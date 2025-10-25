# Metrics Integration Guide

## What "Integrate metrics saving into existing API calls" means

Currently, when you fetch data from Google Ads, Facebook Ads, etc., you:
1. Fetch the data from the API
2. Display it to the user
3. **That's it - the data is lost when the page closes**

We need to ADD a step:
1. Fetch the data from the API
2. **SAVE it to the performance_metrics table** ← NEW STEP
3. Display it to the user

This way, you build a historical database of performance over time.

---

## Example: Facebook Ads Integration

### Before (Current Code - No Storage):
```python
# In your fbads route or service
@fbads_bp.route('/campaigns')
def campaigns():
    # Fetch from Facebook API
    campaigns_data = fetch_facebook_campaigns()

    # Display to user
    return render_template('fbads/campaigns.html', data=campaigns_data)
    # ← Data is lost after this point!
```

### After (With Metrics Storage):
```python
from app.services.metrics_service import save_metrics
import datetime as dt

@fbads_bp.route('/campaigns')
def campaigns():
    # Fetch from Facebook API
    campaigns_data = fetch_facebook_campaigns()

    # NEW: Save to performance_metrics table for historical tracking
    for campaign in campaigns_data:
        save_metrics(
            account_id=current_user.account_id,
            source_type='fbads',
            source_id=campaign['page_id'],
            date=dt.date.today(),
            entity_type='campaign',
            entity_id=campaign['id'],
            entity_name=campaign['name'],
            metrics={
                'reach': campaign['reach'],
                'impressions': campaign['impressions'],
                'clicks': campaign['clicks'],
                'spend': campaign['spend'],
                'leads': campaign['leads'],
                'cpm': campaign['cpm'],
                'cpc': campaign['cpc']
            }
        )

    # Display to user
    return render_template('fbads/campaigns.html', data=campaigns_data)
    # ← Data is now saved for future analysis!
```

---

## Where to Add Metrics Saving

### 1. Google Ads
**File**: `app/google/ads.py` or wherever you fetch Google Ads data

**When**: After fetching campaign/ad group/keyword performance

**Code to add**:
```python
from app.services.metrics_service import save_metrics

# After fetching Google Ads data
save_metrics(
    account_id=account_id,
    source_type='google_ads',
    source_id=customer_id,
    date=dt.date.today(),
    entity_type='campaign',
    entity_id=campaign_id,
    entity_name=campaign_name,
    metrics={
        'impressions': impressions,
        'clicks': clicks,
        'cost': cost,
        'conversions': conversions,
        'cost_per_conversion': cost_per_conversion
    }
)
```

### 2. Google Analytics
**File**: `app/google/__init__.py` (ga_ui route) or analytics service

**When**: After fetching Analytics data

**Code to add**:
```python
save_metrics(
    account_id=account_id,
    source_type='google_analytics',
    source_id=property_id,
    date=dt.date.today(),
    metrics={
        'sessions': sessions,
        'pageviews': pageviews,
        'bounce_rate': bounce_rate,
        'avg_session_duration': avg_session_duration,
        'goal_completions': goal_completions
    }
)
```

### 3. Google Search Console
**File**: `app/google/__init__.py` (gsc routes)

**When**: After fetching GSC performance data

**Code to add**:
```python
save_metrics(
    account_id=account_id,
    source_type='search_console',
    source_id=site_url,
    date=dt.date.today(),
    metrics={
        'impressions': impressions,
        'clicks': clicks,
        'ctr': ctr,
        'position': avg_position
    }
)
```

### 4. Google Local Services Ads (GLSA)
**File**: `app/glsa/__init__.py`

**When**: After fetching GLSA leads/performance

**Code to add**:
```python
save_metrics(
    account_id=account_id,
    source_type='glsa',
    source_id=None,  # GLSA doesn't have a specific ID
    date=dt.date.today(),
    metrics={
        'leads': leads_count,
        'phone_calls': phone_calls,
        'messages': messages,
        'bookings': bookings,
        'spend': spend
    }
)
```

### 5. Google My Business (GMB)
**File**: `app/gmb/__init__.py`

**When**: After fetching GMB insights

**Code to add**:
```python
save_metrics(
    account_id=account_id,
    source_type='gmb',
    source_id=location_id,
    date=dt.date.today(),
    entity_type='location',
    entity_id=location_id,
    entity_name=location_name,
    metrics={
        'views': views,
        'searches': searches,
        'actions': actions,
        'calls': calls,
        'direction_requests': direction_requests,
        'website_clicks': website_clicks
    }
)
```

### 6. Facebook Ads
**File**: `app/fbads/__init__.py`

**When**: After fetching FB Ads campaigns/performance

**Code to add**:
```python
save_metrics(
    account_id=account_id,
    source_type='fbads',
    source_id=page_id,
    date=dt.date.today(),
    entity_type='campaign',
    entity_id=campaign_id,
    entity_name=campaign_name,
    metrics={
        'reach': reach,
        'impressions': impressions,
        'clicks': clicks,
        'spend': spend,
        'leads': leads,
        'cpm': cpm,
        'cpc': cpc,
        'ctr': ctr
    }
)
```

---

## Benefits of Integration

1. **Historical Tracking**: See how performance changes over time
2. **Trend Analysis**: Identify patterns and seasonality
3. **YoY Comparison**: Compare this October to last October
4. **Better AI Insights**: AI can analyze trends, not just current snapshot
5. **Reporting**: Generate monthly/quarterly reports automatically
6. **ROI Proof**: Show improvement after using FieldSprout

---

## Implementation Priority

**High Priority** (Do these first):
1. Google Ads - Most critical for spend tracking
2. Facebook Ads - Important for lead generation
3. GLSA - Direct lead tracking

**Medium Priority**:
4. GMB - Local visibility metrics
5. Google Analytics - Website performance

**Lower Priority** (but still important):
6. Search Console - SEO performance

---

## Testing Your Integration

After adding metrics saving, verify it's working:

```sql
-- Check if metrics are being saved
SELECT
  source_type,
  COUNT(*) as record_count,
  MIN(date) as earliest_date,
  MAX(date) as latest_date
FROM performance_metrics
WHERE account_id = YOUR_ACCOUNT_ID
GROUP BY source_type;

-- View recent saves
SELECT *
FROM performance_metrics
WHERE account_id = YOUR_ACCOUNT_ID
ORDER BY created_at DESC
LIMIT 20;
```
