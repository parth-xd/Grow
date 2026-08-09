# Flask reliability service

Keeps the Flask backend running at boot/login and restarts it if it
crashes, so the dashboard (and the iOS app, once it's reachable over
Tailscale) doesn't silently go dark while you're away from this Mac.

This replaces `./start.sh` (foreground, no restart loop) for day-to-day
use — not `./start.sh --once`, which is still fine for quick manual runs
you'll watch and stop yourself. See `com.parthsharma.parths.flask.plist`
for why this runs Python directly instead of going through `start.sh`'s
own restart loop.

## Install

```bash
mkdir -p ~/Library/LaunchAgents
cp launchd/com.parthsharma.parths.flask.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.parthsharma.parths.flask.plist
```

`RunAtLoad` means it also starts automatically next time you log in —
nothing further to do after this.

## Check it's running

```bash
launchctl print gui/$(id -u)/com.parthsharma.parths.flask | head -20
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/api/config
tail -f ~/Library/Logs/ParthS/app.log
```

Note the logs live in `~/Library/Logs/ParthS/`, **not** the project's own
directory. `~/Desktop` is TCC-protected on modern macOS, and launchd's
spawn helper is denied access to it — pointing a log there made every
launch fail with exit 78 (`EX_CONFIG`) before Python even started.

**Two log files, not one — this is deliberate, see "Log rotation" below:**

- `app.log` — everything that goes through Python's `logging` module:
  app-level `logger.info/warning/error(...)` calls and werkzeug's
  per-request access log. This is where almost all volume lives, and it
  self-rotates (`RotatingFileHandler` in `app.py`, 20MB × 5 = 120MB cap).
  **This is the file to `tail -f` day to day.**
- `raw.log` — only what bypasses `logging` entirely: the one-time Flask
  startup banner, `warnings.warn()` deprecation notices, and any stray
  `print()`. Grows once per process (re)start, not once per request, so it
  stays small at this app's actual restart cadence. Not rotated — hasn't
  needed it, revisit if that ever changes.

## Stop it

**Use `./stop-all.sh`** — it now checks for this service first and uses
`launchctl bootout` automatically. Don't `kill` the PID directly: with no
signal handler in `app.py`, a bare kill and a real crash look identical to
launchd, so it just gets relaunched within `ThrottleInterval` (10s).

To stop it *permanently* (survives the next login too):

```bash
launchctl bootout gui/$(id -u)/com.parthsharma.parths.flask
rm ~/Library/LaunchAgents/com.parthsharma.parths.flask.plist
```

## Also keep the Mac from sleeping

This service only helps if macOS itself stays up: System Settings →
Energy Saver / Battery → disable sleep while on power. A `launchd`
service can't do anything for you while the whole machine is asleep.

## Managing the job needs an active GUI session — running it doesn't

`launchctl bootstrap/bootout/print` against `gui/$(id -u)/...` only work
from a real logged-in console session (this is a per-user LaunchAgent,
not a system daemon) — so install/stop/check commands need to be run
sitting at the Mac, not over a headless SSH session with nobody logged
in. Once installed, though, the service itself keeps running across
logout/login and reboot without you needing to be present — this
restriction is only on the *management* commands, not on uptime.

## Known limitations (not fixed in this pass — flagging, not hiding)

- **No graceful shutdown.** `app.py` has no SIGTERM handler, so `bootout`
  kills it immediately — any in-flight broker call or DB/file write is
  cut mid-operation, no rollback. Adding a signal handler to a live
  trading process deserves its own careful pass (ideally with the
  money-safety skill) rather than being bolted on here.
- **The port-8000 cleanup step kills whatever is listening there**, not
  specifically orphaned Python — pre-existing behavior from start.sh,
  carried over rather than introduced here.

## Log rotation

Fixed — `server.log` had grown to 431MB / 6.58M lines with nothing
bounding it. Two files replace it (see above): `app.log` self-rotates
inside Python via `RotatingFileHandler`; `raw.log` catches what's left and
stays small because it only grows on restart.

**Why rotation had to happen inside Python, not from outside.** The usual
external approach (`logrotate` on Linux, `newsyslog` on macOS: rename the
file, let the process pick up a fresh one) doesn't work here. launchd opens
`StandardOutPath`/`StandardErrorPath` once at process start and hands
Python that file descriptor; renaming the file externally doesn't move
where that descriptor points, so the running process keeps appending to
the *renamed* file forever, and the path you renamed it away from stays
empty until the next restart. `RotatingFileHandler` avoids this by owning
the file itself — it closes, renames, and reopens from inside the same
process, so there's no stale descriptor.

**Why two files instead of pointing both at the same path.** They're two
independent writers. If `RotatingFileHandler` rotated a file that launchd's
raw redirection was *also* writing to, the same stale-descriptor problem
would just reappear on the launchd side — its descriptor would keep
appending to whatever the file got renamed to, invisibly.

**A bug worth knowing about, since it's the kind that's easy to reintroduce.**
The first version of this fix added a `logging.StreamHandler()` unconditionally,
for terminal output when running `python3 app.py` directly. Under launchd
that handler writes to real stdout, which launchd redirects to `raw.log` —
so every line landed in *both* files, and `raw.log` grew at the same rate
`server.log` used to. Fixed by gating the `StreamHandler` on
`sys.stdout.isatty()`, so it only exists when a human is actually watching
a terminal. Caught by checking `raw.log`'s growth after deploying, not by
reasoning about it up front — worth re-checking the same way if this area
changes again.

## scheduler.py doesn't need its own service

Verified in app.py's `if __name__ == "__main__":` block (app.py:6867-6875):
`start_scheduler()` runs automatically, in-process, as soon as `app.py`
starts — before `app.run()`. So wrapping `app.py` in launchd already
covers candle collection, trailing-stop monitoring, and the rest of
scheduler.py's tasks; a second launchd job for `scheduler.py` would just
run everything twice.

`run_collector.py` is a separate one-shot debugging script (runs a single
task once, then exits) — unrelated to normal operation, nothing to
supervise there.
