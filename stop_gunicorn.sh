#!/bin/bash
# Stop Gunicorn script

APP_DIR="/home/fieljtgr/flaskapp"
PID_FILE="$APP_DIR/gunicorn.pid"

if [ ! -f "$PID_FILE" ]; then
    echo "Gunicorn PID file not found. Checking for running processes..."
    PIDS=$(ps aux | grep "[g]unicorn.*passenger_wsgi:application" | awk '{print $2}')
    if [ -z "$PIDS" ]; then
        echo "No Gunicorn processes found."
        exit 0
    else
        echo "Found Gunicorn processes: $PIDS"
        echo "Killing processes..."
        kill $PIDS
        sleep 2
        echo "✓ Gunicorn stopped"
        exit 0
    fi
fi

PID=$(cat "$PID_FILE")
if ps -p "$PID" > /dev/null 2>&1; then
    echo "Stopping Gunicorn (PID: $PID)..."
    kill "$PID"
    sleep 2

    # Force kill if still running
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "Process still running, force killing..."
        kill -9 "$PID"
    fi

    rm -f "$PID_FILE"
    echo "✓ Gunicorn stopped"
else
    echo "Gunicorn not running (stale PID file)"
    rm -f "$PID_FILE"
fi
