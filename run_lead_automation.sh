#!/bin/bash
# Lead Automation Runner Script
# Makes it easy to run the automation with proper database connection

echo "========================================="
echo "  Lead Automation Setup"
echo "========================================="
echo ""

# Check if SQLALCHEMY_DATABASE_URI is already set
if [ -z "$SQLALCHEMY_DATABASE_URI" ]; then
    echo "Database connection not configured."
    echo ""
    echo "Please enter your MySQL password for user 'root':"
    read -s DB_PASSWORD
    echo ""

    export SQLALCHEMY_DATABASE_URI="mysql+pymysql://root:${DB_PASSWORD}@localhost:3306/fieldsprout_xyz?charset=utf8mb4"
else
    echo "✓ Database connection already configured"
fi

echo ""
echo "========================================="
echo "  Running Lead Automation..."
echo "========================================="
echo ""

# Run the automation
python3 run_automation.py

EXIT_CODE=$?

echo ""
echo "========================================="
if [ $EXIT_CODE -eq 0 ]; then
    echo "✓ Automation completed successfully!"
else
    echo "✗ Automation failed (exit code: $EXIT_CODE)"
    echo ""
    echo "Common issues:"
    echo "  - Wrong database password"
    echo "  - Database tables not created (run migration first)"
    echo "  - Missing API keys (SERPAPI_KEY, MAILGUN_API_KEY, etc.)"
    echo ""
    echo "Check RUN_AUTOMATION.md for troubleshooting steps"
fi
echo "========================================="

exit $EXIT_CODE
