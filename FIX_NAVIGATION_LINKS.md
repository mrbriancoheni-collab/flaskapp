# Fix: AI Prompts and AI Agents Navigation Links Not Working

**Issue:** Clicking "System AI Prompts" and "AI Agents" in the admin navigation does nothing.

**Root Cause:** Missing database tables cause routes to fail and silently redirect to dashboard.

---

## The Problem

When you click these navigation links, Flask routes catch exceptions because required database tables don't exist:

1. **AI Prompts** → Looks for `ai_prompts` table
2. **AI Agents** → Looks for `agent_configurations` table

If these tables are missing, the routes catch the exception and redirect to the dashboard silently (making it appear that "nothing happens").

---

## Solution: Create Missing Database Tables

### Option 1: Run SQL Migration Files (Recommended)

**Step 1: Connect to your database**

Via cPanel → phpMyAdmin or MySQL command line:

```bash
mysql -u YOUR_USERNAME -p YOUR_DATABASE_NAME
```

**Step 2: Create ai_prompts table**

```sql
-- Run this entire block
CREATE TABLE IF NOT EXISTS `ai_prompts` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `prompt_key` VARCHAR(100) NOT NULL UNIQUE COMMENT 'Unique identifier for the prompt',
  `name` VARCHAR(200) NOT NULL COMMENT 'Display name for the prompt',
  `description` TEXT COMMENT 'Description of what this prompt does',
  `system_message` TEXT NOT NULL COMMENT 'System message for AI model',
  `prompt_template` TEXT NOT NULL COMMENT 'Prompt template with placeholders',
  `model` VARCHAR(50) NOT NULL DEFAULT 'gpt-4o-mini' COMMENT 'OpenAI model to use',
  `temperature` FLOAT NOT NULL DEFAULT 0.7 COMMENT 'Model temperature (0-1)',
  `max_tokens` INT NOT NULL DEFAULT 2000 COMMENT 'Maximum tokens for response',
  `is_active` BOOLEAN NOT NULL DEFAULT TRUE COMMENT 'Whether this prompt is active',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  INDEX `ix_ai_prompts_prompt_key` (`prompt_key`),
  INDEX `ix_ai_prompts_is_active` (`is_active`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Stores AI prompts for various optimization services';
```

**Step 3: Create agent_configurations table**

```sql
-- Run this entire block
CREATE TABLE IF NOT EXISTS agent_configurations (
    id INT AUTO_INCREMENT PRIMARY KEY,
    account_id INT DEFAULT NULL,
    agent_id VARCHAR(100) NOT NULL,
    agent_type VARCHAR(100) NOT NULL,
    enabled BOOLEAN DEFAULT TRUE,
    auto_execute_threshold DECIMAL(3,2) DEFAULT 0.95,
    custom_prompt TEXT DEFAULT NULL,
    risk_overrides JSON DEFAULT NULL,
    business_rules JSON DEFAULT NULL,
    run_frequency VARCHAR(50) DEFAULT 'default',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_by INT DEFAULT NULL,
    UNIQUE KEY unique_agent_account (agent_id, account_id),
    INDEX idx_account (account_id),
    INDEX idx_enabled (enabled),
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

**Step 4: Seed agent configurations with defaults**

```sql
-- Insert default configurations for all 8 agents
INSERT INTO agent_configurations (account_id, agent_id, agent_type, enabled, auto_execute_threshold, custom_prompt) VALUES
(NULL, 'strategic_director', 'StrategicDirectorAgent', TRUE, 0.85, NULL),
(NULL, 'campaign_manager', 'CampaignManagerAgent', TRUE, 0.90, NULL),
(NULL, 'budget_guardian', 'BudgetGuardianAgent', TRUE, 0.90, NULL),
(NULL, 'quality_score_agent', 'QualityScoreAgent', TRUE, 0.90, NULL),
(NULL, 'keyword_optimizer', 'KeywordOptimizerAgent', TRUE, 0.92, NULL),
(NULL, 'negative_keyword_agent', 'NegativeKeywordAgent', TRUE, 0.95, NULL),
(NULL, 'ad_copy_agent', 'AdCopyAgent', TRUE, 0.90, NULL),
(NULL, 'landing_page_analyst', 'LandingPageAnalystAgent', TRUE, 0.75, NULL);
```

**Step 5: Verify tables were created**

```sql
-- Check ai_prompts table
SELECT COUNT(*) FROM ai_prompts;
-- Should return 0 (empty table)

-- Check agent_configurations table
SELECT COUNT(*) FROM agent_configurations;
-- Should return 8 (one config per agent)

-- List all agent configs
SELECT agent_id, agent_type, enabled, auto_execute_threshold
FROM agent_configurations
WHERE account_id IS NULL
ORDER BY agent_id;
```

---

### Option 2: Use cPanel phpMyAdmin (GUI Method)

1. Log into cPanel
2. Open **phpMyAdmin**
3. Select your database (likely `fieljtgr_flaskapp` or similar)
4. Click the **SQL** tab at the top
5. Copy and paste the SQL from Step 2 above
6. Click **Go**
7. Repeat for Step 3 and Step 4

---

### Option 3: Use Existing Migration Files

If you have SSH access and know your database credentials:

```bash
cd /home/user/flaskapp

