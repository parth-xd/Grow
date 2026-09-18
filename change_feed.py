"""
Change feed — tells open dashboards that something changed, so they refresh
what is on screen instead of polling for it.

Why this exists: everything runs in one process (Flask, the scheduler, the
Telegram commander), and they all write the same stores — paper_trades.json,
trade_journal.json, config_settings. A trade closed from Telegram or by the
5-second monitor after hours was already in those stores, but a dashboard
that was open kept showing the old state until its tab was reopened; the
paper-tab polls only run in market hours and the journal never re-polls.

Two sources feed it:

  1. A file watcher (one daemon thread, one os.stat per file per second)
     that emits a `trades` / `journal` event when the tracker or journal
     file's *content* changes (mtime/size is only the trigger to look).
     Watching the file rather than hooking every writer means every writer
     is covered — bot, paper_trader, trailing_stop, trade_journal, a
     one-off script — without touching a single trade-write path.
  2. Explicit notify() calls for changes that live only in the DB. The one
     caller today is db_manager.set_config (topic `config`, with the key).

Consumers subscribe from the /api/events SSE route in app.py. Each
subscriber owns a bounded queue; a subscriber that stops reading (a closed
phone tab the server has not noticed yet) drops events rather than blocking
anyone else, and is unsubscribed the next time its stream fails to write.

Nothing here is on a money path. notify() never raises.
"""
import hashlib
import logging
import os
import queue
import threading
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_HERE = os.path.dirname(os.path.abspath(__file__))
WATCHED_FILES = {
    "trades": os.path.join(_HERE, "paper_trades.json"),
    "journal": os.path.join(_HERE, "trade_journal.json"),
}
POLL_SECONDS = 1.0
MAX_SUBSCRIBERS = 16      # laptop + phone + a few reloads; beyond this something is leaking
QUEUE_SIZE = 100          # per subscriber; overflow drops, the client refreshes on reconnect anyway

_lock = threading.Lock()
_subscribers = set()
_seq = 0
_watcher = None


def notify(topic, **detail):
    """Broadcast one event to every open stream. Safe to call from any thread."""
    global _seq
    try:
        with _lock:
            _seq += 1
            event = {"id": _seq, "topic": str(topic), "ts": datetime.now(timezone.utc).isoformat(), **detail}
            subs = list(_subscribers)
        for q in subs:
            try:
                q.put_nowait(event)
            except queue.Full:
                pass  # dead or stalled client; its stream will be dropped on the next write
    except Exception as e:
        logger.debug("change_feed.notify failed: %s", e)


def subscribe():
    """Returns a Queue to read events from, or None if the feed is at capacity."""
    q = queue.Queue(maxsize=QUEUE_SIZE)
    with _lock:
        if len(_subscribers) >= MAX_SUBSCRIBERS:
            return None
        _subscribers.add(q)
    return q


def unsubscribe(q):
    with _lock:
        _subscribers.discard(q)


def subscriber_count():
    with _lock:
        return len(_subscribers)


def _stamp(path):
    try:
        st = os.stat(path)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None   # missing file is a state too; appearing later is a change


def _digest(path):
    try:
        with open(path, "rb") as f:
            return hashlib.sha1(f.read()).hexdigest()
    except OSError:
        return None


def _watch_loop():
    # mtime+size is the cheap test; a real change is decided on content.
    # During market hours the tracker is rewritten every 5 s per open
    # position whether or not anything moved, and byte-identical rewrites
    # must not turn into dashboard refreshes — that would be the 5-second
    # poll this feed exists to replace. The ~40 KB read happens only when the
    # stamp changed, so an idle system reads nothing.
    stamps = {t: _stamp(p) for t, p in WATCHED_FILES.items()}
    digests = {t: _digest(p) for t, p in WATCHED_FILES.items()}
    while True:
        time.sleep(POLL_SECONDS)
        for topic, path in WATCHED_FILES.items():
            try:
                st = _stamp(path)
                if st == stamps.get(topic):
                    continue
                stamps[topic] = st
                d = _digest(path)
                if d == digests.get(topic):
                    continue          # rewritten, not changed
                digests[topic] = d
                notify(topic, file=os.path.basename(path))
            except Exception as e:
                logger.debug("change_feed watcher tick failed for %s: %s", topic, e)


def start():
    """Start the file watcher once. Idempotent; never raises."""
    global _watcher
    with _lock:
        if _watcher is not None and _watcher.is_alive():
            return _watcher
        _watcher = threading.Thread(target=_watch_loop, name="change-feed-watcher", daemon=True)
        _watcher.start()
    logger.info("Change feed watching %s", ", ".join(os.path.basename(p) for p in WATCHED_FILES.values()))
    return _watcher
