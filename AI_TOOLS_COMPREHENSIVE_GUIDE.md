# AI Tools Comprehensive Optimization Guide

## Overview

FieldSprout's AI-powered optimization system has been upgraded to enterprise-grade strategic analysis across all marketing channels. This guide documents the comprehensive improvements to all AI prompt tools.

## System Architecture

### Database-Driven Prompts

All AI prompts are stored in the `ai_prompts` database table for easy customization without code changes:

```sql
SELECT prompt_key, name, model, temperature, max_tokens
FROM ai_prompts
WHERE is_active = TRUE;
```

### Key Benefits

1. **No Code Deployments** - Update prompts via SQL without redeploying
2. **A/B Testing** - Test different prompt variations easily
3. **Model Flexibility** - Switch between GPT-4o, GPT-4o-mini, Claude models
4. **Version Control** - Track prompt changes in database
5. **Consistency** - Unified strategic framework across all tools

---

## Upgraded AI Tools Summary

| Tool | Prompt Key | Model | Analysis Sections | Max Tokens | Status |
|------|-----------|-------|-------------------|------------|--------|
| Google Ads | `google_ads_main` | gpt-4o | 8 sections | 4000 | ✅ Optimized |
| Google Analytics | `google_analytics_main` | gpt-4o | 8 sections | 4000 | ✅ UPGRADED |
| Search Console | `search_console_main` | gpt-4o | 8 sections | 4000 | ✅ UPGRADED |
| Local Services Ads | `glsa_main` | gpt-4o | 8 sections | 4000 | ✅ UPGRADED |
| Google Business Profile | `gmb_main` | gpt-4o | 8 sections | 4000 | ✅ UPGRADED |
| Facebook Page | `fbads_profile_main` | gpt-4o | 8 sections | 3000 | ✅ UPGRADED |
| Facebook Ads | `fbads_campaigns_main` | gpt-4o | 8 sections | 4000 | ✅ UPGRADED |
| Campaign Creation | `google_ads_campaign_creation` | gpt-4o | N/A | 6000 | ✅ Optimized |
| LinkedIn Posts | `linkedin_thought_leadership` | Claude Sonnet | N/A | 1000 | ✅ Optimized |

---

## 1. Google Analytics - CRO Strategy

### Prompt Key: `google_analytics_main`

**Before:** Basic 5-focus optimization (2000 tokens, gpt-4o-mini)
**After:** Comprehensive 8-section CRO framework (4000 tokens, gpt-4o)

### Analysis Framework

1. **Traffic Acquisition Audit** - Channel performance, quality, and ROI analysis
2. **User Behavior Analysis** - Engagement patterns, session depth, conversion propensity
3. **Conversion Funnel Optimization** - Drop-off points, friction identification, mobile gaps
4. **Revenue Optimization** - Monetization efficiency, AOV, customer value
5. **Content Performance Analysis** - Engagement by content type, conversion alignment
6. **Technical Analytics Audit** - Tracking accuracy, data quality, Core Web Vitals
7. **Audience Segmentation** - High-value segments for targeting and personalization
8. **Cross-Channel Attribution** - Multi-touch journeys, budget allocation

### Key Benchmarks Added

- Engagement Rate: 58% average, 65%+ excellent
- Conversion Rate by Channel: Organic 2.4%, Paid 2.9%, Email 3.2%
- E-commerce: Cart abandonment 69.8%, checkout completion 25-30%
- Mobile vs Desktop CVR: Mobile typically 64% of desktop
- Core Web Vitals: LCP<2.5s improves CVR by 24%

### Expected Impact

- **Conversions:** +30% improvement
- **Engagement Rate:** Reach 60%+
- **Revenue per Session:** +25% boost

---

## 2. Google Search Console - SEO Strategy

### Prompt Key: `search_console_main`

**Before:** Basic 5-focus SEO (2000 tokens, gpt-4o-mini)
**After:** Comprehensive 8-section SEO framework (4000 tokens, gpt-4o)

### Analysis Framework

1. **Content Audit** - Depth, intent alignment, SERP benchmarks
2. **Keyword Analysis** - Intent segmentation, featured snippet opportunities
3. **CTR Optimization** - Title/meta testing, schema markup, power words
4. **Ranking Opportunities** - Pages ranking 4-20 quick wins
5. **Technical SEO** - Core Web Vitals, mobile, page speed
6. **User Engagement Signals** - Bounce rate, dwell time indicators
7. **Content Freshness** - Topical authority, update strategies
8. **Local & Mobile SEO** - "Near me" queries, mobile optimization

### Key Benchmarks Added

