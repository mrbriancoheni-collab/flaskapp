#!/usr/bin/env python3
"""Test if lead_campaigns_routes can be imported"""
import sys
import os

# Add the Flask app directory to Python path
sys.path.insert(0, '/home/user/flaskapp')
os.chdir('/home/user/flaskapp')

print("Testing lead_campaigns_routes import...")
try:
    from flaskapp.app.admin.lead_campaigns_routes import lead_campaigns_bp
    print("✓ Successfully imported lead_campaigns_routes!")
    print(f"✓ Blueprint name: {lead_campaigns_bp.name}")
    print(f"✓ Blueprint URL prefix: {lead_campaigns_bp.url_prefix}")
except Exception as e:
    print(f"✗ Failed to import lead_campaigns_routes")
    print(f"✗ Error type: {type(e).__name__}")
    print(f"✗ Error message: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\nTesting if Flask app can be created...")
try:
    from flaskapp.app import create_app
    app = create_app()
    print("✓ Flask app created successfully!")
    print(f"✓ Registered blueprints: {list(app.blueprints.keys())}")
except Exception as e:
    print(f"✗ Failed to create Flask app")
    print(f"✗ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n✓ All tests passed!")
