#!/bin/bash
# Deploy script to force Python to reload all code

echo "🚀 Starting deployment..."

# Clear all Python bytecode cache
echo "🗑️  Clearing Python cache..."
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
find . -type f -name "*.pyc" -delete 2>/dev/null
find . -type f -name "*.pyo" -delete 2>/dev/null

# Restart Passenger
echo "♻️  Restarting application..."
touch tmp/restart.txt

# Kill any lingering processes
echo "🔪 Killing old processes..."
pkill -f "passenger" 2>/dev/null || true

echo "✅ Deployment complete!"
echo ""
echo "📝 Test with:"
echo "curl 'https://fieldsprout.io/admin/test-email?to=youremail@gmail.com'"
