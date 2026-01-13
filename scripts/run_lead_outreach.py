#!/usr/bin/env python3
"""
Run Lead Email Outreach Only

Sends emails to enriched leads without scraping or enriching.
Can be run on-demand or via cron.
"""

import sys
import os
import logging

# Add parent directory to path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_ROOT)

# Change to project root directory
os.chdir(PROJECT_ROOT)

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    env_path = os.path.join(PROJECT_ROOT, '.env')
    if os.path.exists(env_path):
        load_dotenv(env_path)
        print(f"Loaded environment from {env_path}")
    else:
        print(f"Warning: .env file not found at {env_path}")
except ImportError:
    print("Warning: python-dotenv not installed, environment variables must be set manually")

from app import create_app
from app.services.lead_automation_service import LeadAutomationService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('/tmp/lead_outreach.log')
    ]
)
logger = logging.getLogger(__name__)


def main():
    """Run lead email outreach."""
    app = create_app()
    with app.app_context():
        logger.info("Starting lead email outreach")

        try:
            service = LeadAutomationService()
            result = service.run_email_outreach()

            logger.info(f"Email outreach complete: {result['sent']} emails sent")
            logger.info(f"Total emails sent: {result['total_emails']}")

            return 0

        except Exception as e:
            logger.error(f"Error during email outreach: {e}", exc_info=True)
            return 1


if __name__ == '__main__':
    sys.exit(main())
