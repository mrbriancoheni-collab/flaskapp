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
        style: str = 'vivid',
        size: str = '1024x1024',
        variations: int = 1
    ) -> Dict:
        """
        Generate ad image using DALL-E 3 with support for multiple variations

        Args:
            prompt: Image generation prompt
            style: Image style ('natural', 'vivid') - vivid is better for ads
            size: Image size ('1024x1024', '1024x1792', '1792x1024')
            variations: Number of variations to generate (1-3 recommended)

        Returns:
            Dict with image_url(s), revised_prompt
        """
        if not self.openai_api_key:
            return {
                'success': False,
                'error': 'OpenAI API key not configured'
            }

        try:
            # DALL-E 3 only supports n=1, so we need multiple API calls for variations
            results = []

            for i in range(min(variations, 3)):  # Max 3 variations to control costs
                # Add variation seed to prompt for diversity
                variation_prompt = prompt
                if variations > 1:
                    variation_suffixes = [
                        "",  # Original
                        " Variation with different angle and lighting setup.",
                        " Alternative composition with different focal point and depth."
                    ]
                    variation_prompt = prompt + variation_suffixes[i]

                response = openai.images.generate(
                    model="dall-e-3",
                    prompt=variation_prompt,
                    size=size,
                    quality="hd",
                    style=style,
                    n=1
                )

                results.append({
                    'image_url': response.data[0].url,
                    'revised_prompt': response.data[0].revised_prompt
                })

            return {
                'success': True,
                'images': results if variations > 1 else None,
                'image_url': results[0]['image_url'],  # Primary image
                'revised_prompt': results[0]['revised_prompt'],
                'all_variations': results,
                'model': 'dall-e-3',
                'size': size,
                'style': style
            }

        except Exception as e:
            logger.error(f"Error generating image: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def get_size_specs(self, size_name: str) -> Tuple[str, str]:
        """
        Get DALL-E size string and description from friendly name

        Args:
            size_name: Friendly size name ('square', 'story', 'banner', 'portrait', 'landscape')

        Returns:
            Tuple of (dalle_size_string, description)
        """
        size_map = {
            'square': ('1024x1024', 'Square (1:1) - Facebook/Instagram Feed'),
            'story': ('1024x1792', 'Story (9:16) - Instagram Stories/Reels'),
            'banner': ('1792x1024', 'Banner (16:9) - Facebook Cover/LinkedIn'),
            'portrait': ('1024x1792', 'Portrait (9:16) - Vertical ads'),
            'landscape': ('1792x1024', 'Landscape (16:9) - Horizontal ads')
        }

        return size_map.get(size_name, ('1024x1024', 'Square (1:1) - Default'))

    def generate_multi_size_images(
        self,
        prompt: str,
        sizes: List[str] = None,
        style: str = 'vivid'
    ) -> Dict:
        """
        Generate images in multiple sizes for different platforms

        Args:
            prompt: Image generation prompt
            sizes: List of size names (['square', 'story', 'banner'])
            style: Image style

        Returns:
            Dict with images for each size
        """
        if sizes is None:
            sizes = ['square']  # Default to square only

        results = {}

        for size_name in sizes:
            dalle_size, description = self.get_size_specs(size_name)

            result = self.generate_image(
                prompt=prompt,
                style=style,
                size=dalle_size,
                variations=1
            )

            if result.get('success'):
                results[size_name] = {
                    'image_url': result['image_url'],
                    'size': dalle_size,
                    'description': description,
                    'revised_prompt': result.get('revised_prompt')
                }
            else:
                results[size_name] = {
                    'error': result.get('error'),
                    'success': False
                }

        return {
            'success': len([r for r in results.values() if r.get('image_url')]) > 0,
            'images': results
        }

    def generate_image_prompt(
        self,
        business_context: Dict,
        copy: Dict,
        platform: str = 'facebook',
        style_preference: str = 'professional'
    ) -> str:
        """
        Generate an optimized DALL-E prompt for the ad image with enhanced quality

        Args:
            business_context: Business info
            copy: Generated copy
            platform: Target platform
            style_preference: Desired style

        Returns:
            Enhanced DALL-E prompt optimized for ad quality
        """
        business_name = business_context.get('business_name', 'a local service business')
        industry = business_context.get('industry', 'service')

        # Enhanced style definitions with professional photography terminology
        style_configs = {
            'professional': {
                'base': 'Professional commercial photography',
                'lighting': 'bright natural lighting, well-balanced exposure',
                'composition': 'rule of thirds composition, shallow depth of field',
                'quality': 'shot with 50mm f/1.8 lens, photorealistic, 4K quality',
                'aesthetic': 'clean, polished, corporate-ready'
            },
            'lifestyle': {
                'base': 'Authentic lifestyle photography',
                'lighting': 'soft natural window light, golden hour warmth',
                'composition': 'candid moment, environmental portrait',
                'quality': 'shot with 35mm f/2.0 lens, film-like aesthetic, high resolution',
                'aesthetic': 'warm, inviting, relatable, human-centered'
            },
            'modern': {
                'base': 'Contemporary minimalist photography',
                'lighting': 'clean studio lighting, high-key exposure',
                'composition': 'geometric balance, negative space, centered subject',
                'quality': 'shot with 85mm f/1.4 lens, ultra-sharp, crisp detail',
                'aesthetic': 'sleek, minimal, modern design, white/neutral tones'
            },
            'dramatic': {
                'base': 'Cinematic dramatic photography',
                'lighting': 'dramatic side lighting, rim light, high contrast',
                'composition': 'dynamic angle, bold perspective, strong leading lines',
                'quality': 'shot with 24mm f/1.4 lens, cinema-grade, HDR',
                'aesthetic': 'bold, impactful, magazine-quality, editorial style'
            },
            'cinematic': {
                'base': 'Cinematic commercial production',
                'lighting': 'three-point lighting setup, volumetric atmosphere',
                'composition': 'wide-angle establishing shot, Hollywood aesthetic',
                'quality': 'anamorphic lens, bokeh, film grain, 6K resolution',
                'aesthetic': 'epic, premium, luxury brand feel'
            }
        }

        style_config = style_configs.get(style_preference, style_configs['professional'])

        # Enhanced industry-specific scenarios with detail
        industry_scenarios = {
            'plumbing': {
                'subject': 'skilled plumber in crisp uniform',
                'action': 'installing premium chrome faucet in upscale residential bathroom',
                'environment': 'modern marble bathroom, organized tools on clean drop cloth',
                'details': 'professional tool kit, copper pipes, stainless fixtures'
            },
            'hvac': {
                'subject': 'HVAC technician in branded uniform',
                'action': 'servicing modern air conditioning system',
                'environment': 'residential home exterior or clean mechanical room',
                'details': 'diagnostic tools, modern HVAC unit, temperature gauges'
            },
            'electrical': {
                'subject': 'licensed electrician in safety gear',
                'action': 'working on modern electrical panel or smart home installation',
                'environment': 'contemporary home interior, organized workspace',
                'details': 'voltage meters, circuit breakers, LED fixtures, wire management'
            },
            'roofing': {
                'subject': 'professional roofer with safety equipment',
                'action': 'installing high-quality roofing materials',
                'environment': 'residential rooftop, blue sky background',
                'details': 'premium shingles, professional tools, safety harness'
            },
            'landscaping': {
                'subject': 'professional landscaper in work attire',
                'action': 'creating beautiful outdoor space',
                'environment': 'upscale residential yard, manicured lawn',
                'details': 'modern landscaping equipment, vibrant plants, pristine results'
            },
            'cleaning': {
                'subject': 'professional cleaner in uniform',
                'action': 'cleaning modern kitchen or living space',
                'environment': 'sparkling clean upscale home interior',
                'details': 'eco-friendly products, organized supplies, spotless surfaces'
            },
            'painting': {
                'subject': 'professional painter in clean whites',
                'action': 'applying perfect finish to interior wall',
                'environment': 'contemporary home, protected floors',
                'details': 'premium paint cans, professional rollers, crisp painter\'s tape'
            },
            'garage door': {
                'subject': 'garage door technician in uniform',
                'action': 'installing or servicing modern garage door system',
                'environment': 'upscale residential garage',
                'details': 'sleek garage door, professional tools, clean workspace'
            }
        }

        # Get scenario or create generic
        scenario = industry_scenarios.get(industry, {
            'subject': f'professional {industry} service provider',
            'action': f'performing expert {industry} work',
            'environment': 'clean professional setting',
            'details': 'high-quality tools and equipment'
        })

        # Platform-specific optimizations
        platform_specs = {
            'facebook': 'social media advertising, engaging and scroll-stopping',
            'instagram': 'Instagram-optimized, bold colors, visually striking, feed-stopping',
            'linkedin': 'professional business aesthetic, corporate credibility, B2B appeal',
            'twitter': 'attention-grabbing, news-worthy quality, shareable'
        }

        platform_style = platform_specs.get(platform, 'social media ready')

        # Build comprehensive enhanced prompt
        enhanced_prompt = f"""{style_config['base']}: {scenario['subject']} {scenario['action']}.
{scenario['environment']}. {scenario['details']}.

Photography specs: {style_config['lighting']}, {style_config['composition']}.
{style_config['quality']}.

Style: {style_config['aesthetic']}, {platform_style}.

Requirements: Commercial-grade quality, brand-safe content, no text overlay, no watermarks,
photorealistic, suitable for professional advertising, high-end production value,
magazine-quality finish. Perfect for {platform} advertising campaign."""

        # Clean up extra whitespace
        enhanced_prompt = ' '.join(enhanced_prompt.split())

        return enhanced_prompt

    def generate_full_creative(
        self,
        website_url: Optional[str] = None,
        business_context: Optional[Dict] = None,
        platform: str = 'facebook',
        objective: str = 'leads',
        industry: Optional[str] = None,
        style_preference: str = 'professional',
        image_variations: int = 1,
        image_size: str = 'square'
    ) -> Dict:
        """
        Generate a complete ad creative (image + copy) with enhanced quality

        Args:
            website_url: Website to scan for context
            business_context: Manual business context (if not using website)
            platform: Target platform
            objective: Ad objective
            industry: Business industry
            style_preference: Image style preference (professional, lifestyle, modern, dramatic, cinematic)
            image_variations: Number of image variations (1-3)
            image_size: Image size ('square', 'story', 'banner')

        Returns:
            Dict with image_url(s), headline, primary_text, description, cta, variations
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

        # Generate enhanced image prompt
        image_prompt = self.generate_image_prompt(
            business_context=context,
            copy=copy_result,
            platform=platform,
            style_preference=style_preference
        )

        # Get size specs
        dalle_size, size_description = self.get_size_specs(image_size)

        # Generate image with variations using 'vivid' style for more impactful ads
        image_result = self.generate_image(
            prompt=image_prompt,
            style='vivid',  # Vivid produces more vibrant, ad-optimized images
            size=dalle_size,
            variations=image_variations
        )

        if not image_result.get('success'):
            # Return copy even if image fails
            return {
                **copy_result,
                'image_generation_failed': True,
                'image_error': image_result.get('error')
            }

        # Combine results
        result = {
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
            'image_size': image_size,
            'size_description': size_description,
            'style_preference': style_preference,
            'business_context': context
        }

        # Add variations if generated
        if image_variations > 1 and image_result.get('all_variations'):
            result['image_variations'] = image_result.get('all_variations')

        return result

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

    def predict_performance(
        self,
        creative: Dict,
        platform: str = 'facebook',
        industry: str = None
    ) -> Dict:
        """
        Predict ad creative performance using AI analysis

        Args:
            creative: Dict with headline, primary_text, description, call_to_action
            platform: Target platform for benchmarks
            industry: Industry for benchmark comparison

        Returns:
            Dict with predicted_ctr, engagement_score, quality_score, recommendations
        """
        try:
            # Industry benchmarks for CTR (%)
            industry_benchmarks = {
                'plumbing': {'ctr': 2.8, 'engagement': 3.5},
                'hvac': {'ctr': 2.5, 'engagement': 3.2},
                'electrical': {'ctr': 2.6, 'engagement': 3.3},
                'roofing': {'ctr': 3.2, 'engagement': 4.0},
                'landscaping': {'ctr': 3.5, 'engagement': 4.2},
                'cleaning': {'ctr': 3.8, 'engagement': 4.5},
                'painting': {'ctr': 2.9, 'engagement': 3.6},
                'garage door': {'ctr': 2.4, 'engagement': 3.0},
                'default': {'ctr': 2.5, 'engagement': 3.0}
            }

            # Platform multipliers
            platform_multipliers = {
                'facebook': 1.0,
                'instagram': 1.15,  # Higher engagement on Instagram
                'linkedin': 0.85,   # Lower CTR but higher quality
                'twitter': 0.95
            }

            benchmark = industry_benchmarks.get(industry, industry_benchmarks['default'])
            platform_mult = platform_multipliers.get(platform, 1.0)

            # Build analysis prompt
            analysis_prompt = f"""Analyze this social media ad creative for {platform} and predict its performance:

HEADLINE: {creative.get('headline', '')}
PRIMARY TEXT: {creative.get('primary_text', '')}
DESCRIPTION: {creative.get('description', '')}
CALL TO ACTION: {creative.get('call_to_action', '')}

Industry: {industry or 'general'}
Platform: {platform}

Provide:
1. Quality Score (0-100): Rate the overall creative quality
2. CTR Adjustment Factor (0.7-1.3): How this compares to average ads (1.0 = average, 1.2 = 20% better)
3. Top 3 Recommendations: Specific improvements to increase performance

Format your response exactly like this:
QUALITY_SCORE: [number 0-100]
CTR_FACTOR: [number 0.7-1.3]
RECOMMENDATION_1: [specific recommendation]
RECOMMENDATION_2: [specific recommendation]
RECOMMENDATION_3: [specific recommendation]"""

            # Use Claude for analysis (faster and cheaper)
            if self.anthropic_client:
                response = self.anthropic_client.messages.create(
                    model="claude-3-5-sonnet-20241022",
                    max_tokens=512,
                    messages=[{
                        "role": "user",
                        "content": analysis_prompt
                    }]
                )
                analysis = response.content[0].text
            elif self.openai_api_key:
                response = openai.chat.completions.create(
                    model="gpt-4o-mini",  # Faster model for analysis
                    messages=[
                        {"role": "system", "content": "You are an expert social media advertising analyst."},
                        {"role": "user", "content": analysis_prompt}
                    ],
                    temperature=0.3  # Lower temperature for more consistent scoring
                )
                analysis = response.choices[0].message.content
            else:
                # Fallback to basic heuristics if no API available
                return self._fallback_performance_prediction(creative, benchmark, platform_mult)

            # Parse AI response
            quality_score = 75  # Default
            ctr_factor = 1.0    # Default
            recommendations = []

            for line in analysis.strip().split('\n'):
                line = line.strip()
                if line.startswith('QUALITY_SCORE:'):
                    try:
                        quality_score = int(line.split(':')[1].strip())
                    except:
                        pass
                elif line.startswith('CTR_FACTOR:'):
                    try:
                        ctr_factor = float(line.split(':')[1].strip())
                    except:
                        pass
                elif line.startswith('RECOMMENDATION_'):
                    rec = line.split(':', 1)[1].strip() if ':' in line else ''
                    if rec:
                        recommendations.append(rec)

            # Calculate predictions
            base_ctr = benchmark['ctr'] * platform_mult
            predicted_ctr = base_ctr * ctr_factor

            # Engagement score based on quality and platform
            base_engagement = benchmark['engagement'] * platform_mult
            engagement_score = min(100, int(base_engagement * (quality_score / 75) * 10))

            return {
                'success': True,
                'predicted_ctr': round(predicted_ctr, 2),
                'predicted_ctr_range': f"{round(predicted_ctr * 0.8, 2)}-{round(predicted_ctr * 1.2, 2)}%",
                'engagement_score': engagement_score,
                'quality_score': quality_score,
                'recommendations': recommendations[:3],
                'benchmark_ctr': round(base_ctr, 2),
                'performance_vs_benchmark': round(((predicted_ctr / base_ctr) - 1) * 100, 1)
            }

        except Exception as e:
            logger.error(f"Error predicting performance: {e}")
            # Return fallback prediction
            return self._fallback_performance_prediction(
                creative,
                industry_benchmarks.get(industry, industry_benchmarks['default']),
                platform_multipliers.get(platform, 1.0)
            )

    def _fallback_performance_prediction(
        self,
        creative: Dict,
        benchmark: Dict,
        platform_mult: float
    ) -> Dict:
        """Fallback performance prediction using heuristics"""

        # Basic quality heuristics
        quality_score = 70

        headline = creative.get('headline', '')
        primary = creative.get('primary_text', '')
        cta = creative.get('call_to_action', '')

        # Adjust quality based on content length and presence
        if len(headline) > 20 and len(headline) < 60:
            quality_score += 5
        if len(primary) > 50 and len(primary) < 150:
            quality_score += 5
        if cta and len(cta) > 3:
            quality_score += 5
        if '?' in headline or '!' in headline:
            quality_score += 3

        # Calculate CTR
        ctr_factor = 0.9 + (quality_score - 70) / 100  # Range: 0.9-1.05
        predicted_ctr = benchmark['ctr'] * platform_mult * ctr_factor

        # Engagement score
        engagement_score = min(100, int(benchmark['engagement'] * platform_mult * (quality_score / 75) * 10))

        return {
            'success': True,
            'predicted_ctr': round(predicted_ctr, 2),
            'predicted_ctr_range': f"{round(predicted_ctr * 0.8, 2)}-{round(predicted_ctr * 1.2, 2)}%",
            'engagement_score': engagement_score,
            'quality_score': quality_score,
            'recommendations': [
                'Consider A/B testing different headlines',
                'Add urgency or scarcity to your messaging',
                'Test different call-to-action phrases'
            ],
            'benchmark_ctr': round(benchmark['ctr'] * platform_mult, 2),
            'performance_vs_benchmark': round(((predicted_ctr / (benchmark['ctr'] * platform_mult)) - 1) * 100, 1)
        }

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
