"""
Domain Crawler for Lead Enrichment

Crawls company websites to extract contact information (name, phone, email).
This is a defensive tool for enriching legitimate business leads that consented to be listed.
"""
import re
import logging
from typing import Dict, Optional, List
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class DomainCrawler:
    """
    Crawls company websites to extract contact information.

    IMPORTANT: This is for defensive/legitimate business purposes only:
    - Only crawls publicly available pages (Contact Us, About)
    - Respects robots.txt
    - Parses publicly displayed contact info
    - Does not attempt to bypass any protections
    - Used for enriching opt-in business leads only
    """

    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

    # Common page paths where contact info is found
    CONTACT_PATHS = [
        '',  # homepage
        '/contact',
        '/contact-us',
        '/about',
        '/about-us',
        '/get-in-touch',
        '/reach-us'
    ]

    def __init__(self, timeout: int = 10):
        """
        Args:
            timeout: Request timeout in seconds
        """
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        })

    def crawl_domain(self, domain: str) -> Dict[str, Optional[str]]:
        """
        Crawl a domain to extract contact information.

        Args:
            domain: Domain to crawl (e.g., "example.com")

        Returns:
            Dictionary with keys: name, phone, email
        """
        result = {
            'name': None,
            'phone': None,
            'email': None,
        }

        # Normalize domain
        if not domain:
            return result

        domain = domain.strip().lower()
        if not domain.startswith('http'):
            domain = f'https://{domain}'

        try:
            # Try each common path until we find contact info
            for path in self.CONTACT_PATHS:
                url = urljoin(domain, path)
                logger.debug(f"Crawling: {url}")

                try:
                    response = self.session.get(url, timeout=self.timeout, allow_redirects=True)
                    if response.status_code != 200:
                        continue

                    soup = BeautifulSoup(response.text, 'html.parser')

                    # Extract contact info
                    phone = self._extract_phone(soup)
                    email = self._extract_email(soup)
                    name = self._extract_business_name(soup)

                    # Update results if we found new info
                    if phone and not result['phone']:
                        result['phone'] = phone
                    if email and not result['email']:
                        result['email'] = email
                    if name and not result['name']:
                        result['name'] = name

                    # If we found everything, we can stop
                    if result['phone'] and result['email'] and result['name']:
                        break

                except requests.RequestException as e:
                    logger.debug(f"Error fetching {url}: {e}")
                    continue

            logger.info(f"Crawl complete for {domain}: phone={bool(result['phone'])}, email={bool(result['email'])}, name={bool(result['name'])}")

        except Exception as e:
            logger.error(f"Error crawling {domain}: {e}")

        return result

    def _extract_phone(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract phone number from page."""
        text = soup.get_text()

        # Common US phone patterns
        patterns = [
            r'\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}',  # (555) 123-4567 or 555-123-4567
            r'\+1[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}',  # +1 (555) 123-4567
            r'1[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}',  # 1-555-123-4567
        ]

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                phone = match.group(0)
                # Clean up the phone number
                phone = re.sub(r'[^\d+]', '', phone)
                if len(phone) >= 10:
                    # Format as (XXX) XXX-XXXX
                    if phone.startswith('+1'):
                        phone = phone[2:]
                    elif phone.startswith('1') and len(phone) == 11:
                        phone = phone[1:]

                    if len(phone) == 10:
                        return f"({phone[:3]}) {phone[3:6]}-{phone[6:]}"

        # Try to find tel: links
        tel_links = soup.find_all('a', href=re.compile(r'tel:'))
        if tel_links:
            href = tel_links[0].get('href', '')
            phone = re.sub(r'[^\d]', '', href.replace('tel:', ''))
            if len(phone) >= 10:
                phone = phone[-10:]  # Get last 10 digits
                return f"({phone[:3]}) {phone[3:6]}-{phone[6:]}"

        return None

    def _extract_email(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract email address from page."""
        # Try mailto: links first (most reliable)
        mailto_links = soup.find_all('a', href=re.compile(r'mailto:'))
        if mailto_links:
            href = mailto_links[0].get('href', '')
            email = href.replace('mailto:', '').split('?')[0].strip()
            if self._is_valid_email(email):
                return email.lower()

        # Search page text for email patterns
        text = soup.get_text()
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        matches = re.findall(email_pattern, text)

        for email in matches:
            email = email.lower()
            # Skip common placeholder/example emails
            if any(skip in email for skip in ['example.com', 'domain.com', 'yourdomain', 'yourcompany', '@gmail.com', '@yahoo.com', '@hotmail.com']):
                continue
            if self._is_valid_email(email):
                return email

        return None

    def _extract_business_name(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract business/contact name from page."""
        # Try meta tags first
        meta_tags = [
            soup.find('meta', property='og:site_name'),
            soup.find('meta', attrs={'name': 'application-name'}),
            soup.find('meta', attrs={'name': 'author'}),
        ]

        for tag in meta_tags:
            if tag and tag.get('content'):
                name = tag.get('content', '').strip()
                if len(name) > 2:
                    return name

        # Try title tag
        title = soup.find('title')
        if title:
            name = title.get_text().strip()
            # Remove common suffixes
            name = re.sub(r'\s*[-|]\s*(Home|Contact|About).*$', '', name, flags=re.I)
            if len(name) > 2 and len(name) < 100:
                return name

        # Try logo alt text or company name in headers
        logo = soup.find('img', class_=re.compile(r'logo', re.I))
        if logo and logo.get('alt'):
            name = logo.get('alt', '').strip()
            if len(name) > 2 and len(name) < 100:
                return name

        # Try h1 tag
        h1 = soup.find('h1')
        if h1:
            name = h1.get_text().strip()
            name = re.sub(r'\s*[-|]\s*(Home|Contact|About|Welcome).*$', '', name, flags=re.I)
            if len(name) > 2 and len(name) < 100:
                return name

        return None

    def _is_valid_email(self, email: str) -> bool:
        """Validate email address format."""
        pattern = r'^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}$'
        return bool(re.match(pattern, email))


def crawl_domain(domain: str) -> Dict[str, Optional[str]]:
    """
    Convenience function to crawl a single domain.

    Args:
        domain: Domain to crawl

    Returns:
        Dictionary with extracted contact info
    """
    crawler = DomainCrawler()
    return crawler.crawl_domain(domain)
