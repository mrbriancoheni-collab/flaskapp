#!/bin/bash
# Quick fix: Restart Flask app

echo "Restarting Flask application..."

# Try multiple restart methods
echo "Method 1: Touch passenger_wsgi.py"
touch /home/fieljtgr/flaskapp/flaskapp/passenger_wsgi.py 2>&1

echo "Method 2: Touch restart.txt"
mkdir -p /home/fieljtgr/flaskapp/tmp
touch /home/fieljtgr/flaskapp/tmp/restart.txt 2>&1

echo "Method 3: passenger-config restart"
passenger-config restart-app /home/fieljtgr/flaskapp 2>&1 || echo "passenger-config not available"

echo ""
echo "Flask app restart attempted!"
echo "Wait 10 seconds then try loading the site again."
echo ""
echo "If still not working, check error logs at:"
echo "  - ~/app_error.log"
echo "  - /home/fieljtgr/logs/"
echo ""
echo "Or temporarily disable new features by commenting out these lines in app/__init__.py:"
echo "  Lines 785-790 (conversations_bp)"
echo "  Lines 793-798 (email_webhook_bp)"
