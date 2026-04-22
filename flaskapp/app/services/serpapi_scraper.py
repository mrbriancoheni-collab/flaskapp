# app/services/serpapi_scraper.py
"""
SERP Scraping Service using SerpAPI (Legal, Compliant approach)

Uses the official SerpAPI service to scrape Google search results for:
- Search Ads (paid ads at top/bottom)
- Google Maps / Local Pack
- Local Services Ads (LSA)
- Organic results (local companies)
"""
import os
import logging
import time
from typing import List, Dict, Any, Optional
import requests

logger = logging.getLogger(__name__)


def should_exclude_domain(url_or_domain: str) -> bool:
    """
    Check if a domain should be excluded from scraping/enrichment.

    Excludes:
    - Government sites (.gov)
    - Non-profit organizations (.org)
    - Review/aggregator sites (Yelp, HomeAdvisor, etc.)

    Args:
        url_or_domain: URL or domain to check

    Returns:
        True if domain should be excluded, False otherwise
    """
    if not url_or_domain:
        return True

    domain = url_or_domain.lower()

    # Check for excluded TLDs
    if domain.endswith('.gov') or '.gov/' in domain:
        return True
    if domain.endswith('.org') or '.org/' in domain:
        return True

    # Check for review/aggregator/social/forum sites
    excluded_domains = [
        # Review & aggregator sites
        'yelp.com', 'yelp.',
        'yellowpages.com', 'yellowpages.',
        'thumbtack.com', 'thumbtack.',
        'angi.com', 'angi.', 'angieslist.com',
        'homeadvisor.com', 'homeadvisor.',
        'bbb.org', 'bbb.',
        'porch.com', 'porch.',
        'houzz.com', 'houzz.',
        'nextdoor.com', 'nextdoor.',
        'bark.com', 'bark.',
        'networx.com',
        'fixr.com',
        'tasker.com',
        'tripadvisor.com', 'tripadvisor.',
        'trustpilot.com', 'trustpilot.',
        'glassdoor.com', 'glassdoor.',
        'indeed.com', 'indeed.',
        'manta.com', 'manta.',
        'superpages.com',
        'mapquest.com',
        'whitepages.com',
        # Social media
        'facebook.com', 'facebook.',
        'instagram.com', 'instagram.',
        'twitter.com', 'twitter.',
        'x.com/x.',
        'linkedin.com', 'linkedin.',
        'reddit.com', 'reddit.',
        'quora.com', 'quora.',
        'tiktok.com', 'tiktok.',
        'pinterest.com', 'pinterest.',
        'snapchat.com', 'snapchat.',
        'youtube.com', 'youtube.',
        # Search engines / tech giants (appear in organic results)
        'google.com', 'google.',
        'bing.com', 'bing.',
        'maps.google.',
        # News & general content
        'wikipedia.org', 'wikipedia.',
        'wikihow.com',
        'forbes.com',
        'inc.com',
    ]

    for excluded in excluded_domains:
        if excluded in domain:
            return True

    return False


