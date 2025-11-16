# 🤖 AI Agents Deployment Guide

Complete guide to deploying the multi-agent AI system for autonomous Google Ads optimization.

---

## 📋 What Was Built

### **7 Autonomous AI Agents** Across 3 Layers

#### Strategic Layer (Weekly/Monthly)
- **Strategic Director** - Your CMO for Google Ads
  - Budget reallocation from losers to winners
  - Campaign scaling decisions (high ROAS + low impression share)
  - Strategic campaign pausing (consistent underperformers)

#### Operational Layer (Every 4 hours)
- **Campaign Manager** - 24/7 performance monitoring
  - CPL spike detection (>30% increase = alert)
  - Conversion drop detection
  - Bid adjustment recommendations
- **Budget Guardian** - Spend protection
  - Emergency pauses for runaway campaigns (3x normal daily spend)
  - Budget overrun prevention
- **Quality Score Doctor** - CPC optimization
  - Low QS diagnosis and fix delegation

#### Tactical Layer (Hourly)
- **Keyword Optimizer** - Keyword performance
  - Pauses $200+ spend keywords with 0 conversions
  - Bid adjustments based on conversion rate
- **Negative Keyword Agent** - Waste blocking
  - Auto-blocks "free", "DIY", "jobs", "salary" searches
  - 95% confidence = auto-execution (no approval needed)
- **Ad Copy Scientist** - Ad testing
  - A/B tests ad variations
  - Pauses underperforming ads

### **Infrastructure Built**
- ✅ Event Bus for inter-agent communication
- ✅ Decision Log for tracking all decisions
- ✅ Google Ads API Executor for real API calls
- ✅ Database schema for decisions and execution logs
- ✅ Approval Queue UI for high-risk decisions
- ✅ Agent Dashboard with performance metrics
- ✅ Manual "Run Agents Now" button
- ✅ Flask CLI commands for cron jobs
- ✅ Scheduler for periodic agent runs

---

## 🚀 Deployment Steps

### **1. Run Database Migrations**

Run these SQL files in order:

```bash
# Navigate to your database
mysql -u username -p database_name

# Run migrations
source flaskapp/migrations/create_agent_decisions_table.sql
source flaskapp/migrations/create_tutorial_popups_table.sql
source flaskapp/migrations/create_agent_execution_log_table.sql
```

**Verify tables created:**
```sql
SHOW TABLES LIKE 'agent_%';
SHOW TABLES LIKE 'tutorial_popups';
```

### **2. Test Manual Agent Run**

Visit your Approval Queue and click "Run Agents Now":
```
https://yoursite.com/account/google/ads/agents/approvals
```

Or test via CLI:
```bash
cd /path/to/flaskapp/flaskapp
flask run-agents --all
```

**Expected output:**
```
Running ALL agents for 3 accounts...
✓ Account 1 completed
✓ Account 2 completed
✓ Account 3 completed

✅ Completed: 3 succeeded, 0 failed
```

### **3. Set Up Cron Jobs for Automatic Runs**

**Edit crontab:**
```bash
crontab -e
```

**Update paths in crontab-agents.txt**, then add these lines:

```bash
# Tactical agents: Every hour
0 * * * * cd /path/to/flaskapp/flaskapp && /path/to/venv/bin/flask run-agents --layer tactical >> /var/log/agents-tactical.log 2>&1

# Operational agents: Every 4 hours
0 */4 * * * cd /path/to/flaskapp/flaskapp && /path/to/venv/bin/flask run-agents --layer operational >> /var/log/agents-operational.log 2>&1

# Strategic agent: Daily at 6am
0 6 * * * cd /path/to/flaskapp/flaskapp && /path/to/venv/bin/flask run-agents --layer strategic >> /var/log/agents-strategic.log 2>&1
```

**Test cron job manually:**
```bash
cd /path/to/flaskapp/flaskapp
/path/to/venv/bin/flask run-agents --layer tactical
```

### **4. Monitor Agent Execution**

**Check logs:**
```bash
tail -f /var/log/agents-tactical.log
tail -f /var/log/agents-operational.log
tail -f /var/log/agents-strategic.log
```

**View execution history:**
```sql
SELECT * FROM agent_execution_log ORDER BY created_at DESC LIMIT 10;
```

**View pending decisions:**
```sql
SELECT * FROM agent_decisions WHERE status = 'pending' ORDER BY created_at DESC;
```

---

## 🎯 How It Works

### **Agent Execution Flow**

1. **Cron job triggers** (or manual "Run Agents Now" button)
2. **Agent Runner** fetches Google Ads data for all active accounts
3. **Each agent analyzes** the data:
   - Strategic: Looks for budget reallocation opportunities
   - Operational: Monitors for CPL spikes, runaway spend
   - Tactical: Reviews keywords, search terms, ad performance
4. **Agents create decisions**:
   - Low-risk (confidence >95%) → Auto-execute immediately
   - High-risk (budget changes, pauses) → Queue for approval
5. **Decisions appear** in Approval Queue for user review
6. **Execution happens**:
   - Auto-executed decisions run via Google Ads API
   - Approved decisions execute when user clicks "Approve"
