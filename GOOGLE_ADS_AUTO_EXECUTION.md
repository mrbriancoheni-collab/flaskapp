# Google Ads Auto-Execution System

**Automatically optimize Google Ads campaigns with AI-powered actions and full undo capability.**

## 📋 Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Architecture](#architecture)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [AI Action Types](#ai-action-types)
- [Safety Mechanisms](#safety-mechanisms)
- [Monitoring](#monitoring)
- [Troubleshooting](#troubleshooting)

---

## Overview

The Google Ads Auto-Execution system automatically identifies and executes safe optimizations across your Google Ads campaigns. Every action is logged with complete reasoning, confidence scores, and undo capability.

**Key Benefits:**
- 🚀 **Automatic Optimization**: AI identifies and fixes campaign issues 24/7
- 📊 **Full Transparency**: Every action is logged with reasoning and data
- ↩️ **One-Click Undo**: All changes can be reversed with a single click
- 🎯 **High Confidence**: Only executes actions with >85% confidence
- 🛡️ **Safety Limits**: Daily caps prevent runaway automation

---

## Features

### 1. **Auto-Add Negative Keywords**

Automatically blocks non-purchase intent search terms to reduce wasted spend.

**Triggers:**
- Search term contains non-purchase intent patterns (jobs, DIY, free, reviews, etc.)
- Confidence score > 85%
- Within daily limit (100 per account per day)

**Example:**
```
Search Term: "plumber jobs near me"
Action: Add as negative keyword (phrase match)
Confidence: 92%
Reasoning: Matches employment-seeking pattern; $45.50 spent, 0 conversions
Estimated Savings: $45.50/month
```

### 2. **Future: Auto-Pause Low-Performing Keywords**

Coming soon: Automatically pause keywords with poor performance.

### 3. **Future: Auto-Adjust Bids**

Coming soon: Adjust bids based on performance and conversion rates.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Cron Job (Hourly)                       │
│                 scripts/auto_execute_google_ads.py          │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ↓
┌─────────────────────────────────────────────────────────────┐
│              Google Ads Auto-Executor Service               │
│        app/services/google_ads_auto_executor.py             │
│                                                              │
│  • Analyzes search terms (last 30 days)                    │
│  • Detects non-purchase intent (60+ patterns)              │
│  • Calculates confidence scores                            │
│  • Checks daily limits                                      │
│  • Creates AIAction records                                 │
│  • Executes via Google Ads API                             │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ↓
┌─────────────────────────────────────────────────────────────┐
│                    AIAction Model                           │
│              app/models_ai_actions.py                       │
│                                                              │
│  • Complete audit trail                                     │
│  • Before/after values                                      │
│  • Confidence scores                                        │
│  • Reasoning & data used                                    │
│  • Undo capability                                          │
└─────────────────────────────────────────────────────────────┘
```

---

## Installation

### Step 1: Create Database Tables

Run the migration script to create the new tables:

```bash
cd /home/user/flaskapp
python scripts/create_ai_tables.py
```

This creates:
- `ai_actions` - Log of all AI-driven changes
- `ai_action_rules` - Rules governing when AI should act

### Step 2: Configure Cron Jobs

Run the cron setup script to configure automated execution:

```bash
cd /home/user/flaskapp
python scripts/setup_cron_jobs.py
```

This will add:
- **Hourly (at :30)**: Run Google Ads auto-execution
- **Hourly (at :00)**: Check for new alerts
- **Every 15 min**: Send alert notifications
- **Daily at 2 AM**: Run lead automation
- **Daily at 4 AM**: Clean up stale alerts

### Step 3: Verify Installation

Check that cron jobs are configured:

```bash
crontab -l
```

You should see entries like:
```
30 * * * * cd /home/user/flaskapp && python scripts/auto_execute_google_ads.py >> /tmp/google_ads_auto_execute.log 2>&1
```

---

## Configuration

### Daily Limits

Edit `app/services/google_ads_auto_executor.py` to adjust limits:

```python
MAX_ACTIONS_PER_DAY = {
    'negative_keyword_added': 100,   # Max negative keywords per account per day
    'keyword_paused': 20,
    'bid_adjusted': 50,
    'budget_reallocated': 10,
}
```

### Confidence Thresholds

Edit confidence requirements:

```python
CONFIDENCE_THRESHOLDS = {
    'negative_keyword_added': 0.85,  # 85% confidence required
    'keyword_paused': 0.90,          # 90% confidence required
    'bid_adjusted': 0.75,
    'budget_reallocated': 0.80,
}
```

### Non-Purchase Intent Patterns

Add/remove patterns that indicate non-purchase intent:

```python
NON_PURCHASE_INTENT_PATTERNS = [
    # Job seeking
    'job', 'jobs', 'career', 'hiring', ...

    # DIY/How-to
    'how to', 'diy', 'tutorial', ...

    # Free seekers
    'free', 'cheap', 'discount', ...

    # Add custom patterns here
    'pattern1', 'pattern2', ...
]
```

---

## Usage

### Viewing AI Actions

Visit the Google Ads dashboard to see all AI actions:
```
https://fieldsprout.io/account/google/ads
```

### Understanding Action Log

Each action shows:
- **Title**: Brief description (e.g., "Block Non-Purchase Intent: 'plumber jobs'")
- **Confidence**: How confident the AI is (0.0 to 1.0)
- **Reasoning**: Why this action was taken
- **Data Used**: Metrics that informed the decision
- **Estimated Savings**: Expected monthly savings
- **Status**: pending | executed | failed | undone

### Undoing an Action

1. Click the "Undo" button next to any executed action
2. Confirm the undo operation
3. The original state will be restored
4. Action status changes to "undone"

---

## AI Action Types

### negative_keyword_added

**What it does**: Adds a search term as a negative keyword (phrase match) at campaign level

**When it triggers**:
- Search term matches non-purchase intent patterns
- Confidence score > 85%
- Has generated impressions/clicks but low/no conversions
- Within daily limit (100/day)

**Confidence calculation**:
```
Base: 0.5
+ Pattern matches (0.0 to 0.4): more matches = higher confidence
+ Zero conversions (0.3): No conversions = high confidence to block
+ Low CTR (0.0 to 0.2): CTR < 1% = poor relevance
+ High spend (0.1): >$50 spent with no conversions
= Total confidence (0.0 to 1.0)
```

**Example data**:
```json
{
  "search_term": "plumber jobs near me",
  "patterns_matched": ["job", "jobs", "near me"],
  "impressions": 523,
  "clicks": 23,
  "conversions": 0,
  "cost": 45.50,
  "ctr": 0.044,
  "conversion_rate": 0.0
}
```

---

## Safety Mechanisms

### 1. Daily Limits

Each action type has a daily cap per account:
- Prevents runaway automation
- Limits worst-case impact
- Resets at midnight UTC

### 2. Confidence Thresholds

Actions only execute if confidence exceeds threshold:
- **85%** for negative keywords (safe action)
- **90%** for pausing (more impactful)
- **75%** for bid adjustments (reversible)

### 3. Lookback Windows

Analyzes data from specific time periods:
- **30 days** for search terms (default)
- Requires minimum impressions (10+)
- Excludes already-blocked terms

### 4. Pattern Matching

Uses 60+ carefully curated patterns:
- Job seeking: "job", "jobs", "career", "hiring"
- DIY/How-to: "how to", "diy", "tutorial"
- Free seekers: "free", "cheap", "discount"
- Research: "review", "comparison", "vs"
- Media: "image", "video", "youtube"

### 5. Full Audit Trail

Every action is logged with:
- Complete reasoning
- Data used for decision
- Before/after values
- Timestamp and user
- Undo capability

---

## Monitoring

### Check Execution Logs

View the auto-execution log:
```bash
tail -f /tmp/google_ads_auto_execute.log
```

Look for:
- Number of accounts processed
- Actions created/executed per account
- Any errors or failures

### Monitor Action Counts

Check daily action counts:
```python
from app.models_ai_actions import AIAction
from datetime import datetime, timedelta

today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
count = AIAction.query.filter(
    AIAction.created_at >= today,
    AIAction.status == 'executed'
).count()

print(f"Actions executed today: {count}")
```

### Review Confidence Distribution

Check average confidence scores:
```python
from sqlalchemy import func

avg_confidence = db.session.query(
    func.avg(AIAction.confidence_score)
).filter(
    AIAction.status == 'executed'
).scalar()

print(f"Average confidence: {avg_confidence:.2%}")
```

---

## Troubleshooting

### Issue: No actions being created

**Possible causes:**
1. Daily limit reached → Check logs for "Daily limit reached"
2. No search terms match patterns → Review patterns in code
3. Confidence too low → Lower threshold or refine patterns
4. Google Ads API error → Check API credentials

**Solution:**
```bash
# Check logs
tail -100 /tmp/google_ads_auto_execute.log | grep "account"

# Verify Google Ads connection
python -c "from app.google.utils_ads import client_from_refresh; ..."
```

### Issue: Actions failing to execute

**Possible causes:**
1. Google Ads API permission issues
2. Invalid campaign/customer ID
3. Network connectivity

**Solution:**
```bash
# Check action failure reasons
SELECT id, title, execution_error
FROM ai_actions
WHERE status = 'failed'
ORDER BY created_at DESC
LIMIT 10;
```

### Issue: Too many actions being created

**Possible causes:**
1. Daily limits too high
2. Confidence threshold too low
3. Patterns too broad

**Solution:**
1. Lower daily limits in `MAX_ACTIONS_PER_DAY`
2. Raise confidence threshold in `CONFIDENCE_THRESHOLDS`
3. Review and refine `NON_PURCHASE_INTENT_PATTERNS`

### Issue: Cron job not running

**Check crontab:**
```bash
crontab -l
```

**Check cron logs:**
```bash
tail -f /var/log/cron.log
# or
grep CRON /var/log/syslog
```

**Test manual execution:**
```bash
cd /home/user/flaskapp
python scripts/auto_execute_google_ads.py
```

---

## Best Practices

### 1. Start with Dry Run

Before enabling auto-execution, test with dry run:
```python
executor = GoogleAdsAutoExecutor(account_id)
actions = executor.auto_add_negative_keywords(dry_run=True)
```

### 2. Monitor for First Week

Watch the system closely for the first week:
- Review all actions daily
- Check confidence scores
- Verify negative keywords make sense
- Adjust patterns as needed

### 3. Set Conservative Limits

Start with lower daily limits:
```python
MAX_ACTIONS_PER_DAY = {
    'negative_keyword_added': 25,  # Start conservative
}
```

Increase gradually as you build confidence.

### 4. Review Regularly

Weekly reviews:
- Check total actions executed
- Review average confidence scores
- Identify any false positives
- Refine patterns based on learnings

---

## Database Schema

### ai_actions Table

```sql
CREATE TABLE ai_actions (
    id INT PRIMARY KEY AUTO_INCREMENT,
    account_id INT NOT NULL,
    action_type ENUM('negative_keyword_added', ...) NOT NULL,
    title VARCHAR(255) NOT NULL,
    description TEXT NOT NULL,
    campaign_id VARCHAR(64),
    campaign_name VARCHAR(255),
    ad_group_id VARCHAR(64),
    ad_group_name VARCHAR(255),
    before_value JSON,
    after_value JSON,
    estimated_monthly_savings FLOAT,
    confidence_score FLOAT,
    reasoning TEXT,
    data_used JSON,
    status ENUM('pending', 'executed', 'failed', 'undone') NOT NULL,
    executed_at DATETIME,
    can_undo BOOLEAN DEFAULT TRUE,
    undone_at DATETIME,
    undone_by INT,
    undo_reason VARCHAR(255),
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    INDEX idx_account_id (account_id),
    INDEX idx_status (status),
    INDEX idx_created_at (created_at)
);
```

### ai_action_rules Table

```sql
CREATE TABLE ai_action_rules (
    id INT PRIMARY KEY AUTO_INCREMENT,
    account_id INT NOT NULL,
    rule_name VARCHAR(255) NOT NULL,
    action_type VARCHAR(64) NOT NULL,
    conditions JSON NOT NULL,
    auto_execute BOOLEAN DEFAULT TRUE,
    min_confidence FLOAT DEFAULT 0.8,
    enabled BOOLEAN DEFAULT TRUE,
    max_actions_per_day INT DEFAULT 50,
    max_actions_per_campaign INT DEFAULT 10,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    INDEX idx_account_id (account_id),
    INDEX idx_enabled (enabled)
);
```

---

## Support

For issues or questions:
1. Check logs: `/tmp/google_ads_auto_execute.log`
2. Review this documentation
3. Check action failure reasons in database
4. Contact development team

---

## Version History

### v1.0.0 (2026-01-11)
- Initial release
- Auto-add negative keywords for non-purchase intent
- Full audit trail and undo capability
- Daily limits and confidence thresholds
- Hourly cron execution

### Future Releases
- v1.1.0: Auto-pause low-performing keywords
- v1.2.0: Auto-adjust bids based on performance
- v1.3.0: Budget reallocation across campaigns
- v2.0.0: Machine learning-based confidence scoring
