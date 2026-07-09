#!/bin/bash
# deploy.sh — pull latest from GitHub and sync to production
# Run from anywhere: bash /home/fieldsprout/deploy.sh

set -e

REPO_DIR="/home/fieldsprout/flaskapp-repo"
PROD_DIR="/home/fieldsprout/flaskapp"
REPO_URL="https://github.com/mrbriancoheni-collab/flaskapp.git"

echo "==> Updating repo..."
if [ -d "$REPO_DIR/.git" ]; then
    cd "$REPO_DIR"
    git pull origin main
else
    git clone "$REPO_URL" "$REPO_DIR"
fi

echo "==> Syncing app files to production..."
# Syncs repo's flaskapp/ subdirectory -> /home/fieldsprout/flaskapp/
# Does NOT delete server-only files (no --delete flag)
rsync -av "$REPO_DIR/flaskapp/" "$PROD_DIR/"

echo "==> Syncing agent runner to /home/fieldsprout/run_agents.py..."
sed \
  -e "s|sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'flaskapp'))|sys.path.insert(0, '/home/fieldsprout/flaskapp')|" \
  -e "s|load_environment(os.path.dirname(os.path.abspath(__file__)))|load_environment('/home/fieldsprout')|" \
  "$REPO_DIR/run_agents.py" > /home/fieldsprout/run_agents.py
chown fieldsprout:fieldsprout /home/fieldsprout/run_agents.py

echo "==> Clearing Python bytecode cache..."
find "$PROD_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$PROD_DIR" -type f -name "*.pyc" -delete 2>/dev/null || true

echo "==> Restarting Passenger..."
touch "$PROD_DIR/passenger_wsgi.py"

echo "==> Deploy complete."
