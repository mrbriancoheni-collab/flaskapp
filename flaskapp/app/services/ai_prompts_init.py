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

    # Google Local Services Ads Optimization Prompt
    glsa_prompt = AIPrompt.query.filter_by(prompt_key='glsa_main').first()
    if not glsa_prompt or force:
        if not glsa_prompt:
            glsa_prompt = AIPrompt(prompt_key='glsa_main')
            db.session.add(glsa_prompt)

        glsa_prompt.name = 'Local Services Ads Optimization'
        glsa_prompt.description = 'Main prompt for generating Google Local Services Ads optimization recommendations'
        glsa_prompt.system_message = 'You are a Google Local Services Ads optimization expert providing data-driven recommendations in JSON format.'
        glsa_prompt.prompt_template = '''You are a Google Local Services Ads (GLSA) optimization expert. Analyze the following LSA profile data and provide actionable recommendations to improve lead generation and conversion.

PROFILE OVERVIEW:
- Primary Category: {primary_category}
- Additional Categories: {categories} ({categories_count} total)
- Service Areas: {service_areas} ({service_areas_count} total)
- Rating: {rating} stars
- Reviews Count: {reviews_count}
- Weekly Budget: {weekly_budget}
- Business Hours: {hours}
- Website: {website}
- Phone: {phone}

BUSINESS CONTEXT:
- Service Priorities: {priorities}
- Priority Service Areas: {priority_areas}
- Response Time: {response_time}
- After Hours Availability: {after_hours}
- Monthly Lead Goal: {lead_goal}

Provide 5-10 specific, actionable recommendations in JSON format. Each recommendation should include:
- title: Brief, action-oriented title
- description: Detailed explanation (2-3 sentences)
- category: One of [categories, service_areas, reviews, budget, profile, responsiveness]
- severity: 1=critical issue, 2=high-impact opportunity, 3=quick win, 4-5=long-term optimization
- expected_impact: Specific metric improvement (e.g., "Increase qualified leads by 15-20%")
- data_points: Array of key metrics supporting this recommendation
- action: Dict with type and implementation details

Focus on:
1. Category optimization (primary + additional categories aligned with high-value services)
2. Service area expansion/refinement (target high-converting neighborhoods)
3. Review generation and reputation management (target 4.7+ rating, 50+ reviews)
4. Budget allocation and pacing (align with lead goals, use dayparting)
5. Profile completeness (hours, website, contact info)
6. Responsiveness optimization (sub-15 minute response times)

Return ONLY valid JSON array of recommendations, no additional text.'''
        glsa_prompt.model = 'gpt-4o-mini'
        glsa_prompt.temperature = 0.7
        glsa_prompt.max_tokens = 2000
        glsa_prompt.is_active = True
        count += 1

    # Google My Business Optimization Prompt
    gmb_prompt = AIPrompt.query.filter_by(prompt_key='gmb_main').first()
    if not gmb_prompt or force:
        if not gmb_prompt:
            gmb_prompt = AIPrompt(prompt_key='gmb_main')
            db.session.add(gmb_prompt)

        gmb_prompt.name = 'Google My Business Optimization'
        gmb_prompt.description = 'Main prompt for generating Google My Business (Google Business Profile) optimization recommendations'
        gmb_prompt.system_message = 'You are a Google My Business optimization expert providing data-driven recommendations in JSON format.'
        gmb_prompt.prompt_template = '''You are a Google My Business (Google Business Profile) optimization expert. Analyze the following business profile data and provide actionable recommendations to improve visibility, engagement, and conversions.

PROFILE OVERVIEW:
- Business Name: {business_name}
- Primary Category: {primary_category}
- Additional Categories: {categories} ({categories_count} total)
- Description: {description} ({description_length} characters)
- Address: {address}
- Phone: {phone}
- Website: {website}
- Hours: {hours}

ENGAGEMENT METRICS:
- Photos: {photos_count}
- Reviews: {reviews_count}
- Rating: {rating} stars
- Posts: {posts_count}
- Last Post: {last_post_date}

ATTRIBUTES:
- Configured Attributes: {attributes} ({attributes_count} total)

Provide 5-10 specific, actionable recommendations in JSON format. Each recommendation should include:
- title: Brief, action-oriented title
- description: Detailed explanation (2-3 sentences)
- category: One of [profile_info, categories, description, photos, posts, reviews, attributes]
- severity: 1=critical issue, 2=high-impact opportunity, 3=quick win, 4-5=long-term optimization
- expected_impact: Specific metric improvement (e.g., "Increase profile views by 15-20%")
- data_points: Array of key metrics supporting this recommendation
- action: Dict with type and implementation details

Focus on:
1. Profile completeness (NAP consistency, hours, description optimization)
2. Category optimization (primary + relevant secondary categories)
3. Description optimization (keyword-rich, 750 char limit, local SEO)
4. Photo strategy (cover, logo, interior, exterior, products/services, team)
5. Review generation and response strategy (target 4.5+ rating, 50+ reviews)
6. Google Posts frequency (weekly posts for offers, updates, events)
7. Attributes selection (service options, accessibility, amenities)

Return ONLY valid JSON array of recommendations, no additional text.'''
        gmb_prompt.model = 'gpt-4o-mini'
        gmb_prompt.temperature = 0.7
        gmb_prompt.max_tokens = 2000
        gmb_prompt.is_active = True
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
