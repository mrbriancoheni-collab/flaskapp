# Email Sequence System - Follow-Up Emails

## Current State

Right now, all campaigns have **1 email sequence** (step 1 - "Auto Campaign"):
- Subject: "Quick question about {{company_name}}'s {{service_type}} services"
- Initial outreach email
- Sent to everyone who hasn't received step 1

## How It Works Now

The email blast system:
1. Finds all enriched contacts
2. Checks if they've received **sequence step 1**
3. If NOT, sends step 1 to them
4. Records that they received step 1
5. Next day, they won't get step 1 again (because they already received it)

**Key Feature:** The system can send **different emails** to the same person (step 1, then step 2, then step 3), but **never sends the same email twice** (step 1 twice).

---

## Adding Follow-Up Sequences

To create follow-up emails (step 2, step 3, etc.), you need to:

### Option 1: SQL Script

```sql
-- Example: Add step 2 (follow-up) for all campaigns

INSERT INTO email_sequences (campaign_id, step_number, name, subject, body_text, body_html, delay_days, is_active, created_at, updated_at)
SELECT
    id as campaign_id,
    2 as step_number,
    'Auto Campaign - Follow-Up' as name,
    'Following up: {{company_name}} marketing opportunities' as subject,
    'Hi {{decision_maker_name}},

I wanted to follow up on my previous email about helping {{company_name}} get more customers in {{location}}.

Many {{service_type}} businesses we work with see a 30-40% increase in qualified leads within the first 3 months.

Would you have 10 minutes this week for a quick call to discuss?

Best regards,
FieldSprout Team
https://fieldsprout.io

----
If you''d prefer not to receive these emails, please reply with "unsubscribe" and I''ll remove you from my list.' as body_text,
    'Hi {{decision_maker_name}},<br><br>I wanted to follow up on my previous email about helping {{company_name}} get more customers in {{location}}.<br><br>Many {{service_type}} businesses we work with see a 30-40% increase in qualified leads within the first 3 months.<br><br>Would you have 10 minutes this week for a quick call to discuss?<br><br>Best regards,<br>FieldSprout Team<br>https://fieldsprout.io<br><br>----<br>If you''d prefer not to receive these emails, please reply with "unsubscribe" and I''ll remove you from my list.' as body_html,
    3 as delay_days,  -- Wait 3 days after step 1
    1 as is_active,
    NOW() as created_at,
    NOW() as updated_at
FROM lead_campaigns
WHERE status = 'ready';
```

### Option 2: Python Script

```python
from app import create_app
from app.extensions import db
from app.models_leads import LeadCampaign, EmailSequence

app = create_app()

with app.app_context():
    # Get all active campaigns
    campaigns = LeadCampaign.query.filter_by(status='ready').all()

    for campaign in campaigns:
        # Check if step 2 already exists
        existing = EmailSequence.query.filter_by(
            campaign_id=campaign.id,
            step_number=2
        ).first()

        if not existing:
            # Create step 2
            step2 = EmailSequence(
                campaign_id=campaign.id,
                step_number=2,
                name="Auto Campaign - Follow-Up",
                subject="Following up: {{company_name}} marketing opportunities",
                body_text="""Hi {{decision_maker_name}},

I wanted to follow up on my previous email about helping {{company_name}} get more customers in {{location}}.

Many {{service_type}} businesses we work with see a 30-40% increase in qualified leads within the first 3 months.

Would you have 10 minutes this week for a quick call to discuss?

Best regards,
FieldSprout Team
https://fieldsprout.io

----
If you'd prefer not to receive these emails, please reply with "unsubscribe" and I'll remove you from my list.""",
                body_html="""Hi {{decision_maker_name}},<br><br>I wanted to follow up...""",
                delay_days=3,  # Wait 3 days after step 1
                is_active=True
            )
            db.session.add(step2)

    db.session.commit()
    print(f"Created step 2 for {len(campaigns)} campaigns")
```

---

## How to Send Follow-Up Sequences

### Manually Run Step 2

