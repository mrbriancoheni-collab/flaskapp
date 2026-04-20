# AI Actions System - How It Works

## Why Are You Seeing Zeros?

If the AI Change Log and Decision Screen are showing **$0 saved**, **0 actions**, and **no recent changes**, it's because **no AI actions have been recorded yet** in the `ai_actions` database table.

This is **normal** for:
- New accounts
- Accounts that just connected to Google Ads
- Accounts where the AI agent hasn't run yet

---

## How the AI System Works

### 1. Data Collection
The system pulls data from your Google Ads account:
- Keywords and their performance
- Search terms report
- Campaign budgets and spending
- Conversion data

### 2. AI Analysis
The AI agent analyzes this data to find:
- **Irrelevant searches** → Block with negative keywords
- **Budget waste** → Reallocate to better performers
- **Underperforming keywords** → Pause or adjust bids
- **Missed opportunities** → Suggest new keywords or campaigns

### 3. AI Actions Recorded
When the AI makes changes, it creates records in the `ai_actions` table with:
- `action_type`: What it did (negative_keyword_added, budget_adjusted, etc.)
- `action_description`: Plain English description
- `estimated_monthly_savings`: Dollar impact
- `status`: 'executed' or 'pending_approval'
- `executed_at`: Timestamp

### 4. Display on Pages
Both the **Decision Screen** and **AI Change Log** pages query this table:

```python
# Get recent AI actions (last 30 days)
recent_actions = AIAction.query.filter(
    AIAction.account_id == aid,
    AIAction.status == 'executed',
    AIAction.created_at >= thirty_days_ago
).order_by(AIAction.created_at.desc()).limit(100).all()
```

If the table is empty → shows 0s

---

## How to Populate AI Actions

### Option 1: Run the AI Agent (Automated)

The AI agent should run automatically via cron job:

```bash
# Check if it's scheduled
crontab -l | grep "run-agents"

# Manually trigger it
cd /home/fieldsprout
venv/bin/flask run-agents
```

This will:
1. Analyze your Google Ads data
2. Identify optimization opportunities
3. Create AI actions in the database
4. (Optionally) Execute approved actions

### Option 2: Create Sample Actions (For Testing)

If you want to see how the pages look with data, you can manually insert test actions:

```sql
-- Add a sample negative keyword action
INSERT INTO ai_actions (
    account_id,
    action_type,
    action_description,
    title,
    reasoning,
    estimated_monthly_savings,
    status,
    executed_at,
    created_at,
    is_undoable,
    confidence_score
) VALUES (
    1,  -- Your account ID
    'negative_keyword_added',
    'Blocked 12 irrelevant "how to" searches',
    'Blocked DIY Searches',
    'These searches indicate users looking for free information, not services',
    47.50,
    'executed',
    NOW() - INTERVAL 2 HOUR,
    NOW() - INTERVAL 2 HOUR,
    true,
    0.95
);

-- Add a budget reallocation action
INSERT INTO ai_actions (
    account_id,
    action_type,
    action_description,
    title,
    reasoning,
    estimated_monthly_savings,
    status,
    executed_at,
    created_at,
    is_undoable,
    confidence_score
) VALUES (
    1,  -- Your account ID
    'budget_adjusted',
    'Moved $150 from ZIP 94103 to high-converting ZIP 94110',
    'Budget Reallocation',
    'ZIP 94103 had 0 conversions with $150 spent. ZIP 94110 has 3.2% conversion rate',
    225.00,
    'executed',
    NOW() - INTERVAL 5 HOUR,
    NOW() - INTERVAL 5 HOUR,
    true,
    0.88
);

-- Add a keyword pause action
INSERT INTO ai_actions (
    account_id,
    action_type,
    action_description,
    title,
    reasoning,
    estimated_monthly_savings,
    status,
    executed_at,
    created_at,
    is_undoable,
    confidence_score
) VALUES (
    1,  -- Your account ID
    'keyword_paused',
    'Paused 3 underperforming broad match keywords',
    'Paused Low Performers',
    'Keywords spent $89 with 0 conversions over 30 days',
    89.00,
    'executed',
    NOW() - INTERVAL 1 DAY,
    NOW() - INTERVAL 1 DAY,
    true,
    0.92
);
```

