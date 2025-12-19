#!/bin/bash
# Verification script for lead automation

echo "================================================================================"
echo "LEAD AUTOMATION VERIFICATION"
echo "================================================================================"
echo ""

# 1. Check automation state
echo "1. AUTOMATION STATE:"
echo "-------------------"
if [ -f /home/fieljtgr/flaskapp/automation_state.json ]; then
    cat /home/fieljtgr/flaskapp/automation_state.json
else
    echo "⚠️  State file not found at /home/fieljtgr/flaskapp/automation_state.json"
fi
echo ""
echo ""

# 2. Check recent automation logs
echo "2. RECENT AUTOMATION LOGS (Last 30 lines):"
echo "-------------------------------------------"
if [ -f /home/fieljtgr/flaskapp/logs/automation.log ]; then
    tail -30 /home/fieljtgr/flaskapp/logs/automation.log
else
    echo "⚠️  Log file not found at /home/fieljtgr/flaskapp/logs/automation.log"
fi
echo ""
echo ""

# 3. Check for errors in logs
echo "3. ERRORS IN LOGS:"
echo "------------------"
if [ -f /home/fieljtgr/flaskapp/logs/automation.log ]; then
    ERROR_COUNT=$(grep -i "error" /home/fieljtgr/flaskapp/logs/automation.log | tail -10 | wc -l)
    if [ $ERROR_COUNT -gt 0 ]; then
        echo "⚠️  Found $ERROR_COUNT recent errors:"
        grep -i "error" /home/fieljtgr/flaskapp/logs/automation.log | tail -10
    else
        echo "✅ No errors found in recent logs"
    fi
else
    echo "⚠️  Log file not found"
fi
echo ""
echo ""

# 4. Check current cron job
echo "4. CURRENT CRON JOB:"
echo "--------------------"
crontab -l 2>&1 | grep -A 2 -B 2 "automation\|lead" || echo "⚠️  No cron job found with 'automation' or 'lead'"
echo ""
echo ""

echo "================================================================================"
echo "VERIFICATION COMPLETE"
echo "================================================================================"
echo ""
echo "Next steps:"
echo "1. Check if 'last_run' is not null in automation state"
echo "2. Check if 'campaigns_scraped' increased from 0"
echo "3. Look for 'AUTOMATION COMPLETE' in logs"
echo "4. If errors found, review the error messages above"
echo ""