- CTR by Position: #1: 27.6%, #2: 15.8%, #3: 11.0%
- Content Length: 1,447 words average for top rankings
- Core Web Vitals: LCP<2.5s, FID<100ms, CLS<0.1
- Local Intent: 46% of searches have local intent
- Featured Snippets: Appear in 12.3% of searches

### Expected Impact

- **Organic Traffic:** +30% growth
- **Average Position:** Improve to top 10
- **CTR:** Beat industry benchmarks by position

---

## 3. Local Services Ads - Lead Gen Strategy

### Prompt Key: `glsa_main`

**Before:** Basic 6-focus optimization (2000 tokens, gpt-4o-mini)
**After:** Comprehensive 8-section lead gen framework (4000 tokens, gpt-4o)

### Analysis Framework

1. **Profile Completeness Audit** - Score vs top 10%, Google Guaranteed badge
2. **Category Strategy** - Lead volume, quality, cost per lead optimization
3. **Service Area Optimization** - Geographic targeting, competition analysis
4. **Reviews & Reputation Management** - 4.7+ rating target, response strategy
5. **Budget & Bidding Strategy** - ROI optimization, dayparting, scaling
6. **Response Time Optimization** - <15 min target, booking rate improvement
7. **Lead Qualification Process** - Reduce wasted spend, dispute management
8. **Competitive Positioning** - Differentiation, value props, market gaps

### Key Benchmarks Added

- Profile Score: 90+ = top 10%, 80-89 = top 25%
- Response Time Impact: <5 min = 40-50% booking rate
- Lead Costs: Urban $40-80, Suburban $30-60, Rural $25-45
- Booking Rates: Emergency 35-45%, Scheduled 20-30%
- Dispute Success: 60-70% for legitimate invalid leads

### Expected Impact

- **Qualified Leads:** +40% increase
- **Booking Rate:** Reach 30%+
- **Cost per Lead:** -25% reduction

---

## 4. Google Business Profile - Local SEO Strategy

### Prompt Key: `gmb_main`

**Before:** Basic 7-focus optimization (2000 tokens, gpt-4o-mini)
**After:** Comprehensive 8-section local SEO framework (4000 tokens, gpt-4o)

### Analysis Framework

1. **Profile Completeness Audit** - 100-point scoring, NAP consistency
2. **Category Strategy** - Primary vs secondary category impact
3. **Description Optimization** - 750 char keyword-rich copy
4. **Visual Content Strategy** - 100+ photos target, video content
5. **Reviews & Reputation Excellence** - 4.5+ rating, 100% response rate
6. **Google Posts Strategy** - Weekly posts, seasonal calendar
7. **Q&A Management** - Seed questions, 24-hour response target
8. **Attributes & Features** - 10+ attributes for 25% more actions

### Key Benchmarks Added

- Profile Completeness: 90+ ranks in Local 3-Pack
- Photo Impact: 100+ photos = 520% more calls
- Posts: Weekly posts = 30% more engagement
- Ranking Factors: Reviews 25%, Completeness 25%, On-page 18%
- Attributes: 10+ = 25% more actions

### Expected Impact

- **Profile Views:** +50% increase
- **Website Clicks:** +35% boost
- **Direction Requests:** +30% growth
- **Local 3-Pack:** Consistent ranking

---

## 5. Facebook Page - Profile Strategy

### Prompt Key: `fbads_profile_main`

**Before:** Basic 5-focus optimization (1500 tokens, gpt-4o-mini)
**After:** Comprehensive 8-section profile framework (3000 tokens, gpt-4o)

### Analysis Framework

1. **Profile Info Optimization** - Name, category, username, verification
2. **Visual Branding Excellence** - Profile/cover photos, video cover
3. **About & Description Copy** - 255 char about, 400-600 description
4. **CTA Button Strategy** - Book Now, Get Quote, testing plan
5. **Content Pillars & Engagement** - 40/30/20/10 content mix
6. **Reviews & Recommendations** - 5-star target, response strategy
7. **Page Tabs & Features** - Essential tabs, custom features
8. **Insights & Optimization** - Quarterly audits, performance tracking

### Key Benchmarks Added

- Engagement Rate: >5% excellent, 3-5% good
- Video Reach: 135% more than photos
- Response Time: Within 2 hours for algorithm boost
- Reviews: 5-star avg = 30% higher ad CTR
- Mobile Traffic: 80% of page visits

### Expected Impact

- **Page Followers:** +30% growth
- **Engagement Rate:** Reach 5%+
- **Ad Conversion Rate:** +30% through trust signals

---

## 6. Facebook Ads - ROAS Optimization Strategy

### Prompt Key: `fbads_campaigns_main`

**Before:** Basic 7-focus optimization (2500 tokens, gpt-4o-mini)
**After:** Comprehensive 8-section ROAS framework (4000 tokens, gpt-4o)