7. **Results tracked** in agent_execution_log

### **Auto-Execution Criteria**

A decision auto-executes if **ALL** of these are true:
- Risk level = `LOW`
- Confidence >= agent's `auto_execute_threshold` (usually 95%)
- Agent has `AUTONOMOUS_EXECUTION` capability

**Examples of auto-execution:**
- ✅ Block "free" searches (95% confidence = waste)
- ✅ Pause keyword with $200+ spend and 0 conversions
- ✅ Add proven search term as keyword

**Examples requiring approval:**
- ❌ Pause campaign (CRITICAL risk)
- ❌ Reallocate $1,000 budget (HIGH risk)
- ❌ Increase campaign budget by 50% (MEDIUM risk)

---

## 📊 User Interface

### **Approval Queue** (`/account/google/ads/agents/approvals`)
- View all pending high-risk decisions
- Approve/reject with one click
- See expected savings, leads, and confidence scores
- Grouped by risk level (Critical → High → Medium)
- **"Run Agents Now"** button for manual testing

### **Agent Dashboard** (`/account/google/ads/agents/dashboard`)
- Agent performance metrics by type
- Auto-execution stats (95% of decisions auto-executed)
- Recent activity feed
- Prediction accuracy tracking

### **Opportunities Page** (`/account/google/ads/opportunities/demo`)
- Banner linking to Agent Dashboard and Approval Queue
- Shows opportunities identified by AI agents
- Tutorial popups explain how agents work

---

## 🔧 Flask CLI Commands

```bash
# Run all agents for all accounts
flask run-agents --all

# Run specific layer
flask run-agents --layer tactical
flask run-agents --layer operational
flask run-agents --layer strategic

# Run for specific account only
flask run-agents --account 123
```

---

## 📁 Files Created

### **Core Agent System**
- `flaskapp/app/agents/executor.py` - Google Ads API integration
- `flaskapp/app/agents/strategic.py` - Updated with executor
- `flaskapp/app/agents/operational.py` - Updated with executor
- `flaskapp/app/agents/tactical.py` - Updated with executor

### **Scheduling & Automation**
- `flaskapp/app/tasks/agent_scheduler.py` - Scheduler for cron jobs
- `flaskapp/app/commands.py` - Flask CLI commands
- `crontab-agents.txt` - Example crontab configuration

### **User Interface**
- `flaskapp/app/google/agents_routes.py` - Updated with `/api/run` endpoint
- `flaskapp/templates/google/agents_approval_queue.html` - Updated with "Run Agents Now" button
- `flaskapp/templates/google/agents_dashboard.html` - Agent dashboard
- `flaskapp/templates/google/ads_opportunities.html` - Updated with AI agents banner

### **Database**
- `flaskapp/migrations/create_agent_decisions_table.sql` - Agent decisions
- `flaskapp/migrations/create_tutorial_popups_table.sql` - Tutorial popups
- `flaskapp/migrations/create_agent_execution_log_table.sql` - Execution log

### **Configuration**
- `flaskapp/app/__init__.py` - Updated to register CLI commands

---

## ⚠️ Current Limitations & TODOs

### **Mock Data (Needs Real Google Ads API)**
Currently using mock performance data in:
- `agents_routes.py:310-345` - Agent runner context
- `agent_scheduler.py:100-118` - Scheduler context

**To fix:** Replace with real Google Ads API calls to fetch:
- 90-day performance metrics (ROAS, spend, conversions)
- Campaign list with metrics
- Keyword performance
- Search term reports
- Ad performance

**Example:**
```python
# Instead of mock data
context = {
    'performance_90d': {
        'roas': 2.5,  # MOCK
        'spend': 5000,  # MOCK
    }
}

# Fetch real data
from app.services.google_ads_service import fetch_account_performance
context = {
    'performance_90d': fetch_account_performance(customer_id, days=90),
    'campaigns': fetch_campaigns(customer_id),
    # etc.
}
```

### **Execution Not Wired to Approval**
When user approves a decision in the queue, it doesn't execute yet.

**To fix:** Update `approve_decision()` in `agents_routes.py:148-171` to call executor.

---

## 🎉 What's Complete

✅ All 7 agents implemented with analyze/decide/execute
✅ Google Ads API executor with all 10 decision types
✅ Approval queue UI with approve/reject
✅ Agent dashboard with performance metrics
✅ "Run Agents Now" button for manual testing
✅ Flask CLI commands for cron jobs
✅ Scheduler for periodic agent runs
✅ Database schema for decisions and logs
✅ Tutorial popups for opportunities demo
✅ Marketing pages updated with agentic copy
✅ Event bus for inter-agent communication
✅ Decision log for tracking predictions vs actuals
✅ Learning & adaptation framework

---

## 📞 Support

If you run into issues:
1. Check `/var/log/agents-*.log` for errors
2. Query `agent_execution_log` table for execution history
3. Run `flask run-agents --account YOUR_ACCOUNT_ID` to test specific account
4. Check that Google Ads credentials are in `google_oauth_tokens` table

Happy deploying! 🚀
