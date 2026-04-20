#!/bin/bash
#
# Force Complete Lead Automation Run
# This will scrape, enrich, and email all pending items
#
# IMPORTANT: Run this on your production server where environment variables are configured
# Make sure these variables are set in your environment or .env file:
# - SQLALCHEMY_DATABASE_URI
# - BREVO_API_KEY
# - BREVO_FROM_EMAIL=brian@fieldsprout.io
# - BREVO_FROM_NAME=Brian @ FieldSprout.io
# - SERPAPI_API_KEY
#

set -e

echo "========================================================================"
echo "FORCE COMPLETE LEAD AUTOMATION"
echo "========================================================================"
echo ""

# Load environment variables from /home/fieldsprout/.env if it exists
if [ -f "/home/fieldsprout/.env" ]; then
    echo "Loading environment variables from /home/fieldsprout/.env"
    set -a  # automatically export all variables
    source /home/fieldsprout/.env
    set +a
    echo "✓ Environment variables loaded"
    echo ""
elif [ -f ".env" ]; then
    echo "Loading environment variables from ./.env"
    set -a
    source .env
    set +a
    echo "✓ Environment variables loaded"
    echo ""
else
    echo "WARNING: No .env file found at /home/fieldsprout/.env or ./.env"
    echo "Environment variables must be already set in the environment"
    echo ""
fi

# Check if virtualenv exists
if [ ! -f "venv/bin/python" ]; then
    echo "ERROR: Virtual environment not found at venv/"
    echo "Please run: python3 -m venv venv && venv/bin/pip install -r flaskapp/requirements.txt"
    exit 1
fi

# Check environment variables
if [ -z "$SQLALCHEMY_DATABASE_URI" ]; then
    echo "ERROR: SQLALCHEMY_DATABASE_URI not set"
    echo "Please set database connection string in /home/fieldsprout/.env"
    exit 1
fi

if [ -z "$BREVO_API_KEY" ]; then
    echo "WARNING: BREVO_API_KEY not set - email sending will not work"
fi

if [ -z "$SERPAPI_API_KEY" ]; then
    echo "WARNING: SERPAPI_API_KEY not set - scraping will not work"
fi

echo "Environment check passed"
echo ""

# Show current status
echo "Checking current automation status..."
echo ""
venv/bin/python3 run_lead_automation.py --dry-run
echo ""

# Ask for confirmation
read -p "Do you want to run the automation now? This will scrape, enrich, and send emails. (yes/no): " -r
echo ""
if [[ ! $REPLY =~ ^[Yy]([Ee][Ss])?$ ]]; then
    echo "Aborted."
    exit 0
fi

# Run automation in a loop until daily limits are hit or all work is done
echo ""
echo "Starting automation runs..."
echo ""

RUN_COUNT=0
MAX_RUNS=10  # Safety limit to prevent infinite loops

while [ $RUN_COUNT -lt $MAX_RUNS ]; do
    RUN_COUNT=$((RUN_COUNT + 1))

    echo "========================================================================"
    echo "RUN #$RUN_COUNT - $(date)"
    echo "========================================================================"
    echo ""

    # Run the automation
    venv/bin/python3 run_lead_automation.py

    EXIT_CODE=$?

    if [ $EXIT_CODE -ne 0 ]; then
        echo ""
        echo "ERROR: Automation run failed with exit code $EXIT_CODE"
        echo "Check logs above for details"
        exit $EXIT_CODE
    fi

    echo ""
    echo "Run #$RUN_COUNT complete. Checking if more work remains..."
    echo ""

    # Check if we've hit daily limits or completed all work
    # The automation service tracks daily stats and will skip if limits are hit

    # Wait a few seconds before next run
    sleep 5
done

echo ""
echo "========================================================================"
echo "AUTOMATION COMPLETE - Reached maximum run count of $MAX_RUNS"
echo "========================================================================"
echo ""
echo "Check automation_state.json for current progress"
echo "If more work remains, run this script again tomorrow or increase MAX_RUNS"
echo ""
