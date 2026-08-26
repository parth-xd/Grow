"""
Cross-process training progress, for the Data Coverage panel's ETA.

Model training runs in more than one place — the scheduler thread inside the
Flask process, and standalone scripts run from a terminal — so an in-memory
counter would be invisible to whichever process serves /api/data-health.
State therefore lives in a small JSON file that any process can write and
the API can read.

Writes are atomic (tempfile + fsync + os.replace). A half-written progress
file would be parsed as corrupt state by the reader, and this file is
updated once per symbol during a ~6 minute run, so a torn write is a real
possibility rather than a theoretical one.

Stale-job handling: a crashed trainer leaves a "running" record forever.
Anything that hasn't advanced in STALE_AFTER_SECONDS is reported as stale so
the UI can stop promising an ETA that will never arrive.
"""

import fcntl
import json
import logging
import os
import tempfile
import time
from contextlib import contextmanager

logger = logging.getLogger(__name__)

_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "training_progress.json")
_LOCK_PATH = _PATH + ".lock"


@contextmanager
def _locked():
    """
    Serialise the whole read-modify-write, not just the write.

    Atomic replace alone is not enough: advance() reads the file, increments,
    then writes. Two concurrent trainers can both read `done=11`, and the
    later write clobbers the earlier one — observed live as the counter going
    BACKWARDS (13 -> 11) and the ETA swinging wildly. An flock around the
    full sequence is what actually makes the increment safe.

    Never raises: progress reporting must not be able to break training.
    """
    f = None
    try:
        f = open(_LOCK_PATH, "w")
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        yield
    except Exception as e:
        logger.debug("training progress lock failed (continuing unlocked): %s", e)
        yield
    finally:
        if f is not None:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
            try:
                f.close()
            except Exception:
                pass

# A single symbol's GBC+XGB training is seconds; a minute of silence means
# the job died rather than that it is merely slow.
STALE_AFTER_SECONDS = 300


def _read_raw():
    try:
        with open(_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def _write_raw(data):
    """Atomic replace — never leave a partially written progress file."""
    try:
        d = os.path.dirname(_PATH)
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".tp_", suffix=".json")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, _PATH)
        except Exception:
            try:
                os.unlink(tmp)
            except Exception:
                pass
            raise
    except Exception as e:
        logger.debug("training progress write failed: %s", e)


def start(job, total, label=None):
    """Begin (or restart) a job with a known total number of units."""
    with _locked():
        data = _read_raw()
        data[job] = {
            "job": job,
            "label": label or job,
            "total": int(total),
            "done": 0,
            "started_at": time.time(),
            "updated_at": time.time(),
            "state": "running",
            "current": None,
        }
        _write_raw(data)


def advance(job, current=None, n=1):
    """Mark n units complete. `current` names what was just finished."""
    with _locked():
        data = _read_raw()
        rec = data.get(job)
        if not rec:
            return
        rec["done"] = int(rec.get("done", 0)) + n
        rec["updated_at"] = time.time()
        if current:
            rec["current"] = current
        _write_raw(data)


def finish(job):
    with _locked():
        data = _read_raw()
        rec = data.get(job)
        if rec:
            rec["state"] = "done"
            rec["updated_at"] = time.time()
            rec["finished_at"] = time.time()
            _write_raw(data)


def snapshot():
    """
    Current progress for every job, with a derived ETA.

    eta_seconds is None when there is nothing to project from (no units done
    yet, or the job is finished/stale) rather than a fabricated number — a
    made-up countdown is worse than no countdown.
    """
    out = {}
    now = time.time()
    for job, rec in _read_raw().items():
        total = int(rec.get("total") or 0)
        done = int(rec.get("done") or 0)
        state = rec.get("state", "running")
        updated = float(rec.get("updated_at") or 0)

        if state == "running" and now - updated > STALE_AFTER_SECONDS:
            state = "stale"

        eta = None
        if state == "running" and done > 0 and total > done:
            elapsed = now - float(rec.get("started_at") or now)
            if elapsed > 0:
                eta = int((elapsed / done) * (total - done))

        out[job] = {
            "label": rec.get("label", job),
            "total": total,
            "done": done,
            "state": state,
            "current": rec.get("current"),
            "eta_seconds": eta,
            "elapsed_seconds": int(now - float(rec.get("started_at") or now)),
            "pct": round(done / total * 100, 1) if total else 0.0,
        }
    return out
