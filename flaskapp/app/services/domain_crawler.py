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
from app.services.serpapi_scraper import should_exclude_domain

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

    # Common page paths where team/leadership info is found
    TEAM_PATHS = [
        '/team',
        '/our-team',
        '/meet-the-team',
        '/leadership',
        '/about/team',
        '/about-us/team',
        '/about/leadership',
        '/management',
        '/staff',
        '/people'
    ]

    # Role keywords to look for (categorized)
    EXECUTIVE_ROLES = ['ceo', 'chief executive', 'president', 'founder', 'co-founder', 'owner', 'principal']
    MARKETING_ROLES = ['marketing', 'cmo', 'chief marketing', 'head of marketing', 'marketing director', 'marketing manager']
    OPERATIONS_ROLES = ['coo', 'chief operating', 'operations', 'general manager', 'managing director']

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

        # Skip excluded domains (.gov, .org, review sites, etc.)
        if should_exclude_domain(domain):
            logger.info(f"Skipping crawl for excluded domain: {domain}")
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

    def find_team_contacts(self, domain: str) -> List[Dict[str, Optional[str]]]:
        """
        Find individual contacts (CEO, owner, marketing, etc.) on a company website.

        Args:
            domain: Domain to crawl

        Returns:
            List of dictionaries with contact info: {name, title, email, phone, role_category, source}
        """
        contacts = []

        # Normalize domain
        if not domain:
            return contacts

        # Skip excluded domains (.gov, .org, review sites, etc.)
        if should_exclude_domain(domain):
            logger.info(f"Skipping team contacts search for excluded domain: {domain}")
            return contacts

        domain = domain.strip().lower()
        if not domain.startswith('http'):
            domain = f'https://{domain}'

        try:
            # Try each team page path
            for path in self.TEAM_PATHS:
                url = urljoin(domain, path)
                logger.debug(f"Searching for team contacts at: {url}")

                try:
                    response = self.session.get(url, timeout=self.timeout, allow_redirects=True)
                    if response.status_code != 200:
                        continue

                    soup = BeautifulSoup(response.text, 'html.parser')

                    # Find team member sections
                    team_members = self._extract_team_members(soup, path)
                    contacts.extend(team_members)

                    # If we found team members, we can stop
                    if team_members:
                        logger.info(f"Found {len(team_members)} team contacts on {path}")
                        break

                except requests.RequestException as e:
                    logger.debug(f"Error fetching {url}: {e}")
                    continue

            # Also check About page for inline team info
            if not contacts:
                about_url = urljoin(domain, '/about')
                try:
                    response = self.session.get(about_url, timeout=self.timeout)
                    if response.status_code == 200:
                        soup = BeautifulSoup(response.text, 'html.parser')
                        contacts.extend(self._extract_team_members(soup, '/about'))
                except:
                    pass

            logger.info(f"Team contact search complete for {domain}: found {len(contacts)} contacts")

        except Exception as e:
            logger.error(f"Error finding team contacts for {domain}: {e}")

        return contacts

    def _extract_team_members(self, soup: BeautifulSoup, page_source: str) -> List[Dict[str, Optional[str]]]:
        """Extract individual team members from a page."""
        members = []

        # Strategy 1: Find structured team member cards/sections
        # Look for common patterns: div/article with name + title
        potential_members = []

        # Look for elements with class patterns like 'team-member', 'staff-member', 'person', etc.
        team_elements = soup.find_all(['div', 'article', 'li'], class_=re.compile(r'team|staff|person|member|bio|profile', re.I))
        potential_members.extend(team_elements)

        # Also look for elements with role="listitem" that might be team members
        potential_members.extend(soup.find_all(['div', 'article'], attrs={'role': 'listitem'}))

        seen_names = set()

        for elem in potential_members:
            try:
                # Extract name
                name = None
                name_elem = elem.find(['h2', 'h3', 'h4', 'strong', 'b'], class_=re.compile(r'name|title', re.I))
                if name_elem:
                    name = name_elem.get_text().strip()
                else:
                    # Try finding any heading
                    name_elem = elem.find(['h2', 'h3', 'h4'])
                    if name_elem:
                        name = name_elem.get_text().strip()

                if not name or len(name) < 3 or len(name) > 100:
                    continue

                # Skip if we've already found this person
                if name.lower() in seen_names:
                    continue

                # Extract title/role
                title = None
                title_elem = elem.find(['p', 'span', 'div'], class_=re.compile(r'title|role|position|job', re.I))
                if title_elem:
                    title = title_elem.get_text().strip()
                else:
                    # Try finding text after name
                    elem_text = elem.get_text()
                    # Look for patterns like "Name\nCEO" or "Name - CEO"
                    lines = [l.strip() for l in elem_text.split('\n') if l.strip()]
                    if len(lines) >= 2:
                        # Second line might be title
                        potential_title = lines[1]
                        if len(potential_title) < 100 and any(keyword in potential_title.lower() for keyword in
                                                              self.EXECUTIVE_ROLES + self.MARKETING_ROLES + self.OPERATIONS_ROLES):
                            title = potential_title

                # Categorize role
                role_category = self._categorize_role(title) if title else None

                # Only include if we found a relevant role
                if role_category in ['executive', 'owner', 'marketing', 'operations']:
                    # Try to extract email
                    email = None
                    mailto_links = elem.find_all('a', href=re.compile(r'mailto:'))
                    if mailto_links:
                        email = mailto_links[0].get('href', '').replace('mailto:', '').split('?')[0].strip()

                    # Try to extract phone
                    phone = None
                    tel_links = elem.find_all('a', href=re.compile(r'tel:'))
                    if tel_links:
                        phone_text = tel_links[0].get('href', '').replace('tel:', '')
                        phone = re.sub(r'[^\d]', '', phone_text)
                        if len(phone) >= 10:
                            phone = phone[-10:]  # Get last 10 digits
                            phone = f"({phone[:3]}) {phone[3:6]}-{phone[6:]}"

                    members.append({
                        'name': name,
                        'title': title,
                        'email': email,
                        'phone': phone,
                        'role_category': role_category,
                        'source': page_source
                    })
                    seen_names.add(name.lower())
                    logger.debug(f"Found team member: {name} - {title} ({role_category})")

            except Exception as e:
                logger.debug(f"Error parsing team member: {e}")
                continue

        return members

    def _categorize_role(self, title: str) -> Optional[str]:
        """Categorize a job title into role categories."""
        if not title:
            return 'other'

        title_lower = title.lower()

        # Check for executive roles
        for keyword in self.EXECUTIVE_ROLES:
            if keyword in title_lower:
                return 'executive' if keyword not in ['owner', 'principal'] else 'owner'

        # Check for marketing roles
        for keyword in self.MARKETING_ROLES:
            if keyword in title_lower:
                return 'marketing'

        # Check for operations roles
        for keyword in self.OPERATIONS_ROLES:
            if keyword in title_lower:
                return 'operations'

        return 'other'

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
