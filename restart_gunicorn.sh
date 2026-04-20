#!/bin/bash
# Restart Gunicorn script

APP_DIR="/home/fieldsprout/flaskapp"

echo "Restarting Gunicorn..."
"$APP_DIR/stop_gunicorn.sh"
sleep 1
"$APP_DIR/start_gunicorn.sh"
