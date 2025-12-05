# app/services/ad_generation_service.py
"""
AI Ad Generation Service

Generates social media ad creatives using:
- OpenAI DALL-E 3 for image generation
- OpenAI GPT-4 or Anthropic Claude for copywriting
- Website scanning for context
"""
import os
import logging
import requests
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from bs4 import BeautifulSoup
import anthropic
import openai

logger = logging.getLogger(__name__)


class AdGenerationService:
    """Service for generating AI-powered ad creatives"""

    def __init__(self):
        self.openai_api_key = os.getenv('OPENAI_API_KEY')
        self.anthropic_api_key = os.getenv('ANTHROPIC_API_KEY')

        if self.openai_api_key:
            openai.api_key = self.openai_api_key

        if self.anthropic_api_key:
            self.anthropic_client = anthropic.Anthropic(api_key=self.anthropic_api_key)
        else:
            self.anthropic_client = None

    def scan_website(self, url: str) -> Dict:
        """
        Scan a website to extract context for ad generation

        Args:
            url: Website URL to scan

        Returns:
            Dict with extracted info: business_name, services, value_props, etc.
        """
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, 'html.parser')

            # Extract key information
            title = soup.find('title')
            meta_description = soup.find('meta', {'name': 'description'})
            h1_tags = soup.find_all('h1', limit=3)
            h2_tags = soup.find_all('h2', limit=5)

            # Try to find business name
            business_name = None
            if title:
                business_name = title.get_text().split('|')[0].split('-')[0].strip()

            # Extract services/offerings
            services = []
            for h2 in h2_tags:
                text = h2.get_text().strip()
                if len(text) < 100 and ('service' in text.lower() or 'repair' in text.lower()
                                       or 'install' in text.lower() or 'maintenance' in text.lower()):
                    services.append(text)

            return {
                'success': True,
                'business_name': business_name,
                'meta_description': meta_description.get('content') if meta_description else None,
                'main_headlines': [h.get_text().strip() for h in h1_tags],
                'services': services[:5],
                'url': url
            }

        except Exception as e:
            logger.error(f"Error scanning website {url}: {e}")
            return {
                'success': False,
                'error': str(e),
                'url': url
            }

    def generate_ad_copy(
        self,
        business_context: Dict,
        platform: str = 'facebook',
        objective: str = 'leads',
        tone: str = 'professional',
        model: str = 'claude'
    ) -> Dict:
        """
        Generate ad copy using AI

        Args:
            business_context: Context about the business (from website scan or manual input)
            platform: Target platform (facebook, instagram, linkedin, etc.)
            objective: Ad objective (awareness, leads, conversions)
            tone: Tone of copy (professional, casual, urgent, friendly)
            model: AI model to use ('claude' or 'gpt4')

        Returns:
            Dict with headline, primary_text, description, call_to_action
        """
        # Build prompt based on context
        prompt = self._build_copy_prompt(business_context, platform, objective, tone)

        try:
            if model == 'claude' and self.anthropic_client:
                response = self.anthropic_client.messages.create(
                    model="claude-3-5-sonnet-20241022",
                    max_tokens=1024,
                    messages=[{
                        "role": "user",
                        "content": prompt
                    }]
                )
                content = response.content[0].text

            elif self.openai_api_key:
                response = openai.chat.completions.create(
                    model="gpt-4-turbo-preview",
                    messages=[
                        {"role": "system", "content": "You are an expert social media ad copywriter."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.7
                )
                content = response.choices[0].message.content
            else:
                return {
                    'success': False,
                    'error': 'No AI API keys configured'
                }

            # Parse the response into structured format
            parsed = self._parse_copy_response(content, platform)
            parsed['success'] = True
            parsed['model_used'] = model
            return parsed

        except Exception as e:
            logger.error(f"Error generating ad copy: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def generate_image(
        self,
        prompt: str,
        style: str = 'natural',
        size: str = '1024x1024'
    ) -> Dict:
        """
        Generate ad image using DALL-E 3

        Args:
            prompt: Image generation prompt
            style: Image style ('natural', 'vivid')
            size: Image size ('1024x1024', '1024x1792', '1792x1024')

        Returns:
            Dict with image_url, revised_prompt
        """
        if not self.openai_api_key:
            return {
                'success': False,
                'error': 'OpenAI API key not configured'
            }

        try:
            response = openai.images.generate(
                model="dall-e-3",
                prompt=prompt,
                size=size,
                quality="hd",
                style=style,
                n=1
            )

            return {
                'success': True,
                'image_url': response.data[0].url,
                'revised_prompt': response.data[0].revised_prompt,
                'model': 'dall-e-3'
            }

        except Exception as e:
            logger.error(f"Error generating image: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def generate_image_prompt(
        self,
        business_context: Dict,
        copy: Dict,
        platform: str = 'facebook',
        style_preference: str = 'professional'
    ) -> str:
        """
        Generate an optimized DALL-E prompt for the ad image

        Args:
            business_context: Business info
            copy: Generated copy
            platform: Target platform
            style_preference: Desired style

        Returns:
            Optimized DALL-E prompt
        """
        business_name = business_context.get('business_name', 'a local service business')
        industry = business_context.get('industry', 'service')

        # Build context-aware prompt
        base_elements = []

        if style_preference == 'professional':
            base_elements.append("professional, high-quality photograph")
        elif style_preference == 'lifestyle':
            base_elements.append("lifestyle photography, authentic moment")
        elif style_preference == 'modern':
            base_elements.append("modern, clean design, minimalist")
        elif style_preference == 'dramatic':
            base_elements.append("dramatic lighting, bold composition")

        # Industry-specific elements
        industry_elements = {
            'plumbing': 'modern plumbing tools, pipes, professional plumber at work',
            'hvac': 'air conditioning unit, HVAC technician, temperature control',
            'electrical': 'electrical panel, licensed electrician, modern lighting',
            'roofing': 'roof installation, roofing materials, professional roofer',
            'landscaping': 'beautiful landscape, lawn care, professional landscaper',
            'cleaning': 'sparkling clean home, professional cleaners, organized space',
        }

        if industry in industry_elements:
            base_elements.append(industry_elements[industry])
        else:
            base_elements.append(f"{industry} professional service provider at work")

        # Platform-specific considerations
        if platform == 'instagram':
            base_elements.append("Instagram-style, visually striking, bold colors")
        elif platform == 'linkedin':
            base_elements.append("professional business setting, corporate aesthetic")

        # Combine elements
        prompt = f"Create a {', '.join(base_elements)}. The image should be suitable for a {platform} ad about {business_name}. High resolution, no text overlay, professional quality."

        return prompt

    def generate_full_creative(
        self,
        website_url: Optional[str] = None,
        business_context: Optional[Dict] = None,
        platform: str = 'facebook',
        objective: str = 'leads',
        industry: Optional[str] = None,
        style_preference: str = 'professional'
    ) -> Dict:
        """
        Generate a complete ad creative (image + copy)

        Args:
            website_url: Website to scan for context
            business_context: Manual business context (if not using website)
            platform: Target platform
            objective: Ad objective
            industry: Business industry
            style_preference: Image style preference

        Returns:
            Dict with image_url, headline, primary_text, description, cta
        """
        # Get business context
        if website_url:
            context = self.scan_website(website_url)
            if not context.get('success'):
                return context
        elif business_context:
            context = business_context
        else:
            return {
                'success': False,
                'error': 'Either website_url or business_context required'
            }

        # Add industry if provided
        if industry:
            context['industry'] = industry

        # Generate copy first
        copy_result = self.generate_ad_copy(
            business_context=context,
            platform=platform,
            objective=objective,
            model='claude' if self.anthropic_client else 'gpt4'
        )

        if not copy_result.get('success'):
            return copy_result

        # Generate image prompt
        image_prompt = self.generate_image_prompt(
            business_context=context,
            copy=copy_result,
            platform=platform,
            style_preference=style_preference
        )

        # Generate image
        image_result = self.generate_image(prompt=image_prompt)

        if not image_result.get('success'):
            # Return copy even if image fails
            return {
                **copy_result,
                'image_generation_failed': True,
                'image_error': image_result.get('error')
            }

        # Combine results
        return {
            'success': True,
            'headline': copy_result.get('headline'),
            'primary_text': copy_result.get('primary_text'),
            'description': copy_result.get('description'),
            'call_to_action': copy_result.get('call_to_action'),
            'image_url': image_result.get('image_url'),
            'image_prompt': image_prompt,
            'revised_image_prompt': image_result.get('revised_prompt'),
            'copy_model': copy_result.get('model_used'),
            'image_model': 'dall-e-3',
            'business_context': context
        }

    def generate_variations(
        self,
        original_creative: Dict,
        variation_count: int = 3,
        vary_element: str = 'all'
    ) -> List[Dict]:
        """
        Generate A/B test variations of an ad creative

        Args:
            original_creative: Original creative dict
            variation_count: Number of variations to generate
            vary_element: What to vary ('headline', 'copy', 'image', 'all')

        Returns:
            List of variation dicts
        """
        variations = []

        for i in range(variation_count):
            variation = original_creative.copy()

            if vary_element in ['headline', 'all']:
                # Generate alternative headline
                prompt = f"Generate an alternative headline for this ad. Original: {original_creative.get('headline')}. Make it different but equally compelling."
                # Use AI to generate...

            if vary_element in ['copy', 'all']:
                # Generate alternative copy
                pass

            if vary_element in ['image', 'all'] and i < 2:  # Limit image variations (expensive)
                # Generate alternative image
                pass

            variations.append(variation)

        return variations

    def _build_copy_prompt(
        self,
        business_context: Dict,
        platform: str,
        objective: str,
        tone: str
    ) -> str:
        """Build the AI prompt for copy generation"""

        business_name = business_context.get('business_name', '[Business Name]')
        services = business_context.get('services', [])
        meta = business_context.get('meta_description', '')

        prompt = f"""Generate compelling ad copy for a {platform} ad.

Business: {business_name}
Services: {', '.join(services) if services else 'local service business'}
Description: {meta if meta else 'N/A'}

Ad Objective: {objective}
Tone: {tone}
Platform: {platform}

Requirements:
- Headline: Attention-grabbing, {40 if platform == 'facebook' else 30} characters max
- Primary Text: Engaging body copy, {125 if platform == 'facebook' else 100} characters, focus on benefits
- Description: Supporting detail, {30 if platform == 'facebook' else 25} characters
- Call to Action: Clear CTA button text (5-15 characters)

Format your response exactly like this:
HEADLINE: [your headline]
PRIMARY: [your primary text]
DESCRIPTION: [your description]
CTA: [your call to action]
"""

        return prompt

    def _parse_copy_response(self, content: str, platform: str) -> Dict:
        """Parse AI response into structured format"""

        lines = content.strip().split('\n')
        result = {
            'headline': '',
            'primary_text': '',
            'description': '',
            'call_to_action': ''
        }

        for line in lines:
            line = line.strip()
            if line.startswith('HEADLINE:'):
                result['headline'] = line.replace('HEADLINE:', '').strip()
            elif line.startswith('PRIMARY:'):
                result['primary_text'] = line.replace('PRIMARY:', '').strip()
            elif line.startswith('DESCRIPTION:'):
                result['description'] = line.replace('DESCRIPTION:', '').strip()
            elif line.startswith('CTA:'):
                result['call_to_action'] = line.replace('CTA:', '').strip()

        return result
