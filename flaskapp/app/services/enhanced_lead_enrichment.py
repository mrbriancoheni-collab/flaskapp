# app/services/enhanced_lead_enrichment.py
"""
Enhanced Lead Enrichment Integration

Integrates all enrichment services for maximum data quality:
1. Contact enrichment (email, name, title, LinkedIn)
2. Email verification (deliverability check)
3. Phone number discovery
4. Company firmographics (revenue, employees, industry)
5. Technology stack detection
6. Social media profiles
7. AI personalized email generation

Uses waterfall approach and caching for efficiency
"""
import logging
from typing import Dict, Optional
from datetime import datetime

from app.models_leads import Lead
from app.services.lead_enrichment import LeadEnrichmentService
from app.services.email_verification import EmailVerificationService, EmailStatus
from app.services.company_data_enrichment import CompanyDataEnrichmentService
from app.services.ai_email_personalization import AIEmailPersonalizationService

logger = logging.getLogger(__name__)


class EnhancedLeadEnrichmentService:
    """
    Comprehensive lead enrichment using all available services

    Enrichment pipeline:
    1. Find decision makers and emails (LeadEnrichmentService)
    2. Verify email deliverability (EmailVerificationService)
    3. Enrich company data (CompanyDataEnrichmentService)
    4. Generate personalized emails (AIEmailPersonalizationService)
    """

    def __init__(self):
        self.contact_enrichment = LeadEnrichmentService()
        self.email_verification = EmailVerificationService()
        self.company_enrichment = CompanyDataEnrichmentService()
        self.ai_personalization = AIEmailPersonalizationService()

    def enrich_lead_complete(
        self,
        lead: Lead,
        verify_email: bool = True,
        enrich_company: bool = True,
        generate_personalization: bool = True,
        your_value_prop: Optional[str] = None
    ) -> Dict:
        """
        Perform complete enrichment on a lead

        Args:
            lead: Lead object to enrich
            verify_email: Whether to verify email deliverability
            enrich_company: Whether to fetch company firmographics
            generate_personalization: Whether to generate AI personalized emails
            your_value_prop: Your product/service value prop (for personalization)

        Returns:
            {
                'success': bool,
                'enrichment_score': int (0-100),
                'data_points_found': int,
                'email_deliverable': bool,
                'personalization_ready': bool
            }
        """
        enrichment_score = 0
        data_points = 0
        email_deliverable = False
        personalization_ready = False

        try:
            # Step 1: Contact Enrichment (email, name, title, LinkedIn)
            logger.info(f"Enriching contacts for {lead.company_name}")

            contact_data = self.contact_enrichment.enrich_lead(
                lead.company_name,
                lead.website
            )

            # Update lead with contact data
            if contact_data.get('email_format'):
                lead.email_format = contact_data['email_format']
                data_points += 1
                enrichment_score += 10

            if contact_data.get('decision_maker_name'):
                lead.decision_maker_name = contact_data['decision_maker_name']
                data_points += 1
                enrichment_score += 15

            if contact_data.get('decision_maker_title'):
                lead.decision_maker_title = contact_data['decision_maker_title']
                data_points += 1
                enrichment_score += 10

            if contact_data.get('decision_maker_email'):
                lead.decision_maker_email = contact_data['decision_maker_email']
                data_points += 1
                enrichment_score += 20

            if contact_data.get('decision_maker_linkedin'):
                lead.decision_maker_linkedin = contact_data['decision_maker_linkedin']
                data_points += 1
                enrichment_score += 10

            # Initialize extra_data if needed
            if not lead.extra_data:
                lead.extra_data = {}

            # Store all contacts (not just primary)
            if contact_data.get('contacts'):
                lead.extra_data['all_contacts'] = contact_data['contacts']
                data_points += len(contact_data['contacts'])
                enrichment_score += min(25, len(contact_data['contacts']) * 5)

            # Step 2: Email Verification
            if verify_email and lead.decision_maker_email:
                logger.info(f"Verifying email for {lead.company_name}")

                verification = self.email_verification.verify_email(
                    lead.decision_maker_email
                )

                # Store verification result
                lead.extra_data['email_verification'] = {
                    'status': verification['status'].value,
                    'score': verification['score'],
                    'is_disposable': verification['is_disposable'],
                    'is_role_based': verification['is_role_based'],
                    'is_free_provider': verification['is_free_provider'],
                    'provider': verification['provider'],
                    'reason': verification.get('reason'),
                    'verified_at': datetime.utcnow().isoformat()
                }

                # Check if email is deliverable
                email_deliverable = self.email_verification.should_send_email(verification)

                if email_deliverable:
                    enrichment_score += 15
                else:
                    # Mark as bounced if email is invalid/disposable
                    if verification['status'] in [EmailStatus.INVALID, EmailStatus.DISPOSABLE]:
                        lead.email_status = 'bounced'
                        logger.warning(
                            f"{lead.company_name}: Email marked as bounced - "
                            f"{verification['status'].value}"
                        )

                data_points += 1

            # Step 3: Company Data Enrichment
            if enrich_company and lead.website:
                logger.info(f"Enriching company data for {lead.company_name}")

                domain = self._extract_domain(lead.website)
                if domain:
                    company_data = self.company_enrichment.enrich_company(
                        domain,
                        lead.company_name
                    )

                    # Store in extra_data
                    if company_data.get('phones'):
                        lead.extra_data['phones'] = company_data['phones']
                        # Update lead.phone if main phone found
                        if company_data['phones'].get('main'):
                            lead.phone = company_data['phones']['main']
                            data_points += 1
                            enrichment_score += 10

                    if company_data.get('firmographics'):
                        lead.extra_data['firmographics'] = company_data['firmographics']
                        firm_count = sum(1 for v in company_data['firmographics'].values() if v)
                        data_points += firm_count
                        enrichment_score += min(15, firm_count * 3)

                    if company_data.get('technographics'):
                        lead.extra_data['technographics'] = company_data['technographics']
                        tech_count = len(company_data['technographics'].get('all_technologies', []))
                        if tech_count > 0:
                            data_points += 1
                            enrichment_score += 5

                    if company_data.get('social'):
                        lead.extra_data['social_profiles'] = company_data['social']
                        social_count = sum(1 for v in company_data['social'].values() if v)
                        data_points += social_count
                        enrichment_score += min(10, social_count * 3)

            # Step 4: AI Personalization
            if generate_personalization and lead.decision_maker_name and your_value_prop:
                logger.info(f"Generating personalized email for {lead.company_name}")

                lead_data = {
                    'company_name': lead.company_name,
                    'website': lead.website,
                    'decision_maker_name': lead.decision_maker_name,
                    'decision_maker_title': lead.decision_maker_title,
                    'industry': lead.extra_data.get('firmographics', {}).get('industry')
                }

                personalization = self.ai_personalization.personalize_email(
                    lead_data,
                    your_value_prop,
                    email_type='intro'
                )

                # Store personalized email templates
                if not lead.extra_data.get('personalized_emails'):
                    lead.extra_data['personalized_emails'] = {}

                lead.extra_data['personalized_emails']['intro'] = personalization

                if personalization.get('personalization_score', 0) >= 50:
                    personalization_ready = True
                    enrichment_score += 15
                    data_points += 1

            # Mark enrichment complete
            lead.enrichment_status = 'completed'
            lead.enriched_at = datetime.utcnow()

            # Cap score at 100
            enrichment_score = min(100, enrichment_score)

            logger.info(
                f"Enrichment complete for {lead.company_name}: "
                f"Score={enrichment_score}, DataPoints={data_points}, "
                f"EmailDeliverable={email_deliverable}"
            )

            return {
                'success': True,
                'enrichment_score': enrichment_score,
                'data_points_found': data_points,
                'email_deliverable': email_deliverable,
                'personalization_ready': personalization_ready
            }

        except Exception as e:
            logger.error(f"Error enriching {lead.company_name}: {e}")
            lead.enrichment_status = 'failed'

            return {
                'success': False,
                'enrichment_score': enrichment_score,
                'data_points_found': data_points,
                'email_deliverable': False,
                'personalization_ready': False,
                'error': str(e)
            }

    def _extract_domain(self, website: str) -> Optional[str]:
        """Extract clean domain from website URL"""
        domain = website.replace('http://', '').replace('https://', '').replace('www.', '')
        domain = domain.split('/')[0].split('?')[0]
        return domain if '.' in domain else None

    def generate_follow_up_emails(
        self,
        lead: Lead,
        your_value_prop: str,
        num_follow_ups: int = 3
    ) -> Dict:
        """
        Generate full email sequence (intro + follow-ups) for a lead

        Args:
            lead: Enriched lead
            your_value_prop: Your product/service value prop
            num_follow_ups: Number of follow-up emails (default 3)

        Returns:
            {
                'intro': {...},
                'follow_up_1': {...},
                'follow_up_2': {...},
                'follow_up_3': {...}
            }
        """
        if not lead.extra_data:
            lead.extra_data = {}

        if not lead.extra_data.get('personalized_emails'):
            lead.extra_data['personalized_emails'] = {}

        lead_data = {
            'company_name': lead.company_name,
            'website': lead.website,
            'decision_maker_name': lead.decision_maker_name,
            'decision_maker_title': lead.decision_maker_title,
            'industry': lead.extra_data.get('firmographics', {}).get('industry')
        }

        email_types = ['intro', 'follow_up_1', 'follow_up_2', 'follow_up_3']

        for i, email_type in enumerate(email_types[:num_follow_ups + 1]):
            if email_type not in lead.extra_data['personalized_emails']:
                personalization = self.ai_personalization.personalize_email(
                    lead_data,
                    your_value_prop,
                    email_type=email_type
                )

                lead.extra_data['personalized_emails'][email_type] = personalization

        return lead.extra_data['personalized_emails']