# For ai_prompts table
mysql -u YOUR_USERNAME -p YOUR_DATABASE < migrations_sql/010_add_ai_prompts_table.sql

# For agent_configurations table
mysql -u YOUR_USERNAME -p YOUR_DATABASE < flaskapp/migrations/create_agent_configurations_table.sql
```

---

## Testing the Fix

After creating the tables:

1. **Restart your Flask application:**
   - cPanel → Setup Python App → Stop App → Start App
   - OR: `touch /home/user/flaskapp/flaskapp/passenger_wsgi.py`

2. **Clear your browser cache:**
   - Ctrl+Shift+Delete (Windows/Linux)
   - Cmd+Shift+Delete (Mac)
   - Select "Cached images and files"

3. **Test navigation links:**
   - Click **System AI Prompts** → Should show empty prompt list with "Initialize Prompts" button
   - Click **AI Agents** → Should show 8 agent configurations

4. **Initialize AI Prompts (first time only):**
   - On the AI Prompts page, click "Initialize Missing Prompts"
   - This will populate the table with default prompts

---

## What Each Page Does

### AI Prompts Page (`/admin/ai-prompts`)

Manages system prompts for AI optimization:
- **google_ads_main** - Comprehensive Google Ads optimization prompt
- **ad_copy_generation** - Generates new ad copy
- **keyword_analysis** - Analyzes keyword performance
- **landing_page_analysis** - Reviews landing pages
- And more...

**Features:**
- Edit prompt templates dynamically without code changes
- Adjust temperature and model settings
- A/B test different prompt versions
- Version control for prompts

### AI Agents Page (`/admin/agents/configure`)

Configure the 8 AI agents that optimize your Google Ads:

**Strategic Layer:**
1. **Strategic Director** - Campaign-level strategy
2. **Campaign Manager** - Campaign structure and settings
3. **Budget Guardian** - Budget allocation and pacing

**Operational Layer:**
4. **Quality Score Agent** - Keyword and ad quality
5. **Keyword Optimizer** - Bid management and keyword expansion

**Tactical Layer:**
6. **Negative Keyword Agent** - Waste reduction
7. **Ad Copy Agent** - Ad creative optimization
8. **Landing Page Analyst** - Landing page recommendations

**Features:**
- Enable/disable agents per account
- Adjust auto-execute thresholds (0-1)
- Add custom business context
- Override risk levels
- Create IF/THEN business rules

---

## Troubleshooting

### Issue: Still doesn't work after creating tables

**Check 1: Verify tables exist**
```sql
SHOW TABLES LIKE 'ai_prompts';
SHOW TABLES LIKE 'agent_configurations';
```

**Check 2: Check table structure**
```sql
DESCRIBE ai_prompts;
DESCRIBE agent_configurations;
```

**Check 3: Restart application**
```bash
touch /home/user/flaskapp/flaskapp/passenger_wsgi.py
```

**Check 4: Check Flask logs**
- cPanel → Error Logs
- Look for Python errors related to ai_prompts or agent_configurations

### Issue: "Access Denied" or "Permission Error"

Make sure your database user has these permissions:
```sql
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX
ON YOUR_DATABASE.*
TO 'YOUR_USERNAME'@'localhost';
FLUSH PRIVILEGES;
```

### Issue: Foreign key constraint fails

The `agent_configurations` table references `accounts` table. Make sure the accounts table exists first:

```sql
SHOW TABLES LIKE 'accounts';
```

If it doesn't exist, you have bigger database issues and should restore from backup.

---

## Why This Happened

These tables were added in recent updates but the migration files were not run on your production database. The code assumes they exist, but without them:

1. User clicks "AI Prompts"
2. Route tries to query `AIPrompt.query.all()`
3. Table doesn't exist → Exception
4. Exception caught → Redirects to dashboard
5. User sees "nothing happens"

The fix ensures the tables exist so the routes can properly load the pages.

---

## Migration Files Reference

**AI Prompts:**
- File: `/home/user/flaskapp/migrations_sql/010_add_ai_prompts_table.sql`
- Purpose: Manage dynamic AI prompts for optimization
- Created: 2025-10-30

**Agent Configurations:**
- File: `/home/user/flaskapp/flaskapp/migrations/create_agent_configurations_table.sql`
- Purpose: Configure AI agent behavior and auto-execution
- Created: Recent (part of agent system)

---

## Summary

**Problem:** Missing database tables
**Solution:** Run SQL migrations to create tables
**Time:** ~5 minutes via phpMyAdmin
**Difficulty:** Easy (copy/paste SQL)

After fix:
- ✓ AI Prompts page accessible
- ✓ AI Agents configuration accessible
- ✓ Can manage system prompts
- ✓ Can configure agent behavior per account
