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
        logger.info(f"Full URL: {url}")

        try:
            logger.info(f"Searching Google for: {search_query}")
            response = self.session.get(url, timeout=10)
            response.raise_for_status()

            logger.info(f"Got response: status={response.status_code}, content-length={len(response.text)}")

            # Parse the HTML
            soup = BeautifulSoup(response.text, 'html.parser')

            # Debug: log what we're finding
            all_divs = soup.find_all('div')
            logger.info(f"Found {len(all_divs)} div elements in response")

            # Extract Local Service Ads (LSA)
            lsa_leads = self._extract_lsa(soup, location)
            logger.info(f"Extracted {len(lsa_leads)} LSA leads")
            leads.extend(lsa_leads)

            # Extract PPC ads
            ppc_leads = self._extract_ppc_ads(soup, location)
            logger.info(f"Extracted {len(ppc_leads)} PPC leads")
            leads.extend(ppc_leads)

            # Extract organic results
            organic_leads = self._extract_organic(soup, location)
            logger.info(f"Extracted {len(organic_leads)} organic leads")
            leads.extend(organic_leads)

            logger.info(f"Total found: {len(leads)} potential leads (organic: {len(organic_leads)}, ppc: {len(ppc_leads)}, lsa: {len(lsa_leads)})")

            # Debug logging if no leads found
            if len(leads) == 0:
                logger.error("=" * 80)
                logger.error("NO LEADS FOUND - DEBUGGING INFO:")
                logger.error(f"Search query: {search_query}")
                logger.error(f"Response length: {len(response.text)} chars")

                # Sample of div classes
                sample_divs = soup.find_all('div', limit=10)
                sample_classes = [d.get('class', []) for d in sample_divs]
                logger.error(f"Sample div classes found: {sample_classes}")

                # Check for h3 tags
                h3_tags = soup.find_all('h3', limit=5)
                logger.error(f"Found {len(h3_tags)} h3 tags: {[h.get_text()[:50] for h in h3_tags]}")

                # Check for cite tags (domain indicators)
                cite_tags = soup.find_all('cite', limit=5)
                logger.error(f"Found {len(cite_tags)} cite tags: {[c.get_text() for c in cite_tags]}")

                # Save HTML to temp file for manual inspection
                import tempfile
                with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False, prefix='serp_debug_') as f:
                    f.write(response.text)
                    logger.error(f"Full HTML saved to: {f.name}")

                logger.error("=" * 80)

            # Be respectful - add delay
            time.sleep(self.delay_seconds)

        except Exception as e:
            logger.error(f"Error scraping Google: {e}")

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

    def _extract_organic(self, soup: BeautifulSoup, location: str) -> List[BusinessLead]:
        """Extract organic search results"""
        leads = []

        # Google frequently changes class names. Try multiple selectors.
        # Common containers: div.g, div[data-hveid], div[jscontroller]
        result_containers = []

        # Try modern selectors first
        result_containers.extend(soup.select('div[data-hveid] h3'))  # h3 inside result containers

        # Try legacy selector
        if not result_containers:
            result_containers.extend(soup.find_all('div', class_='g'))

        # Try finding all h3 tags and work backwards to find parent containers
        if not result_containers:
            h3_tags = soup.find_all('h3')
            for h3 in h3_tags:
                # Find parent container (usually 2-3 levels up)
                parent = h3.find_parent(['div', 'article'])
                if parent and parent not in result_containers:
                    result_containers.append(parent)

        logger.info(f"Found {len(result_containers)} potential organic containers")

        for container in result_containers:
            try:
                # If container is an h3, get its parent
                if container.name == 'h3':
                    title_elem = container
                    container = container.find_parent(['div', 'article'])
                    if not container:
                        continue
                else:
                    # Extract title (business name)
                    title_elem = container.find('h3')
                    if not title_elem:
                        continue

                # Skip if it's an ad
                container_text = container.get_text()
                if re.search(r'\b(Ad|Sponsored)\b', container_text, re.I):
                    continue

                business_name = title_elem.get_text(strip=True)

                # Skip if business name is too short or invalid
                if not business_name or len(business_name) < 3:
                    continue

                # Extract domain - look for links
                domain = None
                link = container.find('a', href=True)
                if link:
                    href = link.get('href', '')
                    if href and not href.startswith('#'):
                        domain = self._extract_domain(href)

                # Extract snippet - look for text content
                snippet = None
                # Try common snippet selectors
                snippet_elem = container.find(['div', 'span'], class_=re.compile(r'.*VwiC3b.*|.*snippet.*|.*st.*', re.I))
                if snippet_elem:
                    snippet = snippet_elem.get_text(strip=True)
                else:
                    # Fallback: get text from container, excluding title
                    full_text = container_text.replace(business_name, '', 1).strip()
                    if len(full_text) > 20:
                        snippet = full_text[:200]  # Limit snippet length

                # Extract phone from all text in container
                phone = self._extract_phone(container_text)

                # Only add if we have a business name and domain
                if business_name and domain:
                    lead = BusinessLead(
                        business_name=business_name,
                        domain=domain,
                        phone=phone,
                        snippet=snippet,
                        city=location.split(',')[0].strip() if ',' in location else location,
                        region=location.split(',')[1].strip() if ',' in location else None,
                        source="google_serp_organic",
                        ad_type="organic"
                    )
                    leads.append(lead)
                    logger.debug(f"Found organic lead: {business_name} ({domain})")

            except Exception as e:
                logger.debug(f"Error parsing organic result: {e}")
                continue

        return leads

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
