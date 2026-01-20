# Google Search Console SEO Recommendations Guide

## System Overview

Your FieldSprout application has an AI-powered SEO recommendations system that analyzes Google Search Console data and provides actionable optimization suggestions.

## How It Works

### 1. **Prompt Storage System**
- SEO prompts are stored in the `ai_prompts` database table
- Key: `search_console_main`
- Allows customization without code changes
- Supports A/B testing different prompt strategies

### 2. **Data Flow**

```
Google Search Console
        ↓
   (OAuth Token)
        ↓
Fetch Performance Data (clicks, impressions, CTR, position)
        ↓
AI Analysis (OpenAI with database-stored prompt)
        ↓
Store Recommendations (optimizer_recommendations table)
        ↓
Display in UI (gsc.html template)
```

### 3. **Two Systems in the Codebase**

#### **Legacy System** (Simple Inline Insights)
- **File:** `app/google/__init__.py` lines 756-837
- **Function:** `get_gsc_insights(gsc)`
- **Prompt:** Inline hardcoded prompt (lines 786-796)
- **Output:** Simple markdown text displayed in "AI Insights" card
- **Use:** Quick inline suggestions on GSC dashboard

#### **New System** (Comprehensive Database-Driven)
- **File:** `app/services/gsc_insights.py`
- **Function:** `generate_gsc_insights(account_id, site_url, regenerate=False)`
- **Prompt:** Database-stored comprehensive prompt (`ai_prompts` table)
- **Output:** Structured recommendations stored in `optimizer_recommendations` table
- **Use:** Detailed SEO audit with trackable recommendations

## Current Implementation Status

### ✅ Working Components
1. Database-stored prompt system (`ai_prompts` table)
2. Service layer (`services/gsc_insights.py`) with comprehensive analysis
3. Recommendation storage (`optimizer_recommendations` table)
4. Apply/dismiss workflow (`OptimizerAction` tracking)
5. Confidence scoring based on data quality
6. Updated `gsc_optimize` route to use database prompts

### ⚠️ Needs Integration
1. **Route Integration:** The "Optimize" button now calls `generate_gsc_insights()`
2. **UI Display:** Recommendations need to be displayed in template
3. **Data Fetching:** GSC data fetching logic (currently returns zeros)

## The Database-Stored Prompt

**Location:** `ai_prompts` table, `prompt_key='search_console_main'`

**Key Features:**
- Analyzes 5 SEO dimensions: Keywords, Content, Technical SEO, CTR Optimization, Rankings
- Provides severity levels (1=critical, 2=high-impact, 3=quick win, 4-5=long-term)
- Includes expected impact metrics
- Returns structured JSON recommendations
- Model: `gpt-4o-mini` (cost-efficient)
- Temperature: 0.7 (balanced creativity)

**Prompt Focus Areas:**
1. **High-impression, low-CTR queries** (title/meta optimization)
2. **Pages ranking 4-10** (content improvement to reach page 1)
3. **Declining rankings** (content refresh needed)
4. **Technical SEO issues**
5. **Content gap opportunities**

## Recommendation Categories

| Category | Description | Example |
|----------|-------------|---------|
| `keywords` | Query and keyword targeting | "Target high-volume keywords with position 8-12" |
| `content` | On-page content optimization | "Expand thin content on top landing pages" |
| `technical_seo` | Technical issues | "Fix pages with slow load times affecting rankings" |
| `ctr_optimization` | Meta tags and snippets | "Optimize meta descriptions for queries with <2% CTR" |
| `rankings` | Position improvements | "Push page 2 rankings to page 1" |
| `schema` | Structured data | "Add FAQ schema for question-based queries" |
| `mobile` | Mobile optimization | "Improve mobile UX for pages with high mobile traffic" |

## Confidence Scoring

Recommendations are scored based on data quality:

```python
base_confidence = 0.75

# Adjustments:
- clicks < 50: × 0.5
- clicks < 500: × 0.8
- impressions < 1000: × 0.7
- severity = 1 (critical): × 1.1
```

**Result:** Confidence between 0.0 and 1.0

## API Usage

### Generate Insights

```python
from app.services.gsc_insights import generate_gsc_insights

insights = generate_gsc_insights(
    account_id=123,
    site_url="https://example.com",
    regenerate=False  # True to ignore cache and regenerate
)

# Returns:
{
    "summary": "Overall assessment text",
    "recommendations": [
        {
            "id": 456,
            "title": "Optimize High-Impression, Low-CTR Queries",
            "description": "Found 12 queries with high impressions but low clicks...",
            "category": "keywords",
            "severity": 3,
            "expected_impact": "Increase clicks by 20-30%",
            "confidence": 0.85,
            "data_points": ["keyword plumbing: 5000 impr, 1.2% CTR"],
            "action": {"type": "optimize", "target": "meta_descriptions"}
        }
    ],
    "stats": {
        "total": 8,
        "open": 8,
        "critical": 1,
        "high_impact": 3,
        "quick_wins": 4
    }
}
```

### Apply Recommendation