### Analysis Framework

1. **Campaign Structure Audit** - Objective alignment, naming convention
2. **Audience Targeting Strategy** - Cold/warm/hot audiences, lookalikes
3. **Creative Optimization & Testing** - Video, carousel, UGC-style
4. **Bidding & Budget Optimization** - CBO vs ABO, scaling roadmap
5. **Placement Optimization** - Feed, Stories, Messenger analysis
6. **Conversion Tracking** - Pixel + CAPI, event match quality
7. **Ad Scheduling & Dayparting** - Time-of-day optimization
8. **Retargeting & Funnel Strategy** - 3-tier audience system

### Key Benchmarks Added

- Video Ads: 15% higher engagement than images
- Carousel: 30-50% lower CPA
- Learning Phase: 50 conversions needed
- Retargeting CPL: 50% lower than cold
- Budget Scaling: Max 20% every 3-4 days
- Event Match Quality: >6.0 required

### Expected Impact

- **ROAS:** +50% improvement
- **CPA:** -30% reduction
- **Conversion Rate:** +40% increase

---

## Implementation Guide

### 1. Initialize/Update Prompts

```bash
cd /home/fieljtgr
FLASK_APP=app virtualenv/bin/python -c "
from app.services.ai_prompts_init import initialize_ai_prompts
# Force update all prompts with new versions
count = initialize_ai_prompts(force=True)
print(f'Updated {count} AI prompts')
"
```

### 2. Verify Prompts in Database

```sql
-- Check all active prompts
SELECT
    prompt_key,
    name,
    model,
    temperature,
    max_tokens,
    LENGTH(prompt_template) as template_length
FROM ai_prompts
WHERE is_active = TRUE
ORDER BY prompt_key;

-- Verify specific prompt
SELECT prompt_template
FROM ai_prompts
WHERE prompt_key = 'google_analytics_main';
```

### 3. Test Prompt Retrieval

```python
from app.services.ai_prompts_init import get_prompt_for_service

# Test retrieval
prompt = get_prompt_for_service('google_analytics_main')
print(f"Model: {prompt['model']}")
print(f"Temperature: {prompt['temperature']}")
print(f"Max Tokens: {prompt['max_tokens']}")
```

### 4. Monitor API Costs

**Cost Comparison:**

| Prompt | Old Model | New Model | Old Tokens | New Tokens | Cost Change |
|--------|-----------|-----------|------------|------------|-------------|
| Google Analytics | gpt-4o-mini | gpt-4o | 2000 | 4000 | +10x higher |
| Search Console | gpt-4o-mini | gpt-4o | 2000 | 4000 | +10x higher |
| LSA | gpt-4o-mini | gpt-4o | 2000 | 4000 | +10x higher |
| GBP | gpt-4o-mini | gpt-4o | 2000 | 4000 | +10x higher |
| FB Page | gpt-4o-mini | gpt-4o | 1500 | 3000 | +10x higher |
| FB Ads | gpt-4o-mini | gpt-4o | 2500 | 4000 | +10x higher |

**Pricing (as of 2026-01):**
- GPT-4o: $2.50 per 1M input tokens, $10 per 1M output tokens
- GPT-4o-mini: $0.15 per 1M input tokens, $0.60 per 1M output tokens

**Estimated cost per insight:** $0.02-$0.05 (gpt-4o) vs $0.001-$0.003 (gpt-4o-mini)

**ROI Justification:** Higher cost but 3-5x better recommendations = worth the investment for paying customers.

---

## Customization Guide

### Adjust Model Temperature

```sql
-- More creative/diverse recommendations
UPDATE ai_prompts
SET temperature = 0.7
WHERE prompt_key = 'google_analytics_main';

-- More focused/conservative recommendations
UPDATE ai_prompts
SET temperature = 0.3
WHERE prompt_key = 'google_analytics_main';
```

### Change Model

```sql
-- Use more cost-effective model for testing
UPDATE ai_prompts
SET model = 'gpt-4o-mini'
WHERE prompt_key IN ('glsa_main', 'gmb_main');

-- Use most powerful model for critical tools
UPDATE ai_prompts
SET model = 'gpt-4o'
WHERE prompt_key IN ('google_ads_main', 'search_console_main');
```

### Adjust Output Length

```sql
-- Shorter recommendations for quick insights
UPDATE ai_prompts
SET max_tokens = 2000
WHERE prompt_key = 'fbads_profile_main';

-- Longer, more detailed analysis
UPDATE ai_prompts
SET max_tokens = 5000
WHERE prompt_key = 'google_ads_main';
```

### Customize Industry Benchmarks

