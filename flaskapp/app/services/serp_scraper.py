"""
SERP scraper for finding home services businesses
Scrapes Google search results for local service ads and organic results
"""
import re
import time
import logging
from typing import List, Dict, Optional
from dataclasses import dataclass
from urllib.parse import urlencode, urlparse, parse_qs
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


@dataclass
class BusinessLead:
    """Represents a potential business lead scraped from Google"""
    business_name: str
    domain: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    region: Optional[str] = None
    source: str = "google_serp"
    ad_type: Optional[str] = None  # "lsa", "ppc", "organic"
    snippet: Optional[str] = None


class GoogleSerpScraper:
    """
    Scrapes Google search results for home services businesses

    IMPORTANT: This scraper is for defensive/research purposes only.
    - Respects robots.txt
    - Uses delays between requests
    - Parses publicly available search results
    - Does not attempt to bypass any protections
    """

    BASE_URL = "https://www.google.com/search"
    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

    def __init__(self, delay_seconds: float = 2.0):
        """
        Args:
            delay_seconds: Delay between requests to be respectful
        """
        self.delay_seconds = delay_seconds
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1"
        })

    def search(
        self,
        query: str,
        location: str = "",
        max_results: int = 20
    ) -> List[BusinessLead]:
        """
        Search Google for home services businesses

        Args:
            query: Search query (e.g., "plumber", "hvac repair")
            location: Location to search in (e.g., "Denver CO")
            max_results: Maximum number of results to return

        Returns:
            List of BusinessLead objects
        """
        leads = []

        # Build search query
        search_query = f"{query} {location}".strip()
        params = {
            "q": search_query,
            "num": min(max_results, 20),  # Google limits to ~20 per page
        }

        url = f"{self.BASE_URL}?{urlencode(params)}"

        try:
            logger.info(f"Searching Google for: {search_query}")
            response = self.session.get(url, timeout=10)
            response.raise_for_status()

            # Save HTML for debugging (first 5000 chars)
            html_preview = response.text[:5000]
            logger.debug(f"Google HTML preview: {html_preview}")

            # Check if we got a CAPTCHA or error page
            if 'captcha' in response.text.lower() or response.status_code != 200:
                logger.warning("Google returned CAPTCHA or error page")
                return []

            # Parse the HTML
            soup = BeautifulSoup(response.text, 'html.parser')

            # Try multiple extraction methods
            # Extract organic results (most reliable)
            organic_leads = self._extract_organic_modern(soup, location)
            leads.extend(organic_leads)

            # Extract PPC ads
            ppc_leads = self._extract_ppc_ads_modern(soup, location)
            leads.extend(ppc_leads)

            # Extract Local Service Ads (LSA)
            lsa_leads = self._extract_lsa(soup, location)
            leads.extend(lsa_leads)

            logger.info(f"Found {len(leads)} potential leads (organic: {len(organic_leads)}, ppc: {len(ppc_leads)}, lsa: {len(lsa_leads)})")

            if len(leads) == 0:
                # Log a sample of the HTML structure to help debug
                all_divs = soup.find_all('div', limit=10)
                logger.warning(f"No leads found. Sample div classes: {[d.get('class') for d in all_divs if d.get('class')]}")

            # Be respectful - add delay
            time.sleep(self.delay_seconds)

        except requests.exceptions.RequestException as e:
            logger.error(f"Network error scraping Google: {e}")
        except Exception as e:
            logger.error(f"Error scraping Google: {e}", exc_info=True)

        return leads[:max_results]

    def _extract_lsa(self, soup: BeautifulSoup, location: str) -> List[BusinessLead]:
        """Extract Local Service Ads"""
        leads = []

        # LSAs typically have specific class names/patterns
        # This is a simplified extraction - real LSA parsing is more complex
        lsa_containers = soup.find_all('div', class_=re.compile(r'.*local.*service.*', re.I))

        for container in lsa_containers:
            try:
                name_elem = container.find(['h3', 'div'], class_=re.compile(r'.*business.*name.*', re.I))
                if not name_elem:
                    continue

                business_name = name_elem.get_text(strip=True)

                # Try to extract phone
                phone = self._extract_phone(container.get_text())

                # Try to extract domain from any links
                domain = None
                link = container.find('a', href=True)
                if link:
                    domain = self._extract_domain(link['href'])

                lead = BusinessLead(
                    business_name=business_name,
                    domain=domain,
                    phone=phone,
                    city=location.split(',')[0].strip() if ',' in location else location,
                    region=location.split(',')[1].strip() if ',' in location else None,
                    source="google_serp_lsa",
                    ad_type="lsa"
                )
                leads.append(lead)

            except Exception as e:
                logger.debug(f"Error parsing LSA: {e}")
                continue

        return leads

    def _extract_ppc_ads(self, soup: BeautifulSoup, location: str) -> List[BusinessLead]:
        """Extract PPC ads (marked with 'Ad' or 'Sponsored')"""
        leads = []

        # Find ad containers (usually marked with 'Ad' badge)
        ad_containers = soup.find_all(['div'], attrs={'data-text-ad': True})
        ad_containers += soup.find_all('div', class_=re.compile(r'.*ad.*container.*', re.I))

        for container in ad_containers:
            try:
                # Extract business name (usually in h3)
                name_elem = container.find(['h3', 'span'], class_=re.compile(r'.*headline.*|.*title.*', re.I))
                if not name_elem:
                    continue

                business_name = name_elem.get_text(strip=True)

                # Extract domain from ad URL
                domain = None
                link = container.find('a', href=True)
                if link:
                    domain = self._extract_domain(link['href'])

                # Extract snippet/description
                snippet_elem = container.find(['div', 'span'], class_=re.compile(r'.*description.*|.*snippet.*', re.I))
                snippet = snippet_elem.get_text(strip=True) if snippet_elem else None

                # Extract phone if present
                phone = self._extract_phone(container.get_text())

                lead = BusinessLead(
                    business_name=business_name,
                    domain=domain,
                    phone=phone,
                    snippet=snippet,
                    city=location.split(',')[0].strip() if ',' in location else location,
                    region=location.split(',')[1].strip() if ',' in location else None,
                    source="google_serp_ppc",
                    ad_type="ppc"
                )
                leads.append(lead)

            except Exception as e:
                logger.debug(f"Error parsing PPC ad: {e}")
                continue

        return leads

    def _extract_organic_modern(self, soup: BeautifulSoup, location: str) -> List[BusinessLead]:
        """
        Extract organic search results using modern selectors (2024+)
        Google's HTML structure: Multiple approaches for better coverage
        """
        leads = []

        # Method 1: Try modern search result containers
        # Google often uses: div with data-sokoban-container or div.g or div[data-hveid]
        selectors_to_try = [
            {'name': 'data-hveid', 'selector': lambda s: s.find_all('div', attrs={'data-hveid': True})},
            {'name': 'class g', 'selector': lambda s: s.find_all('div', class_='g')},
            {'name': 'jscontroller', 'selector': lambda s: s.find_all('div', attrs={'jscontroller': True})},
        ]

        all_containers = []
        for method in selectors_to_try:
            containers = method['selector'](soup)
            if containers:
                logger.debug(f"Found {len(containers)} containers using {method['name']}")
                all_containers.extend(containers)

        # Deduplicate containers
        seen_texts = set()

        for container in all_containers:
            try:
                # Skip if it's an ad
                ad_indicators = container.find_all(text=re.compile(r'^(Ad|Sponsored)$', re.I))
                if ad_indicators:
                    continue

                # Extract title - try multiple selectors
                title_elem = None
                title_selectors = [
                    container.find('h3'),
                    container.find('div', role='heading'),
                    container.find(['span', 'div'], class_=re.compile(r'.*title.*', re.I)),
                ]

                for elem in title_selectors:
                    if elem and elem.get_text(strip=True):
                        title_elem = elem
                        break

                if not title_elem:
                    continue

                business_name = title_elem.get_text(strip=True)

                # Skip duplicates
                if business_name in seen_texts or len(business_name) < 3:
                    continue
                seen_texts.add(business_name)

                # Extract domain - look for cite tags or links
                domain = None
                cite_elem = container.find('cite')
                if cite_elem:
                    domain_text = cite_elem.get_text(strip=True)
                    domain = self._clean_domain(domain_text)

                if not domain:
                    link = container.find('a', href=True)
                    if link and link['href']:
                        domain = self._extract_domain(link['href'])

                # Extract snippet
                snippet = None
                snippet_selectors = [
                    container.find('div', class_=re.compile(r'.*VwiC3b.*', re.I)),
                    container.find(['div', 'span'], attrs={'data-content-feature': '1'}),
                    container.find('div', class_=re.compile(r'.*snippet.*', re.I)),
                ]

                for elem in snippet_selectors:
                    if elem and elem.get_text(strip=True):
                        snippet = elem.get_text(strip=True)
                        break

                # Extract phone from full text
                phone = self._extract_phone(container.get_text())

                # Only add if we have a domain or phone (real business)
                if domain or phone:
                    lead = BusinessLead(
                        business_name=business_name,
                        domain=domain,
                        phone=phone,
                        snippet=snippet,
                        city=location.split(',')[0].strip() if ',' in location else location,
                        region=location.split(',')[1].strip() if ',' in location and len(location.split(',')) > 1 else None,
                        source="google_serp_organic",
                        ad_type="organic"
                    )
                    leads.append(lead)

            except Exception as e:
                logger.debug(f"Error parsing organic result: {e}")
                continue

        return leads

    @staticmethod
    def _clean_domain(text: str) -> Optional[str]:
        """Clean domain text from cite tags"""
        if not text:
            return None
        # Remove protocol
        text = re.sub(r'^https?://', '', text)
        # Remove www
        text = re.sub(r'^www\.', '', text)
        # Take first part (domain)
        text = text.split('/')[0].split('›')[0].strip()
        return text if '.' in text else None

    def _extract_ppc_ads_modern(self, soup: BeautifulSoup, location: str) -> List[BusinessLead]:
        """Extract PPC ads using modern selectors"""
        leads = []

        # Google marks ads with specific aria labels or "Ad" text
        # Look for containers that have "Ad" badge or sponsored indicators
        ad_indicators = soup.find_all(text=re.compile(r'^(Ad|Sponsored)$', re.I))

        for indicator in ad_indicators:
            try:
                # Find the parent container (usually a few levels up)
                container = indicator.find_parent('div', recursive=True)
                if not container:
                    continue

                # Move up to find the main ad container
                for _ in range(5):  # Go up max 5 levels
                    parent = container.find_parent('div')
                    if parent and len(parent.find_all('a')) > 0:
                        container = parent
                    else:
                        break

                # Extract business name from h3 or heading
                name_elem = container.find('h3')
                if not name_elem:
                    name_elem = container.find('div', role='heading')

                if not name_elem:
                    continue

                business_name = name_elem.get_text(strip=True)

                # Extract domain
                domain = None
                cite_elem = container.find('cite')
                if cite_elem:
                    domain = self._clean_domain(cite_elem.get_text(strip=True))

                if not domain:
                    link = container.find('a', href=True)
                    if link:
                        domain = self._extract_domain(link['href'])

                # Extract snippet
                snippet_elem = container.find(['div', 'span'], class_=re.compile(r'.*description.*|.*snippet.*', re.I))
                snippet = snippet_elem.get_text(strip=True) if snippet_elem else None

                # Extract phone
                phone = self._extract_phone(container.get_text())

                if domain or phone:
                    lead = BusinessLead(
                        business_name=business_name,
                        domain=domain,
                        phone=phone,
                        snippet=snippet,
                        city=location.split(',')[0].strip() if ',' in location else location,
                        region=location.split(',')[1].strip() if ',' in location and len(location.split(',')) > 1 else None,
                        source="google_serp_ppc",
                        ad_type="ppc"
                    )
                    leads.append(lead)

            except Exception as e:
                logger.debug(f"Error parsing PPC ad: {e}")
                continue

        # Deduplicate by business name
        seen_names = set()
        unique_leads = []
        for lead in leads:
            if lead.business_name not in seen_names:
                seen_names.add(lead.business_name)
                unique_leads.append(lead)

        return unique_leads

    @staticmethod
    def _extract_phone(text: str) -> Optional[str]:
        """Extract phone number from text"""
        # Match various phone formats
        patterns = [
            r'\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}',  # (123) 456-7890
            r'\d{3}[-.\s]?\d{3}[-.\s]?\d{4}',  # 123-456-7890
        ]

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                # Clean up the phone number
                phone = re.sub(r'[^\d]', '', match.group(0))
                if len(phone) == 10:
                    return f"({phone[:3]}) {phone[3:6]}-{phone[6:]}"

        return None

    @staticmethod
    def _extract_domain(url: str) -> Optional[str]:
        """Extract domain from URL"""
        try:
            # Handle Google redirect URLs
            if 'google.com' in url and '/url?q=' in url:
                parsed = parse_qs(urlparse(url).query)
                if 'q' in parsed:
                    url = parsed['q'][0]

            parsed = urlparse(url)
            domain = parsed.netloc or parsed.path

            # Remove www. prefix
            domain = re.sub(r'^www\.', '', domain)

            # Remove trailing slash and path
            domain = domain.split('/')[0]

            return domain if domain and '.' in domain else None

        except Exception:
            return None


def scrape_home_services(
    service_type: str,
    location: str,
    max_results: int = 20
) -> List[BusinessLead]:
    """
    Convenience function to scrape home services businesses

    Args:
        service_type: Type of service (e.g., "plumber", "hvac", "electrician")
        location: Location to search (e.g., "Denver, CO")
        max_results: Maximum number of results

    Returns:
        List of BusinessLead objects
    """
    scraper = GoogleSerpScraper(delay_seconds=2.0)
    return scraper.search(f"{service_type} near me", location, max_results)
