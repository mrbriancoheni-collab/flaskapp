#!/bin/bash
#
# Production Automation Runner
# Run this script from ANYWHERE - it will automatically navigate to the correct directories
#

set -e

# Production paths
ENV_FILE="/home/fieljtgr/.env"
APP_DIR="/home/fieljtgr/flaskapp"
VENV_DIR="/home/fieljtgr/virtualenv/flaskapp/3.9"

echo "========================================================================"
echo "PRODUCTION LEAD AUTOMATION RUNNER"
echo "========================================================================"
echo ""

# Load environment variables
if [ -f "$ENV_FILE" ]; then
    echo "✓ Loading environment from $ENV_FILE"
    set -a
    source "$ENV_FILE"
    set +a
else
    echo "ERROR: Environment file not found at $ENV_FILE"
    exit 1
fi

# Check app directory
if [ ! -d "$APP_DIR" ]; then
    echo "ERROR: App directory not found at $APP_DIR"
    exit 1
fi

echo "✓ App directory: $APP_DIR"

# Check for Python (virtualenv or system)
PYTHON_CMD=""
if [ -f "$VENV_DIR/bin/python" ]; then
    PYTHON_CMD="$VENV_DIR/bin/python"
    echo "✓ Using virtualenv: $VENV_DIR"
elif [ -f "$APP_DIR/venv/bin/python" ]; then
    PYTHON_CMD="$APP_DIR/venv/bin/python"
    echo "✓ Using virtualenv: $APP_DIR/venv"
else
    PYTHON_CMD="python3"
    echo "⚠ Using system python3 (virtualenv not found)"
fi

# Navigate to app directory
cd "$APP_DIR"
echo "✓ Changed to $APP_DIR"
echo ""

# Check current status
echo "Checking current automation status..."
echo ""
$PYTHON_CMD run_lead_automation.py --dry-run
echo ""

# Ask for confirmation
read -p "Run the full automation now? This will scrape, enrich, and send emails. (yes/no): " -r
echo ""
if [[ ! $REPLY =~ ^[Yy]([Ee][Ss])?$ ]]; then
    echo "Aborted."
    exit 0
fi

# Run automation in a loop
echo "Starting automation runs..."
echo ""

RUN_COUNT=0
MAX_RUNS=20  # Increased to handle all 20 campaigns

while [ $RUN_COUNT -lt $MAX_RUNS ]; do
    RUN_COUNT=$((RUN_COUNT + 1))

    echo "========================================================================"
    echo "RUN #$RUN_COUNT - $(date)"
    echo "========================================================================"
    echo ""

    # Run the automation
    $PYTHON_CMD run_lead_automation.py

    EXIT_CODE=$?

    if [ $EXIT_CODE -ne 0 ]; then
        echo ""
        echo "ERROR: Automation run failed with exit code $EXIT_CODE"
        echo "Check logs above for details"
        exit $EXIT_CODE
    fi

    echo ""
    echo "Run #$RUN_COUNT complete."
    echo ""

    # Brief pause before next iteration
    sleep 3
done

echo ""
echo "========================================================================"
echo "AUTOMATION COMPLETE"
echo "========================================================================"
echo ""
echo "Progress saved to: $APP_DIR/automation_state.json"
echo ""
