#!/bin/bash
# Fix AI Agent Cron Jobs on Production Server
#
# This script will:
# 1. Update cron jobs to use correct paths
# 2. Create log directories
# 3. Test that agents can run
# 4. Show you the results

echo "=================================="
echo "AI AGENT CRON FIX"
echo "=================================="
echo ""

# Detect the correct base directory
if [ -d "/home/fieljtgr" ]; then
    BASE_DIR="/home/fieljtgr"
elif [ -d "/home/user/flaskapp" ]; then
    BASE_DIR="/home/user/flaskapp"
else
    echo "ERROR: Cannot find flaskapp directory"
    exit 1
fi

echo "✓ Found base directory: $BASE_DIR"

# Detect Python/Flask
if [ -f "$BASE_DIR/venv/bin/python" ]; then
    PYTHON="$BASE_DIR/venv/bin/python"
elif [ -f "$BASE_DIR/virtualenv/bin/python" ]; then
    PYTHON="$BASE_DIR/virtualenv/bin/python"
else
    echo "ERROR: Cannot find Python virtualenv"
    exit 1
fi

echo "✓ Found Python: $PYTHON"

# Create logs directory
mkdir -p "$BASE_DIR/logs"
echo "✓ Created logs directory: $BASE_DIR/logs"

echo ""
echo "=================================="
echo "TESTING AGENT COMMAND"
echo "=================================="
echo ""

# Test the command
echo "Testing: $PYTHON -m flask run-agents --help"
cd "$BASE_DIR" && FLASK_APP=app $PYTHON -m flask run-agents --help 2>&1 | head -20

if [ $? -ne 0 ]; then
    echo ""
    echo "❌ ERROR: Flask command failed"
    echo "This usually means:"
    echo "  1. Database environment variables not set (SQLALCHEMY_DATABASE_URI)"
    echo "  2. Missing .env file in $BASE_DIR"
    echo "  3. Flask app not properly configured"
    echo ""
    echo "Check that .env file exists and contains database credentials"
    exit 1
fi

echo ""
echo "✓ Flask command works!"
echo ""

echo "=================================="
echo "CORRECT CRON CONFIGURATION"
echo "=================================="
echo ""
echo "Add these lines to your crontab with: crontab -e"
echo ""
echo "# AI Agents - Tactical (hourly)"
echo "0 * * * * cd $BASE_DIR && FLASK_APP=app $PYTHON -m flask run-agents --layer tactical >> $BASE_DIR/logs/agents-tactical.log 2>&1"
echo ""
echo "# AI Agents - Operational (every 4 hours)"
echo "0 */4 * * * cd $BASE_DIR && FLASK_APP=app $PYTHON -m flask run-agents --layer operational >> $BASE_DIR/logs/agents-operational.log 2>&1"
echo ""
echo "# AI Agents - Strategic (daily at 6 AM)"
echo "0 6 * * * cd $BASE_DIR && FLASK_APP=app $PYTHON -m flask run-agents --layer strategic >> $BASE_DIR/logs/agents-strategic.log 2>&1"
echo ""
echo "=================================="
echo "OR: Update existing cron jobs"
echo "=================================="
echo ""
echo "Run: crontab -e"
echo ""
echo "Then replace your current agent cron lines with the ones above"
echo ""

# Show current crontab
echo "=================================="
echo "CURRENT CRONTAB"
echo "=================================="
crontab -l 2>/dev/null | grep "run-agents" || echo "(No run-agents jobs found)"
echo ""

echo "=================================="
echo "MANUAL TEST"
echo "=================================="
echo ""
echo "To manually test agents right now, run:"
echo ""
echo "  cd $BASE_DIR"
echo "  FLASK_APP=app $PYTHON -m flask run-agents --layer tactical"
echo ""
echo "This will show you:"
echo "  - If agents can connect to Google Ads"
echo "  - What optimizations they find"
echo "  - Any AI actions created"
echo ""

echo "=================================="
echo "NEXT STEPS"
echo "=================================="
echo ""
echo "1. Update crontab with the commands shown above"
echo "2. Wait for the next hour to pass"
echo "3. Check logs: tail -f $BASE_DIR/logs/agents-tactical.log"
echo "4. Check AI Change Log: https://fieldsprout.io/account/google/ads/ai-change-log"
echo ""
