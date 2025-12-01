# app/services/lead_enrichment.py
"""
Lead Enrichment Service

Finds decision makers and email addresses for scraped companies using:
1. Email format discovery (Google search for [company] email format)
2. LinkedIn search for owners/marketers
3. Google search for contact info
"""
import os
import re
import logging
from typing import Optional, Dict, List
import requests
from urllib.parse import quote_plus
from app.services.serpapi_scraper import should_exclude_domain

logger = logging.getLogger(__name__)


class LeadEnrichmentService:
    """Enrich lead data with decision maker contacts"""

    def __init__(self):
        self.serpapi_key = os.getenv('SERPAPI_API_KEY')

    def enrich_lead(self, company_name: str, website: Optional[str]) -> Dict:
        """
        Enrich a lead with contact information

        Returns dict with:
        - email_format: Detected email format (e.g., "first@domain.com")
        - decision_maker_name: Name of owner/marketer
        - decision_maker_title: Job title
        - decision_maker_email: Constructed email
        - decision_maker_linkedin: LinkedIn profile URL
        """
        result = {
            'email_format': None,
            'decision_maker_name': None,
            'decision_maker_title': None,
            'decision_maker_email': None,
            'decision_maker_linkedin': None
        }

        if not website:
            logger.warning(f"No website for {company_name}, skipping enrichment")
            return result

        # Skip excluded domains (.gov, .org, review sites, etc.)
        if should_exclude_domain(website):
            logger.info(f"Skipping enrichment for excluded domain: {website}")
            return result

        domain = self._extract_domain(website)
        if not domain:
            logger.warning(f"Could not extract domain from {website}")
            return result

        # Step 1: Find email format
        email_format = self._find_email_format(company_name, domain)
        result['email_format'] = email_format

        # Step 2: Find decision maker on LinkedIn
        linkedin_info = self._find_decision_maker_linkedin(company_name)
        if linkedin_info:
            result['decision_maker_name'] = linkedin_info.get('name')
            result['decision_maker_title'] = linkedin_info.get('title')
            result['decision_maker_linkedin'] = linkedin_info.get('url')

            # Step 3: Construct email if we have format and name
            if email_format and result['decision_maker_name']:
                result['decision_maker_email'] = self._construct_email(
                    result['decision_maker_name'],
                    domain,
                    email_format
                )

        return result

    def _extract_domain(self, website: str) -> Optional[str]:
        """Extract clean domain from website URL"""
        domain = website.replace('http://', '').replace('https://', '').replace('www.', '')
        domain = domain.split('/')[0].split('?')[0]
        return domain if '.' in domain else None

    def _find_email_format(self, company_name: str, domain: str) -> Optional[str]:
        """
        Find email format by searching Google for "[company] email format"

        Returns format like "first@domain", "firstname.lastname@domain", etc.
        """
        if not self.serpapi_key:
            logger.warning("No SERPAPI_API_KEY, skipping email format search")
            return None

        try:
            # Search for email format
            query = f'"{company_name}" email format OR contact email'
            params = {
                'api_key': self.serpapi_key,
                'engine': 'google',
                'q': query,
                'num': 10
            }

            response = requests.get('https://serpapi.com/search', params=params, timeout=20)
            response.raise_for_status()
            data = response.json()

            # Look for email patterns in snippets
            email_pattern = re.compile(r'[\w.-]+@' + re.escape(domain), re.IGNORECASE)

            for result in data.get('organic_results', [])[:5]:
                snippet = result.get('snippet', '')
                matches = email_pattern.findall(snippet)

                if matches:
                    # Analyze the first match to determine format
                    email = matches[0].lower()
                    local_part = email.split('@')[0]

                    # Detect common formats
                    if '.' in local_part:
                        if len(local_part.split('.')) == 2:
                            return f"firstname.lastname@{domain}"
                    elif len(local_part) <= 10:  # Likely just first name
                        return f"first@{domain}"
                    else:
                        return f"firstnamelastname@{domain}"

            # Default assumption if no pattern found
            return f"first@{domain}"

        except Exception as e:
            logger.error(f"Error finding email format: {e}")
            return f"first@{domain}"  # Fallback

    def _find_decision_maker_linkedin(self, company_name: str) -> Optional[Dict]:
        """
        Find company owner/marketer on LinkedIn via Google search

        Returns dict with name, title, linkedin_url
        """
        if not self.serpapi_key:
            logger.warning("No SERPAPI_API_KEY, skipping LinkedIn search")
            return None

        try:
            # Search LinkedIn for owner/founder
            query = f'site:linkedin.com/in "{company_name}" (owner OR founder OR CEO OR president OR marketing OR manager)'
            params = {
                'api_key': self.serpapi_key,
                'engine': 'google',
                'q': query,
                'num': 5
            }

            response = requests.get('https://serpapi.com/search', params=params, timeout=20)
            response.raise_for_status()
            data = response.json()

            # Parse first LinkedIn result
            for result in data.get('organic_results', []):
                link = result.get('link', '')
                if 'linkedin.com/in/' in link:
                    title = result.get('title', '')
                    snippet = result.get('snippet', '')

                    # Extract name from title (usually "Name - Title - Company")
                    name_match = re.match(r'([^-|]+)', title)
                    name = name_match.group(1).strip() if name_match else None

                    # Extract title
                    title_match = re.search(r'(Owner|Founder|CEO|President|Marketing|Manager|Director)', snippet, re.IGNORECASE)
                    job_title = title_match.group(1) if title_match else 'Owner'

                    if name:
                        return {
                            'name': name,
                            'title': job_title,
                            'url': link
                        }

        except Exception as e:
            logger.error(f"Error finding LinkedIn profile: {e}")

        return None

    def _construct_email(self, full_name: str, domain: str, email_format: str) -> str:
        """Construct email address based on format"""
        # Clean name
        name_parts = full_name.lower().split()
        first_name = name_parts[0] if len(name_parts) > 0 else ''
        last_name = name_parts[-1] if len(name_parts) > 1 else ''

        # Apply format
        if 'firstname.lastname' in email_format:
            return f"{first_name}.{last_name}@{domain}"
        elif 'firstlast' in email_format or 'firstnamelastname' in email_format:
            return f"{first_name}{last_name}@{domain}"
        elif 'first' in email_format:
            return f"{first_name}@{domain}"
        elif 'flast' in email_format:
            return f"{first_name[0]}{last_name}@{domain}"
        else:
            # Default: first@domain
            return f"{first_name}@{domain}"
