#!/bin/bash
# Groww Trading Bot — auto-restart wrapper
# Restarts the server automatically if it crashes.
# Usage: ./start.sh           (foreground with auto-restart)
#        ./start.sh --once    (single run, no restart)

cd "$(dirname "$0")"

LOG="server.log"
MAX_RESTARTS=50          # max restarts before giving up
COOLDOWN=5               # seconds between restarts
CRASH_WINDOW=60          # if it crashes within this many seconds, count as rapid crash
RAPID_CRASH_LIMIT=5      # stop after this many rapid crashes

lsof -ti:8000 | xargs kill -9 2>/dev/null
sleep 1
source .venv/bin/activate

if [[ "$1" == "--once" ]]; then
    echo "$(date): Starting Groww Trading Bot (single run)" | tee -a "$LOG"
    exec .venv/bin/python3 app.py 2>&1 | tee -a "$LOG"
fi

restart_count=0
rapid_crashes=0

echo "$(date): Groww Trading Bot supervisor starting (auto-restart enabled)" | tee -a "$LOG"

while true; do
    start_time=$(date +%s)
    echo "$(date): Starting server (restart #$restart_count)" | tee -a "$LOG"

    .venv/bin/python3 app.py 2>&1 | tee -a "$LOG"
    exit_code=$?
    end_time=$(date +%s)
    runtime=$((end_time - start_time))

    # Clean exit (e.g. manual stop via Ctrl+C or SIGTERM)
    if [[ $exit_code -eq 0 ]]; then
        echo "$(date): Server exited cleanly (code 0). Not restarting." | tee -a "$LOG"
        break
    fi

    restart_count=$((restart_count + 1))
    echo "$(date): Server crashed (exit code $exit_code, ran ${runtime}s). Restart #$restart_count" | tee -a "$LOG"

    # Track rapid crashes (crash within CRASH_WINDOW seconds)
    if [[ $runtime -lt $CRASH_WINDOW ]]; then
        rapid_crashes=$((rapid_crashes + 1))
        echo "$(date): Rapid crash #$rapid_crashes (ran only ${runtime}s)" | tee -a "$LOG"
        if [[ $rapid_crashes -ge $RAPID_CRASH_LIMIT ]]; then
            echo "$(date): Too many rapid crashes ($rapid_crashes). Stopping." | tee -a "$LOG"
            break
        fi
    else
        rapid_crashes=0  # reset if it ran long enough
    fi

    if [[ $restart_count -ge $MAX_RESTARTS ]]; then
        echo "$(date): Max restarts ($MAX_RESTARTS) reached. Stopping." | tee -a "$LOG"
        break
    fi

    # Kill any orphaned process on the port before restarting
    lsof -ti:8000 | xargs kill -9 2>/dev/null
    echo "$(date): Restarting in ${COOLDOWN}s..." | tee -a "$LOG"
    sleep $COOLDOWN
done
