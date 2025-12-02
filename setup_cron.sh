#!/bin/bash
# Setup cron job for lead generation automation

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}Lead Generation Automation - Cron Setup${NC}"
echo -e "${BLUE}================================================${NC}"
echo ""

# Get the absolute path to the Flask app
FLASK_APP_DIR="/home/user/flaskapp"
LOG_DIR="/home/user/flaskapp/logs"
LOG_FILE="$LOG_DIR/automation.log"

# Create logs directory if it doesn't exist
mkdir -p "$LOG_DIR"

# Determine which Python/Flask to use
if command -v flask &> /dev/null; then
    FLASK_CMD="flask"
elif command -v python3 &> /dev/null; then
    FLASK_CMD="python3 -m flask"
else
    echo -e "${YELLOW}Warning: Flask not found in PATH${NC}"
    FLASK_CMD="flask"
fi

echo -e "${GREEN}Configuration:${NC}"
echo "  App Directory: $FLASK_APP_DIR"
echo "  Log File: $LOG_FILE"
echo "  Flask Command: $FLASK_CMD"
echo ""

# Create the cron job entry
CRON_ENTRY="0 9 * * * cd $FLASK_APP_DIR && $FLASK_CMD run-lead-automation >> $LOG_FILE 2>&1"

echo -e "${YELLOW}Cron Job to be added:${NC}"
echo "  Schedule: Daily at 9:00 AM"
echo "  Command: cd $FLASK_APP_DIR && $FLASK_CMD run-lead-automation"
echo "  Log: $LOG_FILE"
echo ""

# Check if cron job already exists
if crontab -l 2>/dev/null | grep -q "run-lead-automation"; then
    echo -e "${YELLOW}Cron job already exists!${NC}"
    echo ""
    echo -e "${BLUE}Current cron jobs:${NC}"
    crontab -l | grep "run-lead-automation"
    echo ""
    read -p "Do you want to replace it? (y/n) " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Aborted."
        exit 0
    fi
    # Remove old entry
    crontab -l | grep -v "run-lead-automation" | crontab -
fi

# Add new cron job
(crontab -l 2>/dev/null; echo "$CRON_ENTRY") | crontab -

echo -e "${GREEN}✓ Cron job installed successfully!${NC}"
echo ""
echo -e "${BLUE}Current cron jobs:${NC}"
crontab -l
echo ""
echo -e "${GREEN}================================================${NC}"
echo -e "${GREEN}Setup Complete!${NC}"
echo -e "${GREEN}================================================${NC}"
echo ""
echo "The automation will run daily at 9:00 AM and:"
echo "  • Create and scrape up to 50 campaigns"
echo "  • Enrich up to 100 leads"
echo "  • Send up to 250 emails"
echo "  • Skip Sundays for emails"
echo ""
echo "To view logs:"
echo "  tail -f $LOG_FILE"
echo ""
echo "To manually run now:"
echo "  cd $FLASK_APP_DIR && $FLASK_CMD run-lead-automation"
echo ""
echo "To remove the cron job:"
echo "  crontab -e"
echo "  (then delete the line with 'run-lead-automation')"
echo ""
