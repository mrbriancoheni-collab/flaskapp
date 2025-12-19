# Lead Automation Status Report

**Generated:** 2025-12-19
**Issue:** Lead automation not running - no scraping, enriching, or emailing of prospects

---

## Investigation Findings

### 1. Automation Has Never Run ✗

**File:** `/home/user/flaskapp/automation_state.json`
**Status:** EXISTS but shows no activity

```json
{
  "last_run": null,
  "campaigns_created": 0,
  "campaigns_scraped": 0,
  "leads_enriched": 0,
  "emails_sent": 0
}
```

**Conclusion:** The automation service has never executed since creation.

---

### 2. No Cron Job Configured ✗

**Checked:** `crontab -l`
**Result:** Command not available (typical on shared hosting)

**Expected cron job:**
```bash
0 9 * * * cd /home/user/flaskapp && python3 run_lead_automation.py >> logs/automation.log 2>&1
```

**Conclusion:** No scheduled automation exists. Must be configured via cPanel.

---

### 3. Email Reply Handler NOT Implemented ✗

**Searched for:**
- Mailgun webhook routes
- Brevo webhook routes
- Inbound email processing
- Email reply handlers

**Result:** No implementation found

**Missing features:**
- `/api/email/reply` webhook endpoint
- Inbound email parsing
- AI response generation for prospect replies
- Reply tracking in database

---

### 4. Conversation Alert System NOT Implemented ✗

**Searched for:**
- Notification system for ongoing conversations
- Alert mechanisms for prospect replies
- User notification preferences

**Result:** No implementation found

**Missing features:**
- Email notifications when prospects reply
- Dashboard alerts for active conversations
- Conversation tracking and threading

---

## Root Cause

The lead automation system is **fully built** but **never activated**. All the code exists:

✓ `LeadAutomationService` - Complete automation logic
✓ `run-lead-automation` CLI command - Functional
✓ Daily limits and state management - Implemented
✓ Scraping, enrichment, email sending - All coded

**What's missing:** Scheduled execution (cron job)

---

## Solution Options

### Option 1: cPanel Cron Job (Recommended)

Since `crontab` command is not available via SSH, you must configure the cron job through cPanel:

**Steps:**
1. Log into cPanel
2. Navigate to "Cron Jobs" or "Advanced" → "Cron Jobs"
3. Add a new cron job:
   - **Minute:** 0
   - **Hour:** 9
   - **Day:** *
   - **Month:** *
   - **Weekday:** *
   - **Command:** `cd /home/user/flaskapp && python3 run_lead_automation.py >> logs/automation.log 2>&1`

**Schedule:** Daily at 9:00 AM

**Note:** The exact Python path may vary. You might need:
- `python3 run_lead_automation.py`
- `/usr/bin/python3 run_lead_automation.py`
- Check cPanel's Python app configuration for the correct path

---

### Option 2: Manual Execution Script

I created `/home/user/flaskapp/run_lead_automation.py` which can be run directly:

```bash
cd /home/user/flaskapp
python3 run_lead_automation.py          # Run automation
python3 run_lead_automation.py --dry-run # Preview only
```

**Limitation:** Currently fails because Flask is not installed in system Python. The application uses Passenger's Python environment.

**Fix needed:** Update script to use Passenger's Python path (found in cPanel → Setup Python App)

---

### Option 3: Call via Passenger Python

Find the correct Python path from cPanel:
1. cPanel → Setup Python App → Your Flask app
2. Look for "Python Executable Path" (example: `/home/user/virtualenv/flaskapp/3.11/bin/python3`)
3. Use that path in cron job:

```bash
cd /home/user/flaskapp && /home/user/virtualenv/flaskapp/3.11/bin/python3 run_lead_automation.py >> logs/automation.log 2>&1
```

---

## Missing Features to Implement

### 1. Email Reply Webhook (HIGH PRIORITY)

**What:** Allow AI to respond to prospect email replies automatically

**Implementation needed:**
- Create webhook endpoint: `/api/email/mailgun-inbound` or `/api/email/brevo-webhook`
- Parse inbound emails
- Detect if it's a reply to an automated email
- Generate AI response using GPT-4 or Claude
- Send reply and log conversation
- Create `email_conversations` table for threading

**Mailgun setup:**
1. Configure Mailgun route to forward inbound emails to webhook
2. Route pattern: `match_recipient("replies@mg.fieldsprout.io")`
3. Action: `forward("https://fieldsprout.io/api/email/mailgun-inbound")`

**Brevo setup:**
1. Configure Brevo inbound email webhook
2. Point to: `https://fieldsprout.io/api/email/brevo-webhook`

---

### 2. Conversation Alert System (MEDIUM PRIORITY)

