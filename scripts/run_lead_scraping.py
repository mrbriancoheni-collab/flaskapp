#!/usr/bin/env python3
"""
Run Lead Scraping Only

Scrapes leads for pending campaigns without enriching or sending emails.
Can be run on-demand or via cron.
"""

import sys
import os
import logging

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.services.lead_automation_service import LeadAutomationService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('/tmp/lead_scraping.log')
    ]
)
logger = logging.getLogger(__name__)


def main():
    """Run lead scraping."""
    app = create_app()
    with app.app_context():
        logger.info("Starting lead scraping")

        try:
            service = LeadAutomationService()
            result = service.run_scraping()

            logger.info(f"Scraping complete: {result['scraped']} campaigns scraped")
            logger.info(f"Total campaigns: {result['total_campaigns']}")

            return 0

        except Exception as e:
            logger.error(f"Error during scraping: {e}", exc_info=True)
            return 1


if __name__ == '__main__':
    sys.exit(main())
