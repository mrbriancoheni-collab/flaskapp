# app/services/company_data_enrichment.py
"""
Company Data Enrichment Service

Enriches company/lead data with firmographics and technographics:
- Phone numbers (main, support, sales)
- Revenue estimates
- Employee count
- Funding information
- Technology stack (CMS, analytics, email, etc.)
- Social media profiles
- Company age and growth metrics

Data sources:
- Clearbit (premium)
- BuiltWith (tech stack)
- Google search (phone, social)
- Domain whois (age)
- LinkedIn company pages
"""
import os
import re
import logging
import requests
from typing import Dict, List, Optional
from datetime import datetime

try:
    import whois
except ImportError:
    whois = None

logger = logging.getLogger(__name__)


class CompanyDataEnrichmentService:
    """Enrich company data with firmographics and technographics"""

    def __init__(self):
        self.clearbit_key = os.getenv('CLEARBIT_API_KEY')
        self.builtwith_key = os.getenv('BUILTWITH_API_KEY')
        self.serpapi_key = os.getenv('SERPAPI_API_KEY')

    def enrich_company(self, domain: str, company_name: Optional[str] = None) -> Dict:
        """
        Enrich company data from multiple sources

        Args:
            domain: Company domain (e.g., "example.com")
            company_name: Company name (optional, for better search)

        Returns:
            {
                'phones': {
                    'main': str,
                    'support': str,
                    'sales': str
                },
                'firmographics': {
                    'employees': int,
                    'employees_range': str (e.g., "50-100"),
                    'revenue': int,
                    'revenue_range': str,
                    'founded_year': int,
                    'industry': str,
                    'description': str
                },
                'technographics': {
                    'cms': str,
                    'analytics': List[str],
                    'advertising': List[str],
                    'email_provider': str,
                    'frameworks': List[str],
                    'all_technologies': List[str]
                },
                'social': {
                    'linkedin': str,
                    'twitter': str,
                    'facebook': str
                },
                'funding': {
                    'total_raised': int,
                    'last_round': str,
                    'investors': List[str]
                }
            }
        """
        result = {
            'phones': {},
            'firmographics': {},
            'technographics': {},
            'social': {},
            'funding': {}
        }

        # 1. Try Clearbit first (most comprehensive)
        if self.clearbit_key:
            clearbit_data = self._enrich_clearbit(domain)
            result = self._merge_data(result, clearbit_data)

        # 2. Get tech stack from BuiltWith
        if self.builtwith_key:
            tech_data = self._enrich_builtwith(domain)
            result['technographics'] = self._merge_data(
                result['technographics'],
                tech_data
            )

        # 3. Search for phone numbers via Google
        if self.serpapi_key and company_name:
            phone_data = self._find_phone_numbers(company_name, domain)
            result['phones'] = self._merge_data(result['phones'], phone_data)

        # 4. Get company age from WHOIS
        domain_age = self._get_domain_age(domain)
        if domain_age:
            result['firmographics']['domain_age_years'] = domain_age

        # 5. Find social profiles via Google
        if self.serpapi_key and company_name:
            social_data = self._find_social_profiles(company_name, domain)
            result['social'] = self._merge_data(result['social'], social_data)

        return result

    def _enrich_clearbit(self, domain: str) -> Dict:
        """Enrich using Clearbit Company API"""
        try:
            headers = {'Authorization': f'Bearer {self.clearbit_key}'}
            response = requests.get(
                f'https://company.clearbit.com/v2/companies/find',
                params={'domain': domain},
                headers=headers,
                timeout=10
            )

            if response.status_code == 404:
                logger.info(f"Clearbit: Company not found for {domain}")
                return {}

            response.raise_for_status()
            data = response.json()

            return {
                'firmographics': {
                    'employees': data.get('metrics', {}).get('employees'),
                    'employees_range': data.get('metrics', {}).get('employeesRange'),
                    'revenue': data.get('metrics', {}).get('annualRevenue'),
                    'revenue_range': data.get('metrics', {}).get('estimatedAnnualRevenue'),
                    'founded_year': data.get('foundedYear'),
                    'industry': data.get('category', {}).get('industry'),
                    'description': data.get('description')
                },
                'phones': {
                    'main': data.get('phone')
                },
                'social': {
                    'linkedin': data.get('linkedin', {}).get('handle'),
                    'twitter': data.get('twitter', {}).get('handle'),
                    'facebook': data.get('facebook', {}).get('handle')
                },
                'technographics': {
                    'all_technologies': data.get('tech', [])
                }
            }

        except Exception as e:
            logger.error(f"Clearbit enrichment error for {domain}: {e}")
            return {}

    def _enrich_builtwith(self, domain: str) -> Dict:
        """Get technology stack from BuiltWith"""
        try:
            response = requests.get(
                'https://api.builtwith.com/v20/api.json',
                params={
                    'KEY': self.builtwith_key,
                    'LOOKUP': domain
                },
                timeout=10
            )
            response.raise_for_status()
            data = response.json()

            if not data.get('Results'):
                return {}

            technologies = data['Results'][0].get('Result', {}).get('Paths', [])

            if not technologies:
                return {}

            tech_categories = {
                'cms': None,
                'analytics': [],
                'advertising': [],
                'email_provider': None,
                'frameworks': [],
                'all_technologies': []
            }

            for path in technologies:
                for tech in path.get('Technologies', []):
                    tech_name = tech.get('Name', '')
                    tech_categories['all_technologies'].append(tech_name)

                    # Categorize technology
                    tech_lower = tech_name.lower()

                    if any(cms in tech_lower for cms in ['wordpress', 'wix', 'squarespace', 'shopify', 'webflow']):
                        tech_categories['cms'] = tech_name
                    elif any(analytics in tech_lower for analytics in ['google analytics', 'mixpanel', 'segment', 'amplitude']):
                        tech_categories['analytics'].append(tech_name)
                    elif any(ad in tech_lower for ad in ['google ads', 'facebook pixel', 'linkedin insight']):
                        tech_categories['advertising'].append(tech_name)
                    elif any(email in tech_lower for email in ['mailchimp', 'sendgrid', 'mailgun', 'postmark']):
                        tech_categories['email_provider'] = tech_name
                    elif any(fw in tech_lower for fw in ['react', 'vue', 'angular', 'next.js', 'gatsby']):
                        tech_categories['frameworks'].append(tech_name)

            return tech_categories

        except Exception as e:
            logger.error(f"BuiltWith enrichment error for {domain}: {e}")
            return {}

    def _find_phone_numbers(self, company_name: str, domain: str) -> Dict:
        """Find phone numbers via Google search"""
        try:
            # Search for phone number
            query = f'"{company_name}" phone number OR contact'
            params = {
                'api_key': self.serpapi_key,
                'engine': 'google',
                'q': query,
                'num': 10
            }

            response = requests.get('https://serpapi.com/search', params=params, timeout=15)
            response.raise_for_status()
            data = response.json()

            phones = {
                'main': None,
                'support': None,
                'sales': None
            }

            # US phone pattern (various formats)
            phone_pattern = re.compile(
                r'(?:\+?1[-.\s]?)?'  # Optional +1
                r'\(?([0-9]{3})\)?'  # Area code
                r'[-.\s]?'
                r'([0-9]{3})'  # Exchange
                r'[-.\s]?'
                r'([0-9]{4})'  # Number
            )

            # Extract from snippets and titles
            for result in data.get('organic_results', []):
                text = f"{result.get('title', '')} {result.get('snippet', '')}"

                matches = phone_pattern.findall(text)
                for match in matches:
                    phone = f"({match[0]}) {match[1]}-{match[2]}"

                    # Categorize phone number
                    text_lower = text.lower()
                    if not phones['main']:
                        phones['main'] = phone
                    elif 'support' in text_lower and not phones['support']:
                        phones['support'] = phone
                    elif 'sales' in text_lower and not phones['sales']:
                        phones['sales'] = phone

                    if all(phones.values()):
                        break

            return phones

        except Exception as e:
            logger.error(f"Phone number search error for {company_name}: {e}")
            return {}

    def _find_social_profiles(self, company_name: str, domain: str) -> Dict:
        """Find social media profiles via Google search"""
        try:
            social = {
                'linkedin': None,
                'twitter': None,
                'facebook': None
            }

            # Search for LinkedIn company page
            query = f'site:linkedin.com/company "{company_name}"'
            params = {
                'api_key': self.serpapi_key,
                'engine': 'google',
                'q': query,
                'num': 3
            }

            response = requests.get('https://serpapi.com/search', params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            for result in data.get('organic_results', []):
                link = result.get('link', '')
                if 'linkedin.com/company/' in link:
                    social['linkedin'] = link
                    break

            # Search for Twitter
            query = f'site:twitter.com "{company_name}"'
            params['q'] = query

            response = requests.get('https://serpapi.com/search', params=params, timeout=10)
            data = response.json()

            for result in data.get('organic_results', []):
                link = result.get('link', '')
                if 'twitter.com/' in link and '/status/' not in link:
                    social['twitter'] = link
                    break

            return social

        except Exception as e:
            logger.error(f"Social profile search error for {company_name}: {e}")
            return {}

    def _get_domain_age(self, domain: str) -> Optional[int]:
        """Get domain age in years using WHOIS"""
        if not whois:
            return None

        try:
            domain_info = whois.whois(domain)

            creation_date = domain_info.creation_date

            # Handle list of dates (some domains return multiple)
            if isinstance(creation_date, list):
                creation_date = creation_date[0]

            if creation_date:
                age = (datetime.now() - creation_date).days / 365.25
                return int(age)

        except Exception as e:
            logger.debug(f"WHOIS lookup error for {domain}: {e}")

        return None

    def _merge_data(self, existing: Dict, new: Dict) -> Dict:
        """Merge new data into existing, preserving non-None values"""
        for key, value in new.items():
            if value:  # Only add non-empty values
                if isinstance(value, dict):
                    if key not in existing:
                        existing[key] = {}
                    existing[key] = self._merge_data(existing[key], value)
                elif isinstance(value, list):
                    if key not in existing:
                        existing[key] = []
                    existing[key].extend(value)
                else:
                    if not existing.get(key):  # Don't overwrite existing values
                        existing[key] = value

        return existing