**What:** Notify you when prospects reply and conversations are ongoing

**Implementation needed:**
- Email notifications when prospect replies
- Dashboard widget showing active conversations
- Real-time notification badge
- Weekly digest of conversations

**Database tables:**
```sql
CREATE TABLE email_conversations (
    id INT AUTO_INCREMENT PRIMARY KEY,
    lead_contact_id INT,
    thread_id VARCHAR(255),
    last_reply_at DATETIME,
    total_messages INT DEFAULT 0,
    ai_handled BOOLEAN DEFAULT FALSE,
    requires_human BOOLEAN DEFAULT FALSE,
    status ENUM('active', 'closed', 'escalated'),
    FOREIGN KEY (lead_contact_id) REFERENCES lead_contacts(id)
);

CREATE TABLE email_conversation_messages (
    id INT AUTO_INCREMENT PRIMARY KEY,
    conversation_id INT,
    direction ENUM('inbound', 'outbound'),
    from_email VARCHAR(255),
    to_email VARCHAR(255),
    subject TEXT,
    body_text TEXT,
    body_html LONGTEXT,
    is_ai_generated BOOLEAN DEFAULT FALSE,
    received_at DATETIME,
    FOREIGN KEY (conversation_id) REFERENCES email_conversations(id)
);
```

---

## Immediate Next Steps

### Step 1: Set Up Cron Job
1. Log into cPanel
2. Find the Python executable path for your Flask app
3. Configure cron job (see Option 1 or Option 3 above)
4. Test by checking `/home/user/flaskapp/logs/automation.log` after it runs

### Step 2: Verify Automation Works
After setting up cron, wait for it to run (or trigger manually), then check:

```bash
# Check if automation ran
cat /home/user/flaskapp/automation_state.json

# Should show:
# "last_run": "2025-12-19T09:00:00",
# "campaigns_created": > 0,
# etc.

# Check logs
tail -f /home/user/flaskapp/logs/automation.log
```

### Step 3: Implement Email Reply Handler (Next Session)
This requires new code - see "Missing Features" section above.

### Step 4: Implement Alert System (Next Session)
This requires new code - see "Missing Features" section above.

---

## Testing Checklist

Before considering automation "working", verify:

- [ ] Cron job configured in cPanel
- [ ] `automation_state.json` shows `last_run` with recent timestamp
- [ ] Campaigns being created (check database or admin page)
- [ ] Leads being scraped from Google (check `leads` table)
- [ ] Contacts being enriched (check `lead_contacts` table)
- [ ] Emails being sent (check `lead_contact_emails` table)
- [ ] Daily limits being respected (50 scrapes, 100 enrichments, 250 emails)
- [ ] Automation logs showing activity
- [ ] Sunday email skip working
- [ ] No errors in logs

---

## Daily Automation Behavior

Once configured, the automation will run daily at 9:00 AM and:

1. **Create & Scrape Campaigns** (up to 50/day)
   - Scrapes Google Ads, Maps, LSA, and Organic results
   - Saves leads with website, phone, address
   - Skips duplicate domains

2. **Enrich Leads** (up to 100/day)
   - Finds decision makers (CEO, President, Owner, Marketing Director)
   - Discovers email addresses
   - Saves contact information

3. **Send Emails** (up to 250/day)
   - Sends personalized outreach emails
   - Uses email sequence templates
   - Skips Sundays automatically
   - Tracks delivery status

4. **Save State**
   - Updates `automation_state.json`
   - Resumes from where it stopped
   - Tracks daily limits

---

## Environment Variables Required

Make sure these are set in cPanel → Setup Python App → Environment Variables:

```bash
# Required for scraping
SERPAPI_API_KEY=your_serpapi_key

# Required for email sending (choose one)
MAILGUN_API_KEY=your_mailgun_key
MAILGUN_DOMAIN=mg.fieldsprout.io

# OR
BREVO_API_KEY=your_brevo_key
BREVO_FROM_EMAIL=noreply@fieldsprout.io

# Database (should already be set)
SQLALCHEMY_DATABASE_URI=mysql+pymysql://user:pass@host/database
```

---

## Support Resources

**Automation status page:**
https://fieldsprout.io/admin/lead-campaigns/automation-status

**Lead campaigns dashboard:**
https://fieldsprout.io/admin/lead-campaigns/

**Activity feed:**
https://fieldsprout.io/admin/activity/

**Documentation:**
`/home/user/flaskapp/AUTOMATION_CRON.md`

---

## Summary

**Problem:** Automation never set up - no cron job exists
**Solution:** Configure cron job in cPanel (see Option 1 or 3)
**Missing:** Email reply handler and conversation alerts (need new code)
**Status:** All automation code exists and is ready to run once scheduled