```python
from app.services.gsc_insights import apply_gsc_recommendation

success, message = apply_gsc_recommendation(
    recommendation_id=456,
    user_id=789
)
```

### Dismiss Recommendation

```python
from app.services.gsc_insights import dismiss_gsc_recommendation

success, message = dismiss_gsc_recommendation(
    recommendation_id=456,
    user_id=789,
    reason="Already implemented manually"
)
```

## Caching & Performance

- **Cache Duration:** 6 hours
- **Prevents:** Redundant OpenAI API calls
- **Cache Key:** Account ID + Site URL + Open status
- **Cache Invalidation:** Manual regenerate or after 6 hours

## Data Requirements

**Minimum for meaningful recommendations:**
- **Clicks:** 50+ (better with 500+)
- **Impressions:** 1000+
- **Time Period:** 30 days
- **Top Queries:** 15+ queries tracked
- **Top Pages:** 10+ pages tracked

**Below minimums:** Recommendations will have lower confidence scores

## Fallback Recommendations

If OpenAI fails or returns invalid JSON, the system provides rule-based fallbacks:

1. **Low CTR** (< 2%): "Improve Meta Titles and Descriptions"
2. **Poor Position** (> 10): "Improve Content Quality for Better Rankings"
3. **Low-CTR Queries:** "Optimize High-Impression, Low-CTR Queries"
4. **Pages Ranking 4-10:** "Push Page 2 Rankings to Page 1"

## Database Schema

### `ai_prompts` Table
```sql
CREATE TABLE ai_prompts (
    id SERIAL PRIMARY KEY,
    prompt_key VARCHAR(100) UNIQUE NOT NULL,
    name VARCHAR(255),
    description TEXT,
    system_message TEXT,
    prompt_template TEXT,
    model VARCHAR(50) DEFAULT 'gpt-4o-mini',
    temperature DECIMAL(3,2) DEFAULT 0.7,
    max_tokens INTEGER DEFAULT 2000,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### `optimizer_recommendations` Table
```sql
CREATE TABLE optimizer_recommendations (
    id SERIAL PRIMARY KEY,
    account_id INTEGER NOT NULL,
    source_type VARCHAR(50) NOT NULL,  -- 'search_console'
    source_id VARCHAR(255),             -- site_url
    category VARCHAR(50),
    title VARCHAR(255),
    details TEXT,
    expected_impact VARCHAR(255),
    confidence DECIMAL(3,2),
    severity INTEGER,
    data_points TEXT,                   -- JSON array
    action_data TEXT,                   -- JSON object
    status VARCHAR(20) DEFAULT 'open',  -- 'open', 'applied', 'dismissed', 'superseded'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## Customizing the Prompt

To customize SEO recommendations:

1. **Update Database Prompt:**
```sql
UPDATE ai_prompts
SET prompt_template = 'Your custom prompt template here...'
WHERE prompt_key = 'search_console_main';
```

2. **Adjust Model Settings:**
```sql
UPDATE ai_prompts
SET
    model = 'gpt-4o',  -- More powerful model
    temperature = 0.5,  -- More conservative
    max_tokens = 3000   -- Longer responses
WHERE prompt_key = 'search_console_main';
```

3. **Test Changes:** Regenerate insights with `regenerate=True`

## Troubleshooting

### No Recommendations Generated

**Check:**
1. ✅ OpenAI API key configured: `OPENAI_API_KEY` in environment
2. ✅ GSC connected and data available
3. ✅ Prompt exists in database: `SELECT * FROM ai_prompts WHERE prompt_key = 'search_console_main';`
4. ✅ Check logs for errors: `tail -f logs/flask.log | grep -i "gsc\|search console"`

### Low Quality Recommendations

**Possible causes:**
- Insufficient data (< 50 clicks, < 1000 impressions)
- Short time period (< 30 days)
- Prompt needs tuning
- Model temperature too high (increase creativity) or too low (too generic)

### Recommendations Not Appearing in UI

**Check:**
1. ✅ Optimize button clicked and request succeeded
2. ✅ Check database: `SELECT * FROM optimizer_recommendations WHERE source_type = 'search_console' AND status = 'open';`
3. ✅ Template integration for displaying recommendations

## Next Steps

1. **Integrate Data Fetching:** Connect real GSC API data fetching logic
2. **UI Enhancement:** Display recommendations in template with apply/dismiss buttons
3. **Automation:** Schedule daily/weekly insights generation for high-traffic sites
4. **Alerts:** Notify users when critical SEO issues detected
5. **Tracking:** Monitor applied recommendations and measure impact

## Files to Review

- **Service:** `flaskapp/app/services/gsc_insights.py`
- **Routes:** `flaskapp/app/google/__init__.py` (lines 1891-1970 for optimize route)
- **Prompts:** `flaskapp/app/services/ai_prompts_init.py` (lines 159-206)
- **Template:** `flaskapp/templates/google/gsc.html`
- **Models:** `flaskapp/app/models_ads.py` (OptimizerRecommendation, OptimizerAction)

---

**Last Updated:** 2026-01-20
**System Version:** Database-driven comprehensive SEO analysis with fallback to inline insights
