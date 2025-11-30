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
from typing import List, Dict, Any, Optional
import requests

logger = logging.getLogger(__name__)


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
            # Make SerpAPI request
            params = {
                'api_key': self.api_key,
                'engine': 'google',
                'q': query,
                'location': location,
                'hl': 'en',
                'gl': 'us',
                'google_domain': 'google.com'
            }

            response = requests.get(self.base_url, params=params, timeout=30)
            response.raise_for_status()

            data = response.json()

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

        # Top ads
        for ad in data.get('ads', []):
            ads.append({
                'company_name': ad.get('title', ''),
                'website': ad.get('displayed_link', ''),
                'source_url': ad.get('link', ''),
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
            ads.append({
                'company_name': ad.get('title', ''),
                'website': ad.get('displayed_link', ''),
                'source_url': ad.get('link', ''),
                'description': ad.get('description', ''),
                'phone': ad.get('phone'),
                'position': ad.get('position'),
                'extra_data': {
                    'ad_position': 'inline',
                    'sitelinks': ad.get('sitelinks', [])
                }
            })

        return ads

    def _parse_maps(self, data: Dict) -> List[Dict[str, Any]]:
        """Parse Google Maps / Local Pack results"""
        maps = []

        local_results = data.get('local_results', {})

        # Places in local pack
        for place in local_results.get('places', []):
            maps.append({
                'company_name': place.get('title', ''),
                'website': place.get('website'),
                'phone': place.get('phone'),
                'address': place.get('address'),
                'source_url': place.get('link'),
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

        return maps

    def _parse_lsa(self, data: Dict) -> List[Dict[str, Any]]:
        """Parse Local Services Ads"""
        lsa = []

        for ad in data.get('local_services', []):
            lsa.append({
                'company_name': ad.get('title', ''),
                'website': ad.get('website'),
                'phone': ad.get('phone'),
                'address': ad.get('address'),
                'source_url': ad.get('link'),
                'position': ad.get('position'),
                'extra_data': {
                    'rating': ad.get('rating'),
                    'reviews': ad.get('reviews'),
                    'badge': ad.get('badge'),  # "Google Guaranteed" or "Google Screened"
                    'years_in_business': ad.get('years_in_business')
                }
            })

        return lsa

    def _parse_organic(self, data: Dict, max_results: int = 5) -> List[Dict[str, Any]]:
        """Parse organic search results (filter for local companies)"""
        organic = []

        for result in data.get('organic_results', [])[:max_results]:
            # Skip aggregators, marketplaces, review sites
            domain = result.get('displayed_link', '').lower()
            if any(x in domain for x in ['yelp', 'yellowpages', 'thumbtack', 'angi', 'homeadvisor', 'bbb.org']):
                continue

            organic.append({
                'company_name': result.get('title', ''),
                'website': result.get('link', ''),
                'source_url': result.get('link', ''),
                'description': result.get('snippet', ''),
                'position': result.get('position'),
                'extra_data': {
                    'rich_snippet': result.get('rich_snippet'),
                    'sitelinks': result.get('sitelinks', [])
                }
            })

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