```bash
# This would send step 2 to everyone who HASN'T received step 2 yet
# (Even if they already got step 1)

# Currently the script only supports step 1, but we can easily add support for step 2
cd /home/user/flaskapp
bash run_email_blast.sh  # Currently sends step 1
```

### Schedule Step 2 Automation

To automatically send step 2 after step 1, you could:

**Option A: Add a second cron job**
```python
# In background_jobs.py, add another scheduled job
scheduler.add_job(
    func=send_sequence_step_2,
    trigger='cron',
    hour=16,  # 4 PM UTC (2 hours after step 1 blast)
    minute=0,
    id='send_sequence_step_2',
    replace_existing=True,
    kwargs={'app': app}
)
```

**Option B: Smart delay-based system**
Query for contacts who:
1. Received step 1 at least X days ago (based on delay_days)
2. Haven't received step 2 yet
3. Aren't unsubscribed

---

## Example Sequence Flow

### Day 1:
- Contact: john@plumber.com
- Action: Receives step 1 (initial outreach)
- Database: `lead_contact_emails` has record with `sequence_step=1`

### Day 4: (3 days later, based on delay_days)
- Contact: john@plumber.com
- Check: Has he received step 2? **No**
- Action: Send step 2 (follow-up)
- Database: `lead_contact_emails` now has 2 records (step 1 and step 2)

### Day 7: (3 days later)
- Contact: john@plumber.com
- Check: Has he received step 3? **No**
- Action: Send step 3 (final follow-up)
- Database: `lead_contact_emails` now has 3 records

### Day 8:
- Contact: john@plumber.com
- Check: Has he received step 1? **Yes** (skip)
- Check: Has he received step 2? **Yes** (skip)
- Check: Has he received step 3? **Yes** (skip)
- Action: **No more emails sent** (unless we create step 4)

---

## Template Variables

Available in all email templates:
- `{{company_name}}` - Lead's company name
- `{{decision_maker_name}}` - Contact's name
- `{{decision_maker_title}}` - Contact's title
- `{{service_type}}` - Campaign's service type (e.g., "plumbing")
- `{{location}}` - Campaign's location (e.g., "Nashville, TN")

---

## Best Practices

### Recommended Sequence Structure:

**Step 1 (Day 0):** Initial outreach
- Introduce yourself
- Mention their business
- Offer value proposition
- Soft CTA (e.g., "Would you be interested?")

**Step 2 (Day 3-7):** Follow-up
- Reference previous email
- Share social proof (results, testimonials)
- Stronger CTA (e.g., "10-minute call this week?")

**Step 3 (Day 7-14):** Final follow-up
- Last chance approach
- Direct value statement
- Very specific CTA (e.g., "Reply with your best time")

**Step 4 (Day 30+):** Breakup email (optional)
- "Haven't heard back, assuming not interested"
- Leave door open for future
- Often gets highest response rate

---

## Current Automation Schedule

- **10 AM UTC:** Main automation (scrape, enrich, email campaigns)
- **2 PM UTC:** Email blast for step 1 (sends to anyone who hasn't received step 1)

**To add step 2:**
- **4 PM UTC:** Email blast for step 2 (sends to anyone who hasn't received step 2)

**To add step 3:**
- **6 PM UTC:** Email blast for step 3 (sends to anyone who hasn't received step 3)

---

## Benefits of This System

✅ **Can re-email contacts** - Send step 1, then step 2, then step 3
✅ **No duplicate emails** - Never sends step 1 twice to same person
✅ **Respects unsubscribes** - Checks unsubscribe list on every send
✅ **Scalable** - Easy to add step 4, 5, 6, etc.
✅ **Gradual coverage** - Eventually reaches everyone with all steps
✅ **Clear tracking** - Can see exactly which steps each contact received

---

## Next Steps

1. **Create step 2 sequences** - Use SQL script above
2. **Test step 2 manually** - Modify run_email_blast.sh to support sequence_step parameter
3. **Schedule step 2 automation** - Add cron job for 4 PM UTC
4. **Monitor results** - Track open rates, replies, unsubscribes per step
5. **Optimize** - Adjust timing, messaging based on performance
