#!/bin/bash
# Find what's sending "Site Alert" emails

echo "=========================================="
echo "FINDING SITE ALERT EMAIL SOURCE"
echo "=========================================="
echo ""

# 1. Check crontab for monitoring jobs
echo "1. Checking crontab for monitoring jobs..."
if crontab -l 2>/dev/null | grep -i "alert\|monitor\|ping\|health\|uptime" > /dev/null; then
    echo "   ⚠ Found monitoring job(s) in crontab:"
    crontab -l 2>/dev/null | grep -i "alert\|monitor\|ping\|health\|uptime"
else
    echo "   ✓ No monitoring jobs in crontab"
fi
echo ""

# 2. Check system crontab
echo "2. Checking system crontab..."
if [ -f /etc/crontab ]; then
    if grep -i "alert\|monitor\|fieldsprout" /etc/crontab 2>/dev/null | grep -v "^#" > /dev/null; then
        echo "   ⚠ Found in /etc/crontab:"
        grep -i "alert\|monitor\|fieldsprout" /etc/crontab | grep -v "^#"
    else
        echo "   ✓ Nothing found in /etc/crontab"
    fi
else
    echo "   ℹ /etc/crontab not accessible"
fi
echo ""

# 3. Check cron.d directory
echo "3. Checking /etc/cron.d/ directory..."
if [ -d /etc/cron.d ]; then
    if grep -r -i "alert\|monitor\|fieldsprout" /etc/cron.d/ 2>/dev/null | grep -v "^#" > /dev/null; then
        echo "   ⚠ Found monitoring in cron.d:"
        grep -r -i "alert\|monitor\|fieldsprout" /etc/cron.d/ 2>/dev/null | grep -v "^#"
    else
        echo "   ✓ Nothing found in /etc/cron.d/"
    fi
else
    echo "   ℹ /etc/cron.d/ not accessible"
fi
echo ""

# 4. Check for monitoring processes
echo "4. Checking for monitoring processes..."
if ps aux | grep -i "monitor\|uptime\|ping.*fieldsprout" | grep -v grep > /dev/null; then
    echo "   ⚠ Found monitoring process:"
    ps aux | grep -i "monitor\|uptime\|ping.*fieldsprout" | grep -v grep
else
    echo "   ✓ No monitoring processes found"
fi
echo ""

# 5. Check mail queue for clues
echo "5. Checking recent emails sent..."
if command -v mailq &> /dev/null; then
    echo "   Mail queue:"
    mailq 2>/dev/null | head -20
else
    echo "   ℹ mailq command not available"
fi
echo ""

# 6. Check mail logs for "Site Alert"
echo "6. Checking mail logs for 'Site Alert'..."
if [ -f /var/log/maillog ]; then
    echo "   Recent 'Site Alert' emails from /var/log/maillog:"
    grep -i "site alert" /var/log/maillog 2>/dev/null | tail -5
elif [ -f /var/log/mail.log ]; then
    echo "   Recent 'Site Alert' emails from /var/log/mail.log:"
    grep -i "site alert" /var/log/mail.log 2>/dev/null | tail -5
else
    echo "   ℹ Mail logs not accessible"
fi
echo ""

# 7. Check for cpanel monitoring config
echo "7. Checking for cPanel monitoring config..."
if [ -f ~/.cpanel/contactinfo ]; then
    echo "   ⚠ Found cPanel contact info file:"
    cat ~/.cpanel/contactinfo
elif [ -f ~/.contactemail ]; then
    echo "   ⚠ Found contact email file:"
    cat ~/.contactemail
else
    echo "   ℹ No cPanel config files found in home directory"
fi
echo ""

# 8. Look for monitoring scripts
echo "8. Searching for monitoring scripts..."
if find /home -name "*monitor*" -o -name "*uptime*" -o -name "*ping*" 2>/dev/null | grep -v ".git\|node_modules\|venv" | head -10; then
    echo "   ⚠ Found monitoring-related files above"
else
    echo "   ✓ No monitoring scripts found"
fi
echo ""

echo "=========================================="
echo "NEXT STEPS:"
echo "=========================================="
echo ""
echo "If monitoring was found in crontab:"
echo "  1. Run: crontab -e"
echo "  2. Comment out the monitoring line (add # at start)"
echo "  3. Save and exit"
echo ""
echo "If this is cPanel monitoring:"
echo "  1. Log into cPanel"
echo "  2. Go to 'Contact Information' or 'Preferences'"
echo "  3. Uncheck 'Notify when site is down'"
echo "  4. Click Save"
echo ""
echo "If still stuck, email your hosting provider:"
echo "  'Please disable all monitoring alerts for fieldsprout.io'"
echo ""