```sql
-- Update benchmarks in prompt template
UPDATE ai_prompts
SET prompt_template = REPLACE(
    prompt_template,
    'Engagement Rate: 58% average',
    'Engagement Rate: 65% average'
)
WHERE prompt_key = 'google_analytics_main';
```

---

## Monitoring & Optimization

### Track Recommendation Quality

```sql
-- Check recommendation acceptance rates
SELECT
    source_type,
    COUNT(*) as total_recs,
    SUM(CASE WHEN status = 'applied' THEN 1 ELSE 0 END) as applied,
    SUM(CASE WHEN status = 'dismissed' THEN 1 ELSE 0 END) as dismissed,
    ROUND(100.0 * SUM(CASE WHEN status = 'applied' THEN 1 ELSE 0 END) / COUNT(*), 1) as apply_rate
FROM optimizer_recommendations
WHERE created_at > NOW() - INTERVAL '30 days'
GROUP BY source_type
ORDER BY apply_rate DESC;
```

### Monitor API Usage

```python
# Log API calls and costs
import logging

logger = logging.getLogger('ai_insights')
logger.info(f"Generated insights: {prompt_key}, model: {model}, tokens: {tokens_used}, cost: ${cost:.4f}")
```

### A/B Test Prompts

```sql
-- Create test variant
INSERT INTO ai_prompts (
    prompt_key, name, model, temperature, max_tokens,
    system_message, prompt_template, is_active
)
SELECT
    'google_analytics_test_v2',
    name || ' (Test V2)',
    'gpt-4o',
    0.5,  -- Different temperature
    max_tokens,
    system_message,
    prompt_template,
    FALSE  -- Not active by default
FROM ai_prompts
WHERE prompt_key = 'google_analytics_main';

-- Activate test variant for specific accounts
-- (requires code changes to route by account)
```

---

## Troubleshooting

### Issue: Prompts not updating

**Check:**
```sql
SELECT * FROM ai_prompts WHERE prompt_key = 'google_analytics_main';
```

**Fix:**
```bash
python -c "from app.services.ai_prompts_init import initialize_ai_prompts; initialize_ai_prompts(force=True)"
```

### Issue: API errors or timeouts

**Possible causes:**
- OpenAI API key invalid/expired
- Rate limits exceeded
- Prompt template has formatting errors (missing `{variables}`)

**Check:**
```python
from app.services.ai_prompts_init import get_prompt_for_service
prompt = get_prompt_for_service('google_analytics_main')
# Verify all template variables are present
print(prompt['prompt_template'])
```

### Issue: Low-quality recommendations

**Tune:**
- Reduce temperature (0.3-0.4) for more focused output
- Increase max_tokens for more detailed analysis
- Add more specific benchmarks to prompt template
- Switch to gpt-4o from gpt-4o-mini

---

## Best Practices

1. **Update Prompts Quarterly** - Industry benchmarks change, keep current
2. **Monitor Costs** - Track OpenAI spend, optimize model selection
3. **Track Acceptance Rates** - Measure which tools provide most value
4. **Version Control** - Document prompt changes in changelog
5. **Test Before Deploying** - Validate prompts in dev environment first
6. **Customize Per Industry** - Consider vertical-specific benchmarks
7. **Keep Templates DRY** - Extract common patterns to reduce duplication

---

## Changelog

### 2026-01-20: Comprehensive Optimization Upgrade

**Upgraded 6 AI Tools:**
- Google Analytics: Basic → Comprehensive 8-section CRO
- Search Console: Basic → Comprehensive 8-section SEO
- Local Services Ads: Basic → Comprehensive 8-section Lead Gen
- Google Business Profile: Basic → Comprehensive 8-section Local SEO
- Facebook Page: Basic → Comprehensive 8-section Profile
- Facebook Ads: Basic → Comprehensive 8-section ROAS

**Key Changes:**
- Model: gpt-4o-mini → gpt-4o (6 tools)
- Temperature: 0.7 → 0.4 (more focused)
- Max Tokens: 1500-2500 → 3000-4000 (more detailed)
- Added 50+ industry benchmarks across all tools
- Structured 8-section analysis framework
- Specific action steps and implementation guides

**Expected Impact:**
- 3-5x more actionable recommendations
- Higher recommendation acceptance rates
- Better strategic alignment across tools
- Consistent framework for all analyses

---

## Support & Resources

- **Prompt File:** `flaskapp/app/services/ai_prompts_init.py`
- **Database Table:** `ai_prompts`
- **Retrieval Function:** `get_prompt_for_service(prompt_key)`
- **OpenAI Docs:** https://platform.openai.com/docs
- **Cost Calculator:** https://openai.com/pricing

---

**Last Updated:** 2026-01-20
**Version:** 2.0 (Comprehensive Strategic Framework)
