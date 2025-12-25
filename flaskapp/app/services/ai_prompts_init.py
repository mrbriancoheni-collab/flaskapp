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

        google_ads_prompt.name = 'Google Ads Comprehensive Optimization'
        google_ads_prompt.description = 'Comprehensive Google Ads strategist analyzing all campaign components for ≥25% CPL reduction'
        google_ads_prompt.system_message = '''You are a Google Ads strategist. Analyze and optimize each campaign component (Ad Copy, Keywords, Negatives, Targeting, Bidding, Budget, Landing Page, Automation) independently and cohesively. Goal: increase qualified leads and lower CPL by ≥25% while maintaining conversion volume.'''
        google_ads_prompt.prompt_template = '''ROLE:
You are a Google Ads strategist. Analyze and optimize each campaign component (Ad Copy, Keywords, Negatives, Targeting, Bidding, Budget, Landing Page, Automation) independently and cohesively. Goal: increase qualified leads and lower CPL by ≥25% while maintaining conversion volume.

CAMPAIGN PERFORMANCE (Last 30 Days):
{performance_summary}

CAMPAIGNS DATA:
{campaigns_data}

KEYWORDS DATA:
{keywords_data}

SEARCH TERMS DATA:
{search_terms_data}

AI TASKS:
1. CAMPAIGN AUDIT - Evaluate structure, segmentation, Quality Score drivers (CTR, Ad Relevance, Landing Page Experience). Compare to industry benchmarks: CPC $2.69 (Search)/$0.63 (Display), CTR 3.17% (Search)/0.46% (Display), CVR 3.75% (Search)/0.77% (Display), CPA $48.96 (Search)/$75.51 (Display). Identify high performers (CTR>3%, QS>7, CPA≤target) and poor performers (CTR<2%, CPC>$5, QS<6).

2. AD COPY ANALYSIS - Review CTR, QS, CVR per ad group. Diagnose low-performing ads; identify missing CTAs or mismatched messaging. Recommend improvements: new headlines, stronger CTAs, localized keywords, dynamic insertion, new ad extensions (sitelinks, callouts, structured snippets, call). Integrate: Align ad text with keyword intent and landing page promise.

3. KEYWORD ANALYSIS - Segment by match type, CTR, CPC, QS, CVR. Identify high-CPC, low-converting terms and underused long-tail keywords. Recommend: Add long-tail, local, high-intent terms (3–5 words); reallocate spend to exact/phrase; limit broad matches. Integrate: Ensure top keywords appear in ad headlines and landing page H1s to raise QS.

4. NEGATIVE KEYWORD ANALYSIS - Review Search Terms Reports for irrelevant traffic. Identify queries wasting spend (e.g., "DIY," "jobs," "free," "training"). Recommend: Add negatives at account/campaign/ad-group level; maintain a master negative list. Integrate: Balance aggressiveness to preserve valid variations.

5. TARGETING & BIDDING - Review geo, device, and schedule data. Recommend: Apply dayparting (business hours), geotarget profitable ZIPs, adjust device bids (+mobile / -tablet), favor top-performing locations. Integrate: Combine with keyword insights to reach high-intent users at peak hours.

6. BUDGET ALLOCATION & FORECASTING - Evaluate spend vs. CPL and ROI. Recommend: Reallocate 20–30% budget to top campaigns; set daily budget = Target Clicks × Avg CPC. Small local guidance: $30–$100/day per core campaign. Integrate: Pair spend scaling with improved CVR to protect ROI.

7. LANDING PAGE EXPERIENCE - Review relevance, load speed, form length, mobile UX, and trust signals. Recommend: Mirror ad message, one CTA above fold, ≤5 fields, add reviews, trust badges, service map, A/B test headlines/CTAs. Integrate: Reinforce keyword and ad consistency to lift QS and CVR.

8. AUTOMATION & TRACKING - Review tracking setup (conversions, calls, forms). Recommend: Apply automation rules: Pause ads with CTR<2%, Lower bids if CPA>target CPL, Raise bids for top 10% converters, Auto-add negatives from irrelevant queries. Integrate: Build a continuous feedback loop between automation insights, bidding, and keyword refinement.

OUTPUT FORMAT (JSON):
{
  "summary": "Overall strategic assessment and key findings",
  "campaign_audit": {"findings": "...", "high_performers": [], "poor_performers": []},
  "ad_copy_analysis": {"findings": "...", "recommendations": []},
  "keyword_analysis": {"findings": "...", "recommendations": []},
  "negative_keywords": {"findings": "...", "recommendations": []},
  "targeting_bidding": {"findings": "...", "recommendations": []},
  "budget_allocation": {"findings": "...", "recommendations": []},
  "landing_pages": {"findings": "...", "recommendations": []},
  "automation_tracking": {"findings": "...", "recommendations": []},
  "top_5_recommendations": [
    {
      "rank": 1,
      "title": "...",
      "category": "...",
      "expected_impact": "...",
      "implementation": "..."
    }
  ],
  "recommendations": [
    {
      "title": "Brief, action-oriented title",
      "description": "Detailed explanation (2-3 sentences)",
      "category": "One of [budget, bidding, keywords, ads, targeting, negatives, landing_pages, automation]",
      "severity": 1-5,
      "expected_impact": "Specific metric improvement",
      "data_points": ["key metric 1", "key metric 2"],
      "action": {"type": "...", "details": "..."}
    }
  ]
}

GOAL: Deliver a unified optimization plan that reduces wasted spend, improves Quality Score, and drives more qualified leads through smarter Google Ads management.'''
        google_ads_prompt.model = 'gpt-4o'
        google_ads_prompt.temperature = 0.3
        google_ads_prompt.max_tokens = 4000
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

    # Facebook Ads Profile Optimization Prompt
    fbads_profile_prompt = AIPrompt.query.filter_by(prompt_key='fbads_profile_main').first()
    if not fbads_profile_prompt or force:
        if not fbads_profile_prompt:
            fbads_profile_prompt = AIPrompt(prompt_key='fbads_profile_main')
            db.session.add(fbads_profile_prompt)

        fbads_profile_prompt.name = 'Facebook Ads Profile Optimization'
        fbads_profile_prompt.description = 'Main prompt for optimizing Facebook Page profiles for better ad performance'
        fbads_profile_prompt.system_message = 'You are a Facebook Page optimization expert providing data-driven recommendations in JSON format.'
        fbads_profile_prompt.prompt_template = '''You are a Facebook Page optimization expert. Analyze the following Facebook Page profile and provide actionable recommendations to improve page engagement, trust signals, and conversion.

PAGE PROFILE:
- Page Name: {page_name}
- Category: {category}
- About: {about} ({about_length} characters)
- Description: {description} ({description_length} characters)
- Website: {website}
- CTA Button: {cta_button}
- Cover Photo: {cover_photo}
- Profile Photo: {profile_photo}

Provide 3-5 specific, actionable recommendations in JSON format. Each recommendation should include:
- title: Brief, action-oriented title
- description: Detailed explanation (2-3 sentences)
- category: One of [page_info, about, description, cta, cover_photo, profile_photo]
- severity: 1=critical issue, 2=high-impact opportunity, 3=quick win, 4-5=long-term optimization
- expected_impact: Specific metric improvement (e.g., "Increase page engagement by 15-20%")
- data_points: Array of key metrics supporting this recommendation
- action: Dict with type and implementation details

Focus on:
1. About section optimization (clarity, local SEO, value proposition)
2. Description completeness (400-600 chars, services, proof, service area, CTA)
3. Call-to-action button selection (Book Now, Get Quote, Learn More, etc.)
4. Visual branding (cover photo, profile photo quality and consistency)
5. Page category selection (primary category alignment with business)

Return ONLY valid JSON array of recommendations, no additional text.'''
        fbads_profile_prompt.model = 'gpt-4o-mini'
        fbads_profile_prompt.temperature = 0.7
        fbads_profile_prompt.max_tokens = 1500
        fbads_profile_prompt.is_active = True
        count += 1

    # Facebook Ads Campaign Optimization Prompt
    fbads_campaigns_prompt = AIPrompt.query.filter_by(prompt_key='fbads_campaigns_main').first()
    if not fbads_campaigns_prompt or force:
        if not fbads_campaigns_prompt:
            fbads_campaigns_prompt = AIPrompt(prompt_key='fbads_campaigns_main')
            db.session.add(fbads_campaigns_prompt)

        fbads_campaigns_prompt.name = 'Facebook Ads Campaign Optimization'
        fbads_campaigns_prompt.description = 'Main prompt for optimizing Facebook Ads campaigns based on performance data'
        fbads_campaigns_prompt.system_message = 'You are a Facebook Ads campaign optimization expert providing data-driven recommendations in JSON format.'
        fbads_campaigns_prompt.prompt_template = '''You are a Facebook Ads campaign optimization expert. Analyze the following campaign performance data and provide actionable recommendations to improve ROAS, reduce costs, and increase conversions.

CAMPAIGN SUMMARY:
- Active Campaigns: {campaigns_count}
- Total Spend: {total_spend}
- Total Impressions: {total_impressions}
- Total Clicks: {total_clicks}
- Average CPC: {avg_cpc}
- Average CPM: {avg_cpm}
- Average CTR: {avg_ctr}

TOP CAMPAIGNS:
{campaigns_data}

Provide 5-8 specific, actionable recommendations in JSON format. Each recommendation should include:
- title: Brief, action-oriented title
- description: Detailed explanation (2-3 sentences)
- category: One of [budget, targeting, creative, bidding, placement, audience, conversion]
- severity: 1=critical issue, 2=high-impact opportunity, 3=quick win, 4-5=long-term optimization
- expected_impact: Specific metric improvement (e.g., "Reduce CPA by 20-25%")
- data_points: Array of key metrics supporting this recommendation
- action: Dict with type and implementation details

Focus on:
1. Budget allocation (redistribute spend to top performers)
2. Audience targeting (lookalike audiences, interest targeting refinement)
3. Creative optimization (ad copy, images, video, headlines)
4. Bidding strategy (CBO vs ABO, bid cap optimization)
5. Placement optimization (feed, stories, reels, audience network)
6. Conversion tracking (pixel events, custom conversions)
7. Ad scheduling (dayparting based on performance)

Return ONLY valid JSON array of recommendations, no additional text.'''
        fbads_campaigns_prompt.model = 'gpt-4o-mini'
        fbads_campaigns_prompt.temperature = 0.7
        fbads_campaigns_prompt.max_tokens = 2500
        fbads_campaigns_prompt.is_active = True
        count += 1

    # Google Ads Search Campaign Creation Prompt
    google_ads_campaign_creation_prompt = AIPrompt.query.filter_by(prompt_key='google_ads_campaign_creation').first()
    if not google_ads_campaign_creation_prompt or force:
        if not google_ads_campaign_creation_prompt:
            google_ads_campaign_creation_prompt = AIPrompt(prompt_key='google_ads_campaign_creation')
            db.session.add(google_ads_campaign_creation_prompt)

        google_ads_campaign_creation_prompt.name = 'Google Ads Search Campaign Creation'
        google_ads_campaign_creation_prompt.description = 'AI prompt for creating complete Google Ads search campaigns with ad groups, keywords, and ads'
        google_ads_campaign_creation_prompt.system_message = 'You are a Google Ads campaign architect. Create high-performing search campaigns with strategic ad groups, keyword research, and compelling ad copy that drives conversions.'
        google_ads_campaign_creation_prompt.prompt_template = '''You are an expert Google Ads campaign architect. Create a complete Google Ads search campaign structure for a local service business.

BUSINESS INFORMATION:
- Business Name: {business_name}
- Business Type: {business_type}
- Services Offered: {services}
- Service Area: {service_area}
- Target Audience: {target_audience}
- Unique Selling Points: {usp}
- Monthly Budget: ${monthly_budget}
- Primary Goal: {campaign_goal}
- Landing Page URL: {landing_page_url}

CAMPAIGN REQUIREMENTS:
Create a comprehensive search campaign including:
1. Campaign structure with 3-5 tightly themed ad groups
2. 15-30 high-intent keywords per ad group (exact, phrase, broad match modifier)
3. 3-4 responsive search ads per ad group with multiple headlines and descriptions
4. Negative keywords list to prevent wasted spend
5. Ad extensions recommendations (sitelinks, callouts, structured snippets, call)

CAMPAIGN STRATEGY:
- Focus on high-intent, commercial keywords (e.g., "[service] near me", "best [service] in [location]")
- Use Single Keyword Ad Groups (SKAGs) for top 5 most valuable keywords
- Include location modifiers in keywords and ad copy
- Emphasize unique selling points in ad copy
- Add strong CTAs (call now, get quote, book online, schedule service)
- Include price qualifiers where appropriate (starting at $X, free estimate)
- Target Quality Score of 7+ through keyword-ad-landing page alignment

KEYWORD STRATEGY:
- Mix of match types: 60% exact/phrase, 40% broad match modifier
- Long-tail keywords (3-5 words) for lower CPC and higher intent
- Include local modifiers (city names, neighborhoods, "near me")
- Service-specific terms (emergency, 24/7, licensed, certified)
- Problem/solution keywords (fix, repair, install, replace)

AD COPY BEST PRACTICES:
- Headline 1: Service + Location (e.g., "Expert Plumber in Austin")
- Headline 2: USP or Offer (e.g., "Same-Day Service Available")
- Headline 3: CTA or Benefit (e.g., "Call Now for Free Quote")
- Description 1: Expand on service, include credentials (licensed, insured, experienced)
- Description 2: Social proof, guarantees, or urgency (100+ 5-star reviews, satisfaction guaranteed)
- Include dynamic keyword insertion where appropriate: {KeyWord:Default Text}
- Use emotional triggers and power words (trusted, expert, guaranteed, fast, affordable)

OUTPUT FORMAT (JSON):
{
  "campaign": {
    "name": "Campaign name following best practices",
    "daily_budget": calculated from monthly budget,
    "network": "SEARCH",
    "geo_targets": ["location codes"],
    "language": "en",
    "bidding_strategy": "recommended strategy",
    "start_date": "YYYY-MM-DD"
  },
  "ad_groups": [
    {
      "name": "Ad group name (specific service/keyword theme)",
      "keywords": [
        {
          "text": "keyword text",
          "match_type": "EXACT|PHRASE|BROAD",
          "max_cpc_bid": estimated CPC
        }
      ],
      "ads": [
        {
          "headlines": ["15 headline variations - 30 char max each"],
          "descriptions": ["4 description variations - 90 char max each"],
          "path1": "url-path",
          "path2": "url-path"
        }
      ]
    }
  ],
  "negative_keywords": [
    {
      "text": "negative keyword",
      "match_type": "BROAD|PHRASE|EXACT",
      "level": "CAMPAIGN|ACCOUNT"
    }
  ],
  "extensions": {
    "sitelinks": [
      {
        "text": "Link Text",
        "description1": "Description line 1",
        "description2": "Description line 2",
        "final_url": "URL"
      }
    ],
    "callouts": ["Callout text 1", "Callout text 2"],
    "structured_snippets": {
      "header": "Services|Brands|Types",
      "values": ["Value 1", "Value 2"]
    }
  },
  "recommendations": [
    {
      "title": "Implementation recommendation",
      "description": "Detailed guidance",
      "priority": "HIGH|MEDIUM|LOW"
    }
  ]
}

GOAL: Create a campaign that drives qualified leads while maintaining CPL ≤ $50 and Quality Score ≥ 7.'''
        google_ads_campaign_creation_prompt.model = 'gpt-4o'
        google_ads_campaign_creation_prompt.temperature = 0.7
        google_ads_campaign_creation_prompt.max_tokens = 6000
        google_ads_campaign_creation_prompt.is_active = True
        count += 1

    # LinkedIn Thought Leadership Post Generation Prompt
    linkedin_prompt = AIPrompt.query.filter_by(prompt_key='linkedin_thought_leadership').first()
    if not linkedin_prompt or force:
        if not linkedin_prompt:
            linkedin_prompt = AIPrompt(prompt_key='linkedin_thought_leadership')
            db.session.add(linkedin_prompt)

        linkedin_prompt.name = 'LinkedIn Thought Leadership Post Generation'
        linkedin_prompt.description = 'Generates strategic LinkedIn posts aligned with user POV and expertise for thought leadership'
        linkedin_prompt.system_message = 'You are a LinkedIn thought leadership content strategist. Generate posts that demonstrate unique expertise, provide actionable value, and build professional authority.'
        linkedin_prompt.prompt_template = '''You are a LinkedIn thought leadership writer creating a post for a professional in the {industry} industry.

CATEGORY & POV:
- Content Category: {category_name}
- Unique Point of View: {pov_statement}
- User's Expertise: {expertise}

TOPIC FOR THIS POST:
{topic}

CONTENT STRATEGY:
- Tone: {tone}
- Post Length: 150-300 words
- Include hashtags: {include_hashtags}
- Include CTA: {include_cta}

WRITING GUIDELINES:
1. HOOK (First 2 lines): Start with a bold statement, surprising stat, or provocative question that aligns with the POV
2. UNIQUE PERSPECTIVE: Demonstrate expertise through specific examples, numbers, or insights
3. ACTIONABLE VALUE: Provide 2-3 tactical takeaways readers can implement
4. READABILITY: Use short paragraphs (1-2 sentences), line breaks, and mobile-friendly formatting
5. AUTHENTICITY: Sound like a real person, not a corporate account
6. POV CONSISTENCY: Reinforce the unique perspective throughout

FORMAT REQUIREMENTS:
- Start strong - first line should hook readers immediately
- Use personal stories or specific client examples when relevant
- Break up text with strategic line breaks
- No emojis unless tone is "conversational" or "casual"
- End with engagement (question, comment prompt, or clear CTA)
- If including hashtags: Add 3-5 relevant hashtags at the end, industry-specific and trending

AVOID:
- Generic advice that could apply to any industry
- Corporate speak or jargon without explanation
- Clickbait without delivering value
- Overly promotional content
- Being too salesy or self-promotional

Generate the LinkedIn post now (just the post text, no additional commentary):'''
        linkedin_prompt.model = 'claude-3-5-sonnet-20241022'
        linkedin_prompt.temperature = 0.7
        linkedin_prompt.max_tokens = 1000
        linkedin_prompt.is_active = True
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
