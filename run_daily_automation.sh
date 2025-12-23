#!/bin/bash
#
# Lead Automation Runner
# Runs daily lead generation automation with all required environment variables
#
# IMPORTANT: Copy this to run_daily_automation_production.sh and add your actual API keys
#

# Change to app directory
cd /home/fieljtgr/flaskapp || exit 1

# Set environment variables (REPLACE WITH YOUR ACTUAL VALUES)
export EMAIL_PROVIDER="brevo"
export BREVO_API_KEY="YOUR_BREVO_API_KEY_HERE"
export BREVO_FROM_EMAIL="your-email@fieldsprout.io"
export BREVO_FROM_NAME="Your Name from FieldSprout"
export SERPAPI_API_KEY="YOUR_SERPAPI_KEY_HERE"
export SQLALCHEMY_DATABASE_URI="mysql+pymysql://username:password@localhost/database?charset=utf8mb4"

# Create logs directory if it doesn't exist
mkdir -p /home/fieljtgr/flaskapp/logs

# Run automation
echo "========================================" >> /home/fieljtgr/flaskapp/logs/automation.log
echo "Starting automation at $(date)" >> /home/fieljtgr/flaskapp/logs/automation.log
echo "========================================" >> /home/fieljtgr/flaskapp/logs/automation.log

/home/fieljtgr/virtualenv/flaskapp/3.9/bin/python -m flask run-lead-automation >> /home/fieljtgr/flaskapp/logs/automation.log 2>&1

EXIT_CODE=$?

echo "========================================" >> /home/fieljtgr/flaskapp/logs/automation.log
echo "Automation finished at $(date) with exit code: $EXIT_CODE" >> /home/fieljtgr/flaskapp/logs/automation.log
echo "========================================" >> /home/fieljtgr/flaskapp/logs/automation.log

exit $EXIT_CODE