After running this SQL, refresh the pages and you'll see:
- AI Change Log: 3 actions listed with savings
- Decision Screen: Timeline with recent changes
- Summary stats: Total saved, total actions, etc.

---

## Understanding "Waste" Detection

You asked: **"$0 waste doesn't seem accurate - we have keywords without proper intent"**

### How Waste is Currently Calculated

The system calculates waste by looking at:

1. **Search Terms** that triggered your ads but didn't convert
2. **Keywords** with high spend and zero conversions
3. **Irrelevant clicks** based on search query analysis

**Current logic in AI agent:**
```python
# Identify wasted spend on non-converting search terms
wasted_searches = search_terms_df[
    (search_terms_df['clicks'] > 0) &
    (search_terms_df['conversions'] == 0) &
    (search_terms_df['cost'] > threshold)
]
```

### Why You Might See $0:

1. **No data imported yet** - Search terms report not pulled from Google Ads
2. **Short time window** - Not enough data to identify patterns
3. **All keywords converting** - Unlikely but possible
4. **Threshold too high** - Waste detection might have minimum spend threshold

### How to Improve Waste Detection

**Option A: Lower the threshold**

Edit the AI agent config to detect smaller waste amounts:

```python
# In the AI agent code
WASTE_THRESHOLD = 10  # Flag keywords that spent >$10 with 0 conversions
LOW_QUALITY_CTR = 0.02  # Flag keywords with CTR < 2%
```

**Option B: Manual keyword review**

You can manually identify wasteful keywords:

```sql
-- Find keywords with spend but no conversions
SELECT
    keyword_text,
    SUM(cost) as total_spend,
    SUM(conversions) as total_conversions,
    SUM(clicks) as total_clicks
FROM keyword_performance
WHERE date >= DATE_SUB(NOW(), INTERVAL 30 DAY)
GROUP BY keyword_text
HAVING total_spend > 20 AND total_conversions = 0
ORDER BY total_spend DESC;
```

**Option C: Add keywords to your review**

Tell us specific keywords you think are wasteful, and we can:
1. Add them as negative keywords
2. Create AI action records for the change
3. Update the waste calculation to include them

---

## Why "No Recent Changes"?

The "What Changed?" timeline on the Decision Screen shows the last 10 AI actions from the database.

If it's empty, it means:
- AI agent hasn't run yet
- No actions were needed (account already optimized)
- AI actions exist but aren't marked as 'executed'

**To check:**

```sql
-- See ALL AI actions (including pending)
SELECT
    action_type,
    action_description,
    status,
    created_at
FROM ai_actions
WHERE account_id = 1
ORDER BY created_at DESC
LIMIT 20;
```

If this returns results but the page shows nothing, the actions might have `status != 'executed'`.

---

## Next Steps

### To Get Real AI Data:

1. **Ensure Google Ads is connected**
   - Go to `/account/google` and verify connection
   - Check that data is pulling (campaigns, keywords visible on `/ads/structure`)

2. **Run the AI agent manually**
   ```bash
   cd /home/fieldsprout
   venv/bin/flask run-agents --account-id=1
   ```

3. **Check for errors in logs**
   ```bash
   tail -f logs/app.log | grep -i "ai_action\|agent"
   ```

### To Add Test Data Now:

1. Run the sample SQL INSERT statements above
2. Refresh the Decision Screen and AI Change Log pages
3. You'll see populated data while waiting for real AI analysis

### To Improve Waste Detection:

1. Share examples of "keywords without proper intent"
2. We can add them as negative keywords manually
3. Configure AI agent to look for similar patterns
4. Lower detection thresholds if needed

---

## Summary

**Current State:**
- ✅ Pages are working correctly (pulling from database)
- ✅ Templates display data when it exists
- ❌ No AI actions in database yet

**Why:**
- AI agent hasn't analyzed your account yet
- Or hasn't found optimization opportunities
- Or hasn't been configured to run automatically

**Solution:**
- Run AI agent manually to get real analysis
- Or insert sample data to see how pages look
- Share specific wasteful keywords for manual review

The system is **ready** - it just needs the AI agent to populate the data!
