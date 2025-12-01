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
        - contacts: List of contact dicts, each containing:
            - name: Full name
            - title: Job title
            - email: Constructed email address
            - linkedin_url: LinkedIn profile URL
            - role_category: Category (executive, owner, marketing, etc.)
        - decision_maker_name: (Legacy, first contact's name)
        - decision_maker_title: (Legacy, first contact's title)
        - decision_maker_email: (Legacy, first contact's email)
        - decision_maker_linkedin: (Legacy, first contact's linkedin)
        """
        result = {
            'email_format': None,
            'contacts': [],
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

        # Step 2: Find multiple decision makers on LinkedIn
        contacts = self._find_decision_makers_linkedin(company_name, domain, email_format)
        result['contacts'] = contacts

        # Set legacy fields for backwards compatibility (use first contact)
        if contacts:
            first_contact = contacts[0]
            result['decision_maker_name'] = first_contact.get('name')
            result['decision_maker_title'] = first_contact.get('title')
            result['decision_maker_email'] = first_contact.get('email')
            result['decision_maker_linkedin'] = first_contact.get('linkedin_url')

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

    def _find_decision_makers_linkedin(self, company_name: str, domain: str, email_format: Optional[str]) -> List[Dict]:
        """
        Find multiple decision makers on LinkedIn via Google search

        Returns list of dicts with name, title, email, linkedin_url, role_category
        """
        if not self.serpapi_key:
            logger.warning("No SERPAPI_API_KEY, skipping LinkedIn search")
            return []

        contacts = []
        seen_names = set()  # Track unique contacts

        try:
            # Search LinkedIn for multiple decision makers
            query = f'site:linkedin.com/in "{company_name}" (owner OR founder OR CEO OR president OR marketing OR director OR manager)'
            params = {
                'api_key': self.serpapi_key,
                'engine': 'google',
                'q': query,
                'num': 10  # Get more results to find multiple contacts
            }

            response = requests.get('https://serpapi.com/search', params=params, timeout=20)
            response.raise_for_status()
            data = response.json()

            # Parse all LinkedIn results
            for result in data.get('organic_results', []):
                link = result.get('link', '')
                if 'linkedin.com/in/' not in link:
                    continue

                title = result.get('title', '')
                snippet = result.get('snippet', '')

                # Extract name from title (usually "Name - Title - Company")
                name_match = re.match(r'([^-|]+)', title)
                name = name_match.group(1).strip() if name_match else None

                if not name or name in seen_names:
                    continue

                # Extract title and categorize role
                job_title, role_category = self._extract_title_and_category(snippet, title)

                if name and job_title:
                    # Construct email if format available
                    contact_email = None
                    if email_format and domain:
                        contact_email = self._construct_email(name, domain, email_format)

                    contacts.append({
                        'name': name,
                        'title': job_title,
                        'email': contact_email,
                        'linkedin_url': link,
                        'role_category': role_category
                    })

                    seen_names.add(name)

                    # Limit to top 5 contacts to avoid overwhelming
                    if len(contacts) >= 5:
                        break

        except Exception as e:
            logger.error(f"Error finding LinkedIn profiles: {e}")

        return contacts

    def _extract_title_and_category(self, snippet: str, title: str) -> tuple:
        """
        Extract job title and categorize the role

        Returns (job_title, role_category)
        """
        combined_text = f"{title} {snippet}".lower()

        # Define role patterns and their categories
        role_patterns = [
            # Executive roles
            (r'\b(ceo|chief executive officer)\b', 'CEO', 'executive'),
            (r'\b(president)\b', 'President', 'executive'),
            (r'\b(coo|chief operating officer)\b', 'COO', 'executive'),
            (r'\b(cto|chief technology officer)\b', 'CTO', 'executive'),
            (r'\b(cfo|chief financial officer)\b', 'CFO', 'executive'),
            (r'\b(cmo|chief marketing officer)\b', 'CMO', 'executive'),

            # Owner/Founder
            (r'\b(owner|co-owner)\b', 'Owner', 'owner'),
            (r'\b(founder|co-founder)\b', 'Founder', 'owner'),

            # Marketing roles
            (r'\b(marketing director|director of marketing)\b', 'Marketing Director', 'marketing'),
            (r'\b(marketing manager|manager of marketing)\b', 'Marketing Manager', 'marketing'),
            (r'\b(head of marketing)\b', 'Head of Marketing', 'marketing'),
            (r'\b(vp marketing|vice president of marketing)\b', 'VP Marketing', 'marketing'),

            # Operations roles
            (r'\b(operations director|director of operations)\b', 'Operations Director', 'operations'),
            (r'\b(operations manager|manager of operations)\b', 'Operations Manager', 'operations'),
            (r'\b(general manager)\b', 'General Manager', 'operations'),

            # Sales roles
            (r'\b(sales director|director of sales)\b', 'Sales Director', 'sales'),
            (r'\b(sales manager|manager of sales)\b', 'Sales Manager', 'sales'),
            (r'\b(vp sales|vice president of sales)\b', 'VP Sales', 'sales'),
        ]

        # Try to match patterns
        for pattern, display_title, category in role_patterns:
            if re.search(pattern, combined_text):
                return (display_title, category)

        # Fallback: extract any title-like text
        title_match = re.search(r'(Owner|Founder|CEO|President|Marketing|Manager|Director)', combined_text, re.IGNORECASE)
        if title_match:
            return (title_match.group(1).title(), 'other')

        return ('Contact', 'other')

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
