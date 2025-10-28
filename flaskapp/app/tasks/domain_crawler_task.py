"""
Domain Crawler Background Task

Scheduled task to crawl CRM contact domains and enrich with contact information.
Run this via cron job for automated daily enrichment.
"""
import logging
from datetime import datetime, timedelta
from typing import Dict

logger = logging.getLogger(__name__)


def run_daily_crawler(max_domains: int = 50) -> Dict[str, int]:
    """
    Run domain crawler on CRM contacts that need enrichment.

    This function is designed to be run as a scheduled task (cron job).
    It will:
    1. Find contacts with domains that haven't been crawled recently
    2. Crawl their websites for contact info
    3. Update CRM records with found information

    Args:
        max_domains: Maximum number of domains to crawl in this run

    Returns:
        Dictionary with crawl statistics
    """
    from app import db
    from app.models import CRMContact
    from app.services.domain_crawler import DomainCrawler

    logger.info(f"Starting daily domain crawler (max={max_domains})")

    stats = {
        'total_crawled': 0,
        'enriched': 0,
        'emails_found': 0,
        'phones_found': 0,
        'names_found': 0,
        'errors': 0
    }

    try:
        # Find contacts that need crawling:
        # 1. Have a domain
        # 2. Never crawled OR last crawled more than 30 days ago OR missing contact info
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)

        contacts = CRMContact.query.filter(
            CRMContact.domain.isnot(None),
            db.or_(
                CRMContact.last_crawled_at.is_(None),
                CRMContact.last_crawled_at < thirty_days_ago,
                CRMContact.email.is_(None),
                CRMContact.phone.is_(None)
            )
        ).limit(max_domains).all()

        if not contacts:
            logger.info("No contacts need crawling")
            return stats

        logger.info(f"Found {len(contacts)} contacts to crawl")

        crawler = DomainCrawler(timeout=15)

        for contact in contacts:
            try:
                logger.debug(f"Crawling: {contact.domain} ({contact.business_name})")

                result = crawler.crawl_domain(contact.domain)
                stats['total_crawled'] += 1

                # Update contact with found information
                enriched = False

                if result['email'] and not contact.email:
                    contact.email = result['email']
                    stats['emails_found'] += 1
                    enriched = True
                    logger.info(f"Found email for {contact.business_name}: {result['email']}")

                if result['phone'] and not contact.phone:
                    contact.phone = result['phone']
                    stats['phones_found'] += 1
                    enriched = True
                    logger.info(f"Found phone for {contact.business_name}: {result['phone']}")

                if result['name'] and not contact.contact_name:
                    contact.contact_name = result['name']
                    stats['names_found'] += 1
                    enriched = True
                    logger.info(f"Found name for {contact.business_name}: {result['name']}")

                # Always update crawl tracking
                contact.last_crawled_at = datetime.utcnow()
                contact.crawl_attempts += 1

                if enriched:
                    stats['enriched'] += 1

            except Exception as e:
                stats['errors'] += 1
                logger.error(f"Error crawling {contact.domain}: {e}", exc_info=True)
                # Still update crawl attempt counter
                try:
                    contact.crawl_attempts += 1
                except:
                    pass
                continue

        # Commit all changes
        db.session.commit()

        logger.info(
            f"Domain crawler complete: "
            f"crawled={stats['total_crawled']}, "
            f"enriched={stats['enriched']}, "
            f"emails={stats['emails_found']}, "
            f"phones={stats['phones_found']}, "
            f"names={stats['names_found']}, "
            f"errors={stats['errors']}"
        )

    except Exception as e:
        logger.error(f"Fatal error in domain crawler task: {e}", exc_info=True)
        db.session.rollback()
        stats['errors'] += 1

    return stats


if __name__ == "__main__":
    # Allow running directly for testing
    from app import create_app

    app = create_app()
    with app.app_context():
        print("Running domain crawler task...")
        result = run_daily_crawler(max_domains=10)
        print(f"Results: {result}")
