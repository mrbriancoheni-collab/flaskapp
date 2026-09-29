# app/services/lead_enrichment.py
"""
Lead Enrichment Service

Finds decision makers and email addresses for scraped companies using:
1. Domain crawler - reads actual emails directly from company website (most reliable)
2. Team page crawler - finds real team contacts from /team, /about, /leadership pages
3. LinkedIn search via SerpAPI - finds decision makers to construct/supplement emails
"""
import os
import re
import logging
from typing import Optional, Dict, List
import requests
from app.services.serpapi_scraper import should_exclude_domain

logger = logging.getLogger(__name__)


class LeadEnrichmentService:
    """Enrich lead data with decision maker contacts"""

    def __init__(self):
        self.serpapi_key = os.getenv('SERPAPI_API_KEY')

    def enrich_lead(self, company_name: str, website: Optional[str]) -> Dict:
        """
        Enrich a lead with contact information.

        Sources (in priority order):
        1. Direct website crawl — reads actual mailto links and email text from
           the company's contact/about pages (real, verified emails)
        2. Team page crawl — reads team/leadership pages for individual contacts
           with their actual emails
        3. LinkedIn via SerpAPI — finds decision maker names; emails are
           constructed from the detected format (supplementary)

        Returns dict with:
        - email_format: Detected email format (e.g., "firstname.lastname@domain")
        - contacts: List of contact dicts (name, title, email, linkedin_url, role_category)
        - decision_maker_name/title/email/linkedin: Legacy first-contact fields
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

        contacts = []
        seen_emails = set()
        seen_names = set()

        # ── Step 1: Crawl website directly for real email addresses ──────────
        direct_email = self._crawl_website_for_email(domain)
        if direct_email:
            logger.info(f"Found direct email for {company_name}: {direct_email}")
            contacts.append({
                'name': company_name,
                'title': 'Contact',
                'email': direct_email,
                'linkedin_url': None,
                'role_category': 'other',
                'email_source': 'website_direct'
            })
            seen_emails.add(direct_email.lower())

            # Derive the email format from a real email we found
            result['email_format'] = self._detect_format_from_email(direct_email, domain)

        # ── Step 2: Crawl team/leadership pages for individual contacts ──────
        team_contacts = self._crawl_team_pages(domain)
        for tc in team_contacts:
            email = (tc.get('email') or '').lower()
            name = tc.get('name', '')
            if not name:
                continue
            # Skip duplicates
            if email and email in seen_emails:
                continue
            if name.lower() in seen_names:
                continue
            contacts.append({
                'name': name,
                'title': tc.get('title'),
                'email': tc.get('email'),
                'linkedin_url': None,
                'role_category': tc.get('role_category', 'other'),
                'email_source': 'website_team_page'
            })
            if email:
                seen_emails.add(email)
            seen_names.add(name.lower())

        # Detect email format from any real team email if not found yet
        if not result['email_format']:
            for tc in team_contacts:
                if tc.get('email') and '@' + domain in tc['email']:
                    result['email_format'] = self._detect_format_from_email(tc['email'], domain)
                    break

        # ── Step 3: SerpAPI email format search (fallback if no real email) ──
        if not result['email_format']:
            result['email_format'] = self._find_email_format(company_name, domain)

        # ── Step 4: LinkedIn search — find named decision makers ─────────────
        linkedin_contacts = self._find_decision_makers_linkedin(
            company_name, domain, result['email_format']
        )
        for lc in linkedin_contacts:
            name = lc.get('name', '')
            email = (lc.get('email') or '').lower()
            if not name or name.lower() in seen_names:
                continue
            if email and email in seen_emails:
                continue
            contacts.append({**lc, 'email_source': 'linkedin'})
            seen_names.add(name.lower())
            if email:
                seen_emails.add(email)

        result['contacts'] = contacts

        # Set legacy fields (first contact with an actual email wins)
        primary = next((c for c in contacts if c.get('email')), contacts[0] if contacts else None)
        if primary:
            result['decision_maker_name'] = primary.get('name')
            result['decision_maker_title'] = primary.get('title')
            result['decision_maker_email'] = primary.get('email')
            result['decision_maker_linkedin'] = primary.get('linkedin_url')

        logger.info(
            f"Enrichment done for {company_name}: {len(contacts)} contacts, "
            f"{sum(1 for c in contacts if c.get('email'))} with email"
        )
        return result

    # ── Domain crawl helpers ─────────────────────────────────────────────────

    def _crawl_website_for_email(self, domain: str) -> Optional[str]:
        """
        Crawl the company's contact/home/about pages and return the first
        real email address found (from mailto links or page text).
        """
        try:
            from app.services.domain_crawler import DomainCrawler
            crawler = DomainCrawler(timeout=10)
            result = crawler.crawl_domain(domain)
            return result.get('email')
        except Exception as e:
            logger.debug(f"Website crawl failed for {domain}: {e}")
            return None

    def _crawl_team_pages(self, domain: str) -> List[Dict]:
        """
        Crawl team/leadership/about pages and return individual contacts
        with their real email addresses and titles.
        """
        try:
            from app.services.domain_crawler import DomainCrawler
            crawler = DomainCrawler(timeout=10)
            return crawler.find_team_contacts(domain)
        except Exception as e:
            logger.debug(f"Team page crawl failed for {domain}: {e}")
            return []

    def _detect_format_from_email(self, email: str, domain: str) -> str:
        """Detect email format pattern from a known real email address."""
        try:
            local = email.split('@')[0].lower()
            # firstname.lastname  (e.g. john.smith)
            if '.' in local:
                parts = local.split('.')
                if len(parts) == 2 and len(parts[0]) > 1 and len(parts[1]) > 1:
                    # could also be f.lastname (single initial before dot)
                    if len(parts[0]) == 1:
                        return f"flast@{domain}"  # f.last → flast pattern
                    return f"firstname.lastname@{domain}"
            # first_last or first-last
            if '_' in local:
                return f"first_last@{domain}"
            if '-' in local:
                return f"first-last@{domain}"
            # flast (single char prefix + surname, no separator)
            # heuristic: short local looks like initial+surname
            if len(local) <= 8 and len(local) >= 4:
                return f"flast@{domain}"
            if len(local) <= 10:
                return f"first@{domain}"
            return f"firstnamelastname@{domain}"
        except Exception:
            return f"first@{domain}"

    # ── Existing helpers (unchanged) ─────────────────────────────────────────

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
            return f"first@{domain}"

        try:
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
                    email = matches[0].lower()
                    local_part = email.split('@')[0]
                    if '.' in local_part and len(local_part.split('.')) == 2:
                        return f"firstname.lastname@{domain}"
                    elif len(local_part) <= 10:
                        return f"first@{domain}"
                    else:
                        return f"firstnamelastname@{domain}"

            return f"first@{domain}"

        except Exception as e:
            logger.error(f"Error finding email format: {e}")
            return f"first@{domain}"

    def _find_decision_makers_linkedin(self, company_name: str, domain: str, email_format: Optional[str]) -> List[Dict]:
        """
        Find multiple decision makers on LinkedIn via Google search.
        Emails are constructed from the detected format (supplementary source).

        Returns list of dicts with name, title, email, linkedin_url, role_category.
        """
        if not self.serpapi_key:
            logger.warning("No SERPAPI_API_KEY, skipping LinkedIn search")
            return []

        contacts = []
        seen_names = set()

        try:
            query = f'site:linkedin.com/in "{company_name}" (owner OR founder OR CEO OR president OR marketing OR director OR manager)'
            params = {
                'api_key': self.serpapi_key,
                'engine': 'google',
                'q': query,
                'num': 20
            }

            response = requests.get('https://serpapi.com/search', params=params, timeout=20)
            response.raise_for_status()
            data = response.json()

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

                job_title, role_category = self._extract_title_and_category(snippet, title)

                if name and job_title:
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

                    if len(contacts) >= 10:
                        break

        except Exception as e:
            logger.error(f"Error finding LinkedIn profiles: {e}")

        return contacts

    def _extract_title_and_category(self, snippet: str, title: str) -> tuple:
        """Extract job title and categorize the role. Returns (job_title, role_category)."""
        combined_text = f"{title} {snippet}".lower()

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

        for pattern, display_title, category in role_patterns:
            if re.search(pattern, combined_text):
                return (display_title, category)

        title_match = re.search(r'(Owner|Founder|CEO|President|Marketing|Manager|Director)', combined_text, re.IGNORECASE)
        if title_match:
            return (title_match.group(1).title(), 'other')

        return ('Contact', 'other')

    def _construct_email(self, full_name: str, domain: str, email_format: str) -> str:
        """Construct email address based on detected format."""
        name_parts = full_name.lower().split()
        first_name = name_parts[0] if name_parts else ''
        last_name = name_parts[-1] if len(name_parts) > 1 else ''
        first_initial = first_name[0] if first_name else ''

        fmt = email_format.lower()
        if 'firstname.lastname' in fmt:
            return f"{first_name}.{last_name}@{domain}"
        elif 'first_last' in fmt:
            return f"{first_name}_{last_name}@{domain}"
        elif 'first-last' in fmt:
            return f"{first_name}-{last_name}@{domain}"
        elif 'f.last' in fmt:
            return f"{first_initial}.{last_name}@{domain}"
        elif 'firstlast' in fmt or 'firstnamelastname' in fmt:
            return f"{first_name}{last_name}@{domain}"
        elif 'flast' in fmt:
            return f"{first_initial}{last_name}@{domain}"
        elif 'first' in fmt:
            return f"{first_name}@{domain}"
        else:
            return f"{first_name}@{domain}"