class SerpAPIScraperService:
    """Scrape Google SERPs using SerpAPI (compliant, legal approach)"""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv('SERPAPI_API_KEY')
        if not self.api_key:
            raise ValueError("SERPAPI_API_KEY environment variable not set")

        self.base_url = "https://serpapi.com/search"

    def scrape_campaign(
        self,
        query: str,
        location: str,
        scrape_ads: bool = True,
        scrape_maps: bool = True,
        scrape_lsa: bool = True,
        scrape_organic: bool = True,
        max_organic: int = 5
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Scrape all result types for a campaign

        Args:
            query: Search query (e.g., "plumbing")
            location: Location (e.g., "New York, NY")
            scrape_ads: Include search ads
            scrape_maps: Include Google Maps results
            scrape_lsa: Include Local Services Ads
            scrape_organic: Include organic results
            max_organic: Max number of organic results

        Returns:
            Dict with keys: 'ads', 'maps', 'lsa', 'organic'
        """
        logger.info(f"Scraping SERP for query='{query}' location='{location}'")

        results = {
            'ads': [],
            'maps': [],
            'lsa': [],
            'organic': []
        }

        try:
            # Make SerpAPI request with retry logic for rate limiting
            params = {
                'api_key': self.api_key,
                'engine': 'google',
                'q': query,
                'location': location,
                'hl': 'en',
                'gl': 'us',
                'google_domain': 'google.com',
                'num': 20,  # Request more results (helps get more organic + triggers more result types)
                'no_cache': 'false',  # Use cache when available to save credits
            }

            # Retry logic for rate limiting (429 errors)
            # Limited to 3 retries to avoid HTTP timeout (max wait: 2+4+8 = 14 seconds)
            max_retries = 3
            retry_delay = 2  # Start with 2 seconds
            response = None

            for attempt in range(max_retries):
                try:
                    response = requests.get(self.base_url, params=params, timeout=30)

                    # Log response details for debugging
                    logger.info(f"SerpAPI response status: {response.status_code}")

                    # Check for rate limiting
                    if response.status_code == 429:
                        if attempt < max_retries - 1:
                            wait_time = retry_delay * (2 ** attempt)  # Exponential backoff
                            logger.warning(f"SerpAPI rate limit hit. Waiting {wait_time}s before retry {attempt + 1}/{max_retries}")
                            time.sleep(wait_time)
                            continue
                        else:
                            # Log the actual response for debugging
                            try:
                                error_data = response.json()
                                logger.error(f"SerpAPI 429 response: {error_data}")
                                actual_error = error_data.get('error', 'Rate limit exceeded')
                                raise requests.RequestException(f"SerpAPI error: {actual_error}")
                            except ValueError:
                                logger.error(f"SerpAPI 429 response body: {response.text[:500]}")
                                raise requests.RequestException(
                                    "SerpAPI rate limit exceeded. Please wait a few minutes before trying again."
                                )

                    # Check for other error status codes
                    if response.status_code != 200:
                        try:
                            error_data = response.json()
                            error_msg = error_data.get('error', 'Unknown error')
                            logger.error(f"SerpAPI error {response.status_code}: {error_msg}")
                            raise requests.RequestException(f"SerpAPI error: {error_msg}")
                        except ValueError:
                            logger.error(f"SerpAPI error {response.status_code}: {response.text[:500]}")
                            response.raise_for_status()

                    response.raise_for_status()
                    break  # Success, exit retry loop

                except requests.RequestException as e:
                    if attempt < max_retries - 1 and response and response.status_code == 429:
                        continue  # Retry
                    raise  # Re-raise if not a rate limit error or last attempt

            data = response.json()

            # Debug: Log what result types are available
            available_keys = [k for k in data.keys() if 'result' in k.lower() or k in ['ads', 'inline_ads', 'local_results', 'local_services']]
            logger.info(f"SerpAPI response contains these result keys: {available_keys}")
            if 'ads' in data:
                logger.debug(f"Found {len(data.get('ads', []))} raw ads in response")
            if 'local_results' in data:
                places_count = len(data.get('local_results', {}).get('places', []))
                logger.debug(f"Found {places_count} places in local_results")
            if 'local_services' in data:
                logger.debug(f"Found {len(data.get('local_services', []))} local services ads")
            if 'organic_results' in data:
                logger.debug(f"Found {len(data.get('organic_results', []))} organic results before filtering")

            # Parse different result types
            if scrape_ads:
                results['ads'] = self._parse_ads(data)

            if scrape_maps:
                results['maps'] = self._parse_maps(data)

            if scrape_lsa:
                results['lsa'] = self._parse_lsa(data)

            if scrape_organic:
                results['organic'] = self._parse_organic(data, max_results=max_organic)

            logger.info(
                f"Scraped {len(results['ads'])} ads, {len(results['maps'])} maps, "
                f"{len(results['lsa'])} LSA, {len(results['organic'])} organic"
            )

            return results

        except requests.RequestException as e:
            logger.error(f"SerpAPI request failed: {e}")
            raise
        except Exception as e:
            logger.error(f"SERP scraping error: {e}")
            raise

    def _parse_ads(self, data: Dict) -> List[Dict[str, Any]]:
        """Parse search ads from SerpAPI response"""
        ads = []
        filtered_count = 0

        # Top ads
        for ad in data.get('ads', []):
            website = ad.get('displayed_link', '')
            source_url = ad.get('link', '')

            # Skip excluded domains
            if should_exclude_domain(website) or should_exclude_domain(source_url):
                filtered_count += 1
                logger.debug(f"Filtered out top ad: {ad.get('title', '')} (domain: {website})")
                continue

            ads.append({
                'company_name': ad.get('title', ''),
                'website': website,
                'source_url': source_url,
                'description': ad.get('description', ''),
                'phone': ad.get('phone'),
                'position': ad.get('position'),
                'extra_data': {
                    'ad_position': ad.get('block_position'),
                    'sitelinks': ad.get('sitelinks', [])
                }
            })

        # Bottom ads (inline ads)
        for ad in data.get('inline_ads', []):
            website = ad.get('displayed_link', '')
            source_url = ad.get('link', '')

            # Skip excluded domains
            if should_exclude_domain(website) or should_exclude_domain(source_url):
                filtered_count += 1
                logger.debug(f"Filtered out inline ad: {ad.get('title', '')} (domain: {website})")
                continue

            ads.append({
                'company_name': ad.get('title', ''),
                'website': website,
                'source_url': source_url,
                'description': ad.get('description', ''),
                'phone': ad.get('phone'),
                'position': ad.get('position'),
                'extra_data': {
                    'ad_position': 'inline',
                    'sitelinks': ad.get('sitelinks', [])
                }
            })

        if filtered_count > 0:
            logger.info(f"Filtered out {filtered_count} ads due to domain exclusions")
        return ads

    def _parse_maps(self, data: Dict) -> List[Dict[str, Any]]:
        """Parse Google Maps / Local Pack results"""
        maps = []
        filtered_count = 0

        local_results = data.get('local_results', {})

        # Places in local pack
        for place in local_results.get('places', []):
            website = place.get('website')
            source_url = place.get('link')

            # Skip excluded domains
            if should_exclude_domain(website) or should_exclude_domain(source_url):
                filtered_count += 1
                logger.debug(f"Filtered out map listing: {place.get('title', '')} (domain: {website})")
                continue

            maps.append({
                'company_name': place.get('title', ''),
                'website': website,
                'phone': place.get('phone'),
                'address': place.get('address'),
                'source_url': source_url,
                'position': place.get('position'),
                'extra_data': {
                    'rating': place.get('rating'),
                    'reviews': place.get('reviews'),
                    'type': place.get('type'),
                    'hours': place.get('hours'),
                    'service_options': place.get('service_options', {}),
                    'gps_coordinates': place.get('gps_coordinates', {})
                }
            })

        if filtered_count > 0:
            logger.info(f"Filtered out {filtered_count} map listings due to domain exclusions")
        return maps

    def _parse_lsa(self, data: Dict) -> List[Dict[str, Any]]:
        """Parse Local Services Ads"""
        lsa = []
        filtered_count = 0

        for ad in data.get('local_services', []):
            website = ad.get('website')
            source_url = ad.get('link')

            # Skip excluded domains
            if should_exclude_domain(website) or should_exclude_domain(source_url):
                filtered_count += 1
                logger.debug(f"Filtered out LSA: {ad.get('title', '')} (domain: {website})")
                continue

            lsa.append({
                'company_name': ad.get('title', ''),
                'website': website,
                'phone': ad.get('phone'),
                'address': ad.get('address'),
                'source_url': source_url,
                'position': ad.get('position'),
                'extra_data': {
                    'rating': ad.get('rating'),
                    'reviews': ad.get('reviews'),
                    'badge': ad.get('badge'),  # "Google Guaranteed" or "Google Screened"
                    'years_in_business': ad.get('years_in_business')
                }
            })

        if filtered_count > 0:
            logger.info(f"Filtered out {filtered_count} LSA listings due to domain exclusions")
        return lsa

    def _parse_organic(self, data: Dict, max_results: int = 5) -> List[Dict[str, Any]]:
        """Parse organic search results (filter for local companies)"""
        organic = []
        filtered_count = 0

        for result in data.get('organic_results', [])[:max_results]:
            website = result.get('link', '')

            # Skip excluded domains (.gov, .org, review sites, etc.)
            if should_exclude_domain(website):
                filtered_count += 1
                logger.debug(f"Filtered out organic result: {result.get('title', '')} (domain: {website})")
                continue

            organic.append({
                'company_name': result.get('title', ''),
                'website': website,
                'source_url': website,
                'description': result.get('snippet', ''),
                'position': result.get('position'),
                'extra_data': {
                    'rich_snippet': result.get('rich_snippet'),
                    'sitelinks': result.get('sitelinks', [])
                }
            })

        if filtered_count > 0:
            logger.info(f"Filtered out {filtered_count} organic results due to domain exclusions")
        return organic

    def get_credits_remaining(self) -> Optional[int]:
        """Check remaining SerpAPI credits"""
        try:
            response = requests.get(
                'https://serpapi.com/account',
                params={'api_key': self.api_key},
                timeout=10
            )
            response.raise_for_status()
            data = response.json()
            return data.get('total_searches_left')
        except Exception as e:
            logger.error(f"Failed to check SerpAPI credits: {e}")
            return None
