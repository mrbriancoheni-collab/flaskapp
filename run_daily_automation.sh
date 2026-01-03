#!/bin/bash
#
# Lead Automation Runner - Auto-detects environment
# Works in both production (/home/fieljtgr/flaskapp) and dev (/home/user/flaskapp)
#

# Detect base directory automatically
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
BASE_DIR="$SCRIPT_DIR"

cd "$BASE_DIR" || exit 1

# Source .env file if it exists
if [ -f "$BASE_DIR/.env" ]; then
    export $(grep -v '^#' "$BASE_DIR/.env" | xargs)
fi

# Set defaults if not in environment
export EMAIL_PROVIDER="${EMAIL_PROVIDER:-brevo}"
export BREVO_FROM_EMAIL="${BREVO_FROM_EMAIL:-noreply@fieldsprout.io}"
export BREVO_FROM_NAME="${BREVO_FROM_NAME:-FieldSprout}"

# Create logs directory
mkdir -p "$BASE_DIR/logs"

# Auto-detect Python virtualenv
if [ -f "$BASE_DIR/venv/bin/python" ]; then
    PYTHON="$BASE_DIR/venv/bin/python"
elif [ -f "$BASE_DIR/virtualenv/bin/python" ]; then
    PYTHON="$BASE_DIR/virtualenv/bin/python"
else
    PYTHON="python3"
fi

# Run automation
echo "========================================" >> "$BASE_DIR/logs/automation.log"
echo "Starting automation at $(date)" >> "$BASE_DIR/logs/automation.log"
echo "Base dir: $BASE_DIR" >> "$BASE_DIR/logs/automation.log"
echo "Python: $PYTHON" >> "$BASE_DIR/logs/automation.log"
echo "========================================" >> "$BASE_DIR/logs/automation.log"

cd "$BASE_DIR/flaskapp" && $PYTHON -m flask run-lead-automation >> "$BASE_DIR/logs/automation.log" 2>&1

EXIT_CODE=$?

echo "========================================" >> "$BASE_DIR/logs/automation.log"
echo "Finished at $(date) with exit code: $EXIT_CODE" >> "$BASE_DIR/logs/automation.log"
echo "========================================" >> "$BASE_DIR/logs/automation.log"

exit $EXIT_CODE
