#!/bin/bash
# Gunicorn startup script for Flask application
# This script starts Gunicorn to serve the Flask app on port 8000

# Configuration
APP_DIR="/home/fieldsprout/flaskapp"
VENV_DIR="/home/fieldsprout/virtualenv/flaskapp/3.9"
BIND_ADDRESS="127.0.0.1:8000"
WORKERS=4
TIMEOUT=120
WORKER_CLASS="sync"
LOG_DIR="$APP_DIR/logs"
ACCESS_LOG="$LOG_DIR/gunicorn_access.log"
ERROR_LOG="$LOG_DIR/gunicorn_error.log"
PID_FILE="$APP_DIR/gunicorn.pid"

# Create logs directory if it doesn't exist
mkdir -p "$LOG_DIR"

# Change to app directory
cd "$APP_DIR" || exit 1

# Activate virtualenv if it exists
if [ -d "$VENV_DIR" ]; then
    source "$VENV_DIR/bin/activate"
    echo "Activated virtualenv at $VENV_DIR"
else
    echo "Warning: Virtualenv not found at $VENV_DIR"
    echo "Looking for virtualenv..."
    # Try to find virtualenv
    if [ -d "/home/fieldsprout/virtualenv" ]; then
        FOUND_VENV=$(find /home/fieldsprout/virtualenv -name "activate" -type f 2>/dev/null | head -1)
        if [ -n "$FOUND_VENV" ]; then
            VENV_DIR=$(dirname "$(dirname "$FOUND_VENV")")
            source "$FOUND_VENV"
            echo "Found and activated virtualenv at $VENV_DIR"
        fi
    fi
fi

# Check if Gunicorn is already running
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if ps -p "$OLD_PID" > /dev/null 2>&1; then
        echo "Gunicorn is already running (PID: $OLD_PID)"
        echo "To restart, run: kill $OLD_PID && $0"
        exit 1
    else
        echo "Removing stale PID file"
        rm -f "$PID_FILE"
    fi
fi

# Start Gunicorn
echo "Starting Gunicorn..."
echo "App directory: $APP_DIR"
echo "Bind address: $BIND_ADDRESS"
echo "Workers: $WORKERS"
echo "Log directory: $LOG_DIR"

gunicorn \
    --bind "$BIND_ADDRESS" \
    --workers "$WORKERS" \
    --timeout "$TIMEOUT" \
    --worker-class "$WORKER_CLASS" \
    --access-logfile "$ACCESS_LOG" \
    --error-logfile "$ERROR_LOG" \
    --pid "$PID_FILE" \
    --daemon \
    passenger_wsgi:application

# Check if Gunicorn started successfully
sleep 2
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "✓ Gunicorn started successfully (PID: $PID)"
        echo "✓ Listening on $BIND_ADDRESS"
        echo "✓ Access log: $ACCESS_LOG"
        echo "✓ Error log: $ERROR_LOG"
        exit 0
    else
        echo "✗ Gunicorn failed to start. Check error log:"
        tail -20 "$ERROR_LOG"
        exit 1
    fi
else
    echo "✗ Gunicorn PID file not created. Check for errors:"
    tail -20 "$ERROR_LOG"
    exit 1
fi
