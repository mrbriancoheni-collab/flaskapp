# app/services/ai_prompts_init.py
"""
Initialize default AI prompts in the database.
This extracts hardcoded prompts from the services and stores them in the AIPrompt table.
"""

from app import db
from app.models_ads import AIPrompt


def initialize_ai_prompts(force=False):
    """
    Initialize or update AI prompts in the database.

    Args:
        force: If True, update existing prompts with defaults. If False, only create missing ones.

    Returns:
        Number of prompts created or updated
    """
    count = 0

    # Google Ads Optimization Prompt
    google_ads_prompt = AIPrompt.query.filter_by(prompt_key='google_ads_main').first()
    if not google_ads_prompt or force:
        if not google_ads_prompt:
            google_ads_prompt = AIPrompt(prompt_key='google_ads_main')
            db.session.add(google_ads_prompt)

        google_ads_prompt.name = 'Google Ads Optimization'
        google_ads_prompt.description = 'Main prompt for generating Google Ads optimization recommendations'
        google_ads_prompt.system_message = 'You are a Google Ads optimization expert providing data-driven recommendations in JSON format.'
        google_ads_prompt.prompt_template = '''You are a Google Ads optimization expert. Analyze the following campaign data and provide actionable recommendations.

CAMPAIGN PERFORMANCE (Last 30 Days):
{performance_summary}

CAMPAIGNS:
{campaigns_data}

AD GROUPS:
{ad_groups_data}

KEYWORDS:
{keywords_data}

SEARCH TERMS:
{search_terms_data}

Provide 5-10 specific, actionable recommendations in JSON format. Each recommendation should include:
- title: Brief, action-oriented title
- description: Detailed explanation (2-3 sentences)
- category: One of [budget, bidding, keywords, ads, targeting, negatives, landing_pages]
- severity: 1=critical issue, 2=high-impact opportunity, 3=quick win, 4-5=long-term optimization
- expected_impact: Specific metric improvement (e.g., "Reduce CPA by 15-20%")
- data_points: Array of key metrics supporting this recommendation
- action: Dict with type and target details

Focus on:
1. Wasted spend (high cost, low conversions)
2. Budget constraints (lost impression share)
3. Negative keywords needed
4. Bidding strategy improvements
5. Low-quality score keywords

Return ONLY valid JSON array of recommendations, no additional text.'''
        google_ads_prompt.model = 'gpt-4o-mini'
        google_ads_prompt.temperature = 0.7
        google_ads_prompt.max_tokens = 2000
        google_ads_prompt.is_active = True
        count += 1

    # Google Analytics Optimization Prompt
    ga_prompt = AIPrompt.query.filter_by(prompt_key='google_analytics_main').first()
    if not ga_prompt or force:
        if not ga_prompt:
            ga_prompt = AIPrompt(prompt_key='google_analytics_main')
            db.session.add(ga_prompt)

        ga_prompt.name = 'Google Analytics Optimization'
        ga_prompt.description = 'Main prompt for generating Google Analytics optimization recommendations'
        ga_prompt.system_message = 'You are a Google Analytics expert providing data-driven optimization recommendations in JSON format.'
        ga_prompt.prompt_template = '''You are a Google Analytics optimization expert. Analyze the following GA4 data and provide actionable recommendations.

PROPERTY PERFORMANCE (Last 30 Days):
- Sessions: {sessions}
- Users: {users}
- Engagement Rate: {engagement_rate}
- Avg Session Duration: {avg_session_duration}s
- Conversions: {conversions}
- Conversion Rate: {conversion_rate}
- Revenue: ${revenue}

TOP PAGES:
{top_pages}

TOP TRAFFIC SOURCES:
{top_sources}

CONVERSION EVENTS:
{conversions_data}

Provide 5-10 specific, actionable recommendations in JSON format. Each recommendation should include:
- title: Brief, action-oriented title
- description: Detailed explanation (2-3 sentences)
- category: One of [content, traffic_sources, conversions, engagement, technical, user_experience]
- severity: 1=critical issue, 2=high-impact opportunity, 3=quick win, 4-5=long-term optimization
- expected_impact: Specific metric improvement (e.g., "Increase conversion rate by 15-20%")
- data_points: Array of key metrics supporting this recommendation
- action: Dict with implementation steps

Focus on:
1. Content optimization for high-traffic pages with low engagement
2. Traffic source opportunities (underperforming channels)
3. Conversion funnel improvements
4. User engagement enhancements
5. Technical performance issues

Return ONLY valid JSON array of recommendations, no additional text.'''
        ga_prompt.model = 'gpt-4o-mini'
        ga_prompt.temperature = 0.7
        ga_prompt.max_tokens = 2000
        ga_prompt.is_active = True
        count += 1

    # Google Search Console SEO Prompt
    gsc_prompt = AIPrompt.query.filter_by(prompt_key='search_console_main').first()
    if not gsc_prompt or force:
        if not gsc_prompt:
            gsc_prompt = AIPrompt(prompt_key='search_console_main')
            db.session.add(gsc_prompt)

        gsc_prompt.name = 'Search Console SEO Optimization'
        gsc_prompt.description = 'Main prompt for generating Google Search Console SEO recommendations'
        gsc_prompt.system_message = 'You are an SEO expert providing data-driven optimization recommendations in JSON format.'
        gsc_prompt.prompt_template = '''You are an SEO expert specializing in Google Search Console optimization. Analyze the following GSC data and provide actionable SEO recommendations.

SITE PERFORMANCE (Last 30 Days):
- Total Clicks: {clicks}
- Total Impressions: {impressions}
- Average CTR: {avg_ctr}
- Average Position: {avg_position}

TOP PERFORMING PAGES:
{top_pages}

TOP QUERIES:
{top_queries}

LOW CTR QUERIES (High impressions, low clicks):
{low_ctr_queries}

Provide 5-10 specific, actionable SEO recommendations in JSON format. Each recommendation should include:
- title: Brief, action-oriented title
- description: Detailed explanation (2-3 sentences)
- category: One of [keywords, content, technical_seo, ctr_optimization, rankings, schema, mobile]
- severity: 1=critical issue, 2=high-impact opportunity, 3=quick win, 4-5=long-term SEO
- expected_impact: Specific metric improvement (e.g., "Increase organic clicks by 15-20%")
- data_points: Array of key metrics supporting this recommendation
- action: Dict with implementation steps

Focus on:
1. High-impression, low-CTR queries (title/meta optimization)
2. Pages ranking 4-10 (content improvement to reach page 1)
3. Declining rankings (content refresh needed)
4. Technical SEO issues
5. Content gap opportunities

Return ONLY valid JSON array of recommendations, no additional text.'''
        gsc_prompt.model = 'gpt-4o-mini'
        gsc_prompt.temperature = 0.7
        gsc_prompt.max_tokens = 2000
        gsc_prompt.is_active = True
        count += 1

    db.session.commit()
    return count


def get_prompt_for_service(prompt_key: str) -> dict:
    """
    Retrieve a prompt configuration for a service.

    Args:
        prompt_key: The prompt key (e.g., 'google_ads_main')

    Returns:
        Dict with prompt_template, system_message, model, temperature, max_tokens
        Returns None if prompt not found or not active
    """
    prompt = AIPrompt.query.filter_by(prompt_key=prompt_key, is_active=True).first()

    if not prompt:
        return None

    return {
        'prompt_template': prompt.prompt_template,
        'system_message': prompt.system_message,
        'model': prompt.model,
        'temperature': prompt.temperature,
        'max_tokens': prompt.max_tokens,
        'name': prompt.name
    }
