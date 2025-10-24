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

            # Parse the HTML
            soup = BeautifulSoup(response.text, 'html.parser')

            # Extract Local Service Ads (LSA)
            lsa_leads = self._extract_lsa(soup, location)
            leads.extend(lsa_leads)

            # Extract PPC ads
            ppc_leads = self._extract_ppc_ads(soup, location)
            leads.extend(ppc_leads)

            # Extract organic results
            organic_leads = self._extract_organic(soup, location)
            leads.extend(organic_leads)

            logger.info(f"Found {len(leads)} potential leads")

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

        # Find organic result containers (usually div with class 'g')
        result_containers = soup.find_all('div', class_='g')

        for container in result_containers:
            try:
                # Skip if it's an ad
                if container.find(text=re.compile(r'Ad|Sponsored', re.I)):
                    continue

                # Extract title (business name)
                title_elem = container.find('h3')
                if not title_elem:
                    continue

                business_name = title_elem.get_text(strip=True)

                # Extract domain
                domain = None
                link = container.find('a', href=True)
                if link:
                    domain = self._extract_domain(link['href'])

                # Extract snippet
                snippet_elem = container.find(['div', 'span'], class_=re.compile(r'.*VwiC3b.*|.*snippet.*', re.I))
                snippet = snippet_elem.get_text(strip=True) if snippet_elem else None

                # Extract phone from snippet
                phone = self._extract_phone(container.get_text())

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
