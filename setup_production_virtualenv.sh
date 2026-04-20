#!/bin/bash
#
# Production Virtualenv Setup Script
# Run this on your production server at /home/fieldsprout/flaskapp
#
set -e

echo "Setting up production virtualenv..."

# Base directory (adjust if needed)
PROD_BASE="/home/fieldsprout"
APP_DIR="$PROD_BASE/flaskapp"
VENV_DIR="$PROD_BASE/virtualenv/flaskapp/3.9"

# Check if we're in the right place
if [ ! -d "$APP_DIR" ]; then
    echo "ERROR: App directory not found at $APP_DIR"
    echo "Are you on the production server?"
    exit 1
fi

# Create virtualenv directory structure
echo "Creating virtualenv at $VENV_DIR..."
mkdir -p "$VENV_DIR"

# Find Python 3.9 or use latest Python 3
if command -v python3.9 &> /dev/null; then
    PYTHON_CMD="python3.9"
    echo "Using Python 3.9"
elif command -v python3.11 &> /dev/null; then
    PYTHON_CMD="python3.11"
    echo "Using Python 3.11"
else
    PYTHON_CMD="python3"
    echo "Using system python3"
fi

# Create virtualenv
echo "Creating virtualenv with $PYTHON_CMD..."
$PYTHON_CMD -m venv "$VENV_DIR"

# Verify virtualenv was created
if [ ! -f "$VENV_DIR/bin/python" ]; then
    echo "ERROR: Virtualenv creation failed"
    exit 1
fi

echo "Virtualenv created successfully!"

# Upgrade pip
echo "Upgrading pip..."
"$VENV_DIR/bin/pip" install --upgrade pip

# Install dependencies
echo "Installing dependencies from requirements.txt..."
if [ -f "$APP_DIR/flaskapp/requirements.txt" ]; then
    "$VENV_DIR/bin/pip" install -r "$APP_DIR/flaskapp/requirements.txt"
    echo "Dependencies installed successfully!"
else
    echo "WARNING: requirements.txt not found at $APP_DIR/flaskapp/requirements.txt"
fi

# Verify Flask is installed
if "$VENV_DIR/bin/python" -c "import flask" 2>/dev/null; then
    echo "✓ Flask installed successfully"
else
    echo "✗ Flask installation failed"
    exit 1
fi

# Show Python and pip versions
echo ""
echo "Setup complete!"
echo "Python version: $("$VENV_DIR/bin/python" --version)"
echo "Pip version: $("$VENV_DIR/bin/pip" --version)"
echo "Flask version: $("$VENV_DIR/bin/python" -c 'import flask; print(flask.__version__)')"
echo ""
echo "Virtualenv location: $VENV_DIR"
echo ""
echo "Next steps:"
echo "1. Restart your web server (LiteSpeed/Passenger)"
echo "2. Test the website"
echo "3. Check logs if issues persist"
