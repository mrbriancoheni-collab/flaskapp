#!/bin/bash
# Quick script to check if the site is actually responding

echo "================================"
echo "CHECKING SITE STATUS"
echo "================================"
echo ""

# Check if Gunicorn is running
echo "1. Checking if Gunicorn is running..."
if pgrep -f "gunicorn.*passenger_wsgi" > /dev/null; then
    echo "   ✓ Gunicorn is running"
    ps aux | grep "[g]unicorn.*passenger_wsgi" | head -2
else
    echo "   ✗ Gunicorn is NOT running!"
    echo "   Run: cd /home/fieldsprout/flaskapp && ./start_gunicorn.sh"
fi

echo ""

# Check if port 8000 is listening
echo "2. Checking if port 8000 is listening..."
if netstat -tlnp 2>/dev/null | grep ":8000" > /dev/null; then
    echo "   ✓ Port 8000 is listening"
else
    echo "   ✗ Port 8000 is NOT listening!"
fi

echo ""

# Check health endpoint
echo "3. Checking health endpoint..."
HEALTH_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/__health__ 2>/dev/null)
if [ "$HEALTH_RESPONSE" = "200" ]; then
    echo "   ✓ Health endpoint responding: HTTP $HEALTH_RESPONSE"
else
    echo "   ✗ Health endpoint NOT responding: HTTP $HEALTH_RESPONSE"
fi

echo ""

# Check main site
echo "4. Checking main site..."
SITE_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" https://fieldsprout.io 2>/dev/null)
if [ "$SITE_RESPONSE" = "200" ] || [ "$SITE_RESPONSE" = "302" ]; then
    echo "   ✓ Site responding: HTTP $SITE_RESPONSE"
else
    echo "   ⚠ Site responding with: HTTP $SITE_RESPONSE"
fi

echo ""
echo "================================"
echo "Status check complete!"
echo "================================"
