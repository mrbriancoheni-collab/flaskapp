# app/services/ai_email_personalization.py
"""
AI Email Personalization Service

Uses Claude/GPT-4 to generate highly personalized email introductions based on:
- Company website content
- LinkedIn profile information
- Recent company news
- Industry insights
- Pain points and challenges
- Technology stack

Generates personalized:
- Opening lines
- Value propositions
- Call-to-actions
- Full email sequences
"""
import os
import logging
import requests
from typing import Dict, List, Optional
import anthropic
import openai
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class AIEmailPersonalizationService:
    """AI-powered email personalization for cold outreach"""

    def __init__(self):
        self.anthropic_key = os.getenv('ANTHROPIC_API_KEY')
        self.openai_key = os.getenv('OPENAI_API_KEY')

        if self.anthropic_key:
            self.anthropic_client = anthropic.Anthropic(api_key=self.anthropic_key)
        else:
            self.anthropic_client = None

        if self.openai_key:
            openai.api_key = self.openai_key

    def personalize_email(
        self,
        lead_data: Dict,
        your_value_prop: str,
        email_type: str = 'intro'
    ) -> Dict:
        """
        Generate personalized email content for a lead

        Args:
            lead_data: Dict containing:
                - company_name: str
                - website: str (optional)
                - decision_maker_name: str (optional)
                - decision_maker_title: str (optional)
                - industry: str (optional)
                - website_content: str (optional, scraped content)
            your_value_prop: Your product/service value proposition
            email_type: 'intro', 'follow_up_1', 'follow_up_2', 'follow_up_3'

        Returns:
            {
                'subject': str,
                'intro_line': str,  # Personalized opening
                'body': str,  # Full email body
                'cta': str,  # Call-to-action
                'personalization_score': int (0-100),
                'personalization_elements': List[str]
            }
        """
        # Gather context about the lead
        context = self._gather_context(lead_data)

        # Generate personalized content using AI
        if self.anthropic_client:
            return self._personalize_with_claude(context, your_value_prop, email_type)
        elif self.openai_key:
            return self._personalize_with_gpt(context, your_value_prop, email_type)
        else:
            logger.warning("No AI API key found, using template-based personalization")
            return self._fallback_personalization(lead_data, your_value_prop, email_type)

    def _gather_context(self, lead_data: Dict) -> str:
        """Gather all available context about the lead"""
        context_parts = []

        company_name = lead_data.get('company_name', 'the company')
        context_parts.append(f"Company: {company_name}")

        if lead_data.get('industry'):
            context_parts.append(f"Industry: {lead_data['industry']}")

        if lead_data.get('decision_maker_name'):
            context_parts.append(f"Contact: {lead_data['decision_maker_name']}")

        if lead_data.get('decision_maker_title'):
            context_parts.append(f"Title: {lead_data['decision_maker_title']}")

        # Add website content if available
        if lead_data.get('website_content'):
            context_parts.append(f"\nWebsite content:\n{lead_data['website_content'][:1000]}")
        elif lead_data.get('website'):
            # Try to scrape website
            scraped_content = self._scrape_website_summary(lead_data['website'])
            if scraped_content:
                context_parts.append(f"\nWebsite content:\n{scraped_content}")

        return "\n".join(context_parts)

    def _scrape_website_summary(self, url: str) -> Optional[str]:
        """Scrape website for key information"""
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (compatible; LeadEnrichmentBot/1.0)'}
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')

            # Extract key elements
            summary_parts = []

            # Get title
            if soup.title:
                summary_parts.append(f"Title: {soup.title.string}")

            # Get meta description
            meta_desc = soup.find('meta', attrs={'name': 'description'})
            if meta_desc and meta_desc.get('content'):
                summary_parts.append(f"Description: {meta_desc['content']}")

            # Get first few paragraphs
            paragraphs = soup.find_all('p')[:3]
            if paragraphs:
                text = ' '.join([p.get_text().strip() for p in paragraphs])
                summary_parts.append(f"Content: {text[:500]}")

            return "\n".join(summary_parts) if summary_parts else None

        except Exception as e:
            logger.warning(f"Could not scrape {url}: {e}")
            return None

    def _personalize_with_claude(
        self,
        context: str,
        value_prop: str,
        email_type: str
    ) -> Dict:
        """Generate personalized email using Claude"""
        try:
            prompt = self._build_personalization_prompt(context, value_prop, email_type)

            response = self.anthropic_client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=1000,
                temperature=0.7,
                messages=[{
                    "role": "user",
                    "content": prompt
                }]
            )

            content = response.content[0].text

            # Parse the response
            return self._parse_ai_response(content)

        except Exception as e:
            logger.error(f"Claude personalization error: {e}")
            return self._fallback_personalization({}, value_prop, email_type)

    def _personalize_with_gpt(
        self,
        context: str,
        value_prop: str,
        email_type: str
    ) -> Dict:
        """Generate personalized email using GPT-4"""
        try:
            prompt = self._build_personalization_prompt(context, value_prop, email_type)

            response = openai.chat.completions.create(
                model="gpt-4-turbo-preview",
                messages=[
                    {"role": "system", "content": "You are an expert B2B cold email copywriter who crafts highly personalized, conversion-focused outreach."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=1000
            )

            content = response.choices[0].message.content

            # Parse the response
            return self._parse_ai_response(content)

        except Exception as e:
            logger.error(f"GPT personalization error: {e}")
            return self._fallback_personalization({}, value_prop, email_type)

    def _build_personalization_prompt(
        self,
        context: str,
        value_prop: str,
        email_type: str
    ) -> str:
        """Build the AI prompt for email personalization"""
        email_type_instructions = {
            'intro': 'This is the first email. Be friendly, show you did research, and offer clear value.',
            'follow_up_1': 'This is the first follow-up (3 days after intro). Reference the initial email briefly and add a new angle or benefit.',
            'follow_up_2': 'This is the second follow-up (6 days after intro). Share a case study or specific result relevant to their industry.',
            'follow_up_3': 'This is the final follow-up (10 days after intro). Use the "break-up" email technique - be friendly but indicate this is your last outreach.'
        }

        instruction = email_type_instructions.get(email_type, email_type_instructions['intro'])

        return f"""You are writing a highly personalized B2B cold outreach email. Use the information below to craft a compelling, personalized email.

LEAD CONTEXT:
{context}

YOUR VALUE PROPOSITION:
{value_prop}

EMAIL TYPE:
{instruction}

REQUIREMENTS:
1. Start with a HIGHLY personalized opening line that shows genuine research (not generic like "I came across your website")
2. Reference something specific from their website, industry, or role
3. Keep it concise (under 150 words)
4. Focus on THEIR problems/goals, not your product features
5. Include ONE clear, low-friction call-to-action
6. Maintain professional but conversational tone
7. NO buzzwords, NO hype, NO salesy language

OUTPUT FORMAT (use exact headers):
SUBJECT: [compelling subject line]

INTRO: [personalized opening line, 1-2 sentences]

BODY: [main message, 2-3 sentences]

CTA: [clear call-to-action, 1 sentence]

PERSONALIZATION_ELEMENTS: [comma-separated list of what you personalized: e.g., "website content, job title, industry challenge"]

Generate the email now:"""

    def _parse_ai_response(self, content: str) -> Dict:
        """Parse AI-generated email content"""
        lines = content.strip().split('\n')

        subject = ""
        intro = ""
        body = ""
        cta = ""
        elements = []

        current_section = None

        for line in lines:
            line = line.strip()

            if line.startswith('SUBJECT:'):
                current_section = 'subject'
                subject = line.replace('SUBJECT:', '').strip()
            elif line.startswith('INTRO:'):
                current_section = 'intro'
                intro = line.replace('INTRO:', '').strip()
            elif line.startswith('BODY:'):
                current_section = 'body'
                body = line.replace('BODY:', '').strip()
            elif line.startswith('CTA:'):
                current_section = 'cta'
                cta = line.replace('CTA:', '').strip()
            elif line.startswith('PERSONALIZATION_ELEMENTS:'):
                elements_str = line.replace('PERSONALIZATION_ELEMENTS:', '').strip()
                elements = [e.strip() for e in elements_str.split(',')]
            elif line and current_section:
                # Continue building current section
                if current_section == 'subject':
                    subject += ' ' + line
                elif current_section == 'intro':
                    intro += ' ' + line
                elif current_section == 'body':
                    body += ' ' + line
                elif current_section == 'cta':
                    cta += ' ' + line

        # Calculate personalization score
        score = min(100, len(elements) * 20 + (50 if intro else 0))

        # Build full email body
        full_body = f"{intro}\n\n{body}\n\n{cta}"

        return {
            'subject': subject.strip(),
            'intro_line': intro.strip(),
            'body': full_body.strip(),
            'cta': cta.strip(),
            'personalization_score': score,
            'personalization_elements': elements
        }

    def _fallback_personalization(
        self,
        lead_data: Dict,
        value_prop: str,
        email_type: str
    ) -> Dict:
        """Fallback to template-based personalization when AI unavailable"""
        company_name = lead_data.get('company_name', 'your company')
        name = lead_data.get('decision_maker_name', 'there')
        title = lead_data.get('decision_maker_title', '')

        if email_type == 'intro':
            subject = f"Quick question about {company_name}'s growth"
            intro = f"Hi {name},"
            title_part = f" and saw you're the {title}" if title else ""
            body = f"I noticed {company_name}{title_part}.\n\n{value_prop}\n\nWould you be open to a quick 15-minute call this week?"
            cta = "Let me know if Thursday or Friday works better for you."
        else:
            subject = f"Following up - {company_name}"
            intro = f"Hi {name},"
            body = f"Following up on my previous email about {value_prop.split('.')[0]}.\n\nStill interested in learning how we can help {company_name}?"
            cta = "Happy to send over some case studies if that would be helpful."

        return {
            'subject': subject,
            'intro_line': intro,
            'body': f"{intro}\n\n{body}\n\n{cta}",
            'cta': cta,
            'personalization_score': 30,  # Low score for templates
            'personalization_elements': ['name', 'company']
        }
