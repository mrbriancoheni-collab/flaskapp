# Email Sequence System - Smart Delay-Based Sequencing

## 🎯 NEW: Automated Multi-Step Email Campaigns

The system now automatically progresses contacts through your 6-step "Auto Campaign" email sequence!

### How It Works

**Every day at 2 PM UTC**, the system:
1. Checks all enriched contacts
2. Finds which sequence steps they've already received
3. Determines the next step they need
4. Checks if enough `delay_days` have passed since their last email
5. Sends the next step if they're ready

**Example Flow:**
- **Day 1**: Contact receives **Step 1** (initial outreach)
- **Day 4** (3 days later): Contact receives **Step 2** (follow-up)
- **Day 9** (5 days later): Contact receives **Step 3** (second follow-up)
- ...and so on through all 6 steps

---

## Current "Auto Campaign" Sequence

Your campaigns already have a 6-email sequence titled **"Auto Campaign"**.

The system will automatically send all 6 steps based on the `delay_days` configured for each step:

```
Step 1 → wait X days → Step 2 → wait Y days → Step 3 → ... → Step 6
```

---

## No Manual Setup Required!

✅ **The system is ready to use your existing 6-step sequence**
✅ **Automated progression** - contacts move through steps automatically
✅ **Respects delays** - won't send next step until `delay_days` have passed
✅ **Respects unsubscribes** - checks before every send
✅ **Daily limit** - sends up to 250 emails per day

---

## How to Run

### Option 1: Automated (Recommended)
The system runs automatically every day at **2 PM UTC**. No action needed!

### Option 2: Manual Run
```bash
# Smart sequencing (sends next step for each contact)
bash run_email_blast.sh

# Send specific step only (advanced)
bash run_email_blast.sh 1  # Send step 1 to all who haven't received it
bash run_email_blast.sh 2  # Send step 2 to all who haven't received it
```

---

## Understanding the Smart Sequencing Logic

### For Each Contact:

1. **Check what they've received**
   - Query `lead_contact_emails` table for sequence steps already sent
   - Example: Contact has received steps 1, 2, 3

2. **Find next step**
   - Look at campaign's `email_sequences` ordered by `step_number`
   - Find first step they haven't received
   - Example: Next step is 4

3. **Check delay requirement**
   - Get `delay_days` from step 4 configuration
   - Calculate days since last email
   - Example: Step 4 requires 7 days, last email was 5 days ago → NOT READY

4. **Send if ready**
   - If delay requirement met, send step 4
   - Record in `lead_contact_emails` with `sequence_step = 4`
   - Move to next contact

### Contact States:

- **Never emailed**: Receives step 1 immediately
- **In sequence**: Waits for `delay_days`, then receives next step
- **Completed**: Received all 6 steps, no more emails
- **Unsubscribed**: Skipped entirely

---

## Template Variables

Available in all email templates:
- `{{company_name}}` - Lead's company name
- `{{decision_maker_name}}` - Contact's name
- `{{decision_maker_title}}` - Contact's title
- `{{service_type}}` - Campaign's service type (e.g., "plumbing")
- `{{location}}` - Campaign's location (e.g., "Nashville, TN")

---

## Monitoring & Logs

### Check Daily Run Status
```bash
tail -f logs/email_blast.log
```

### Manual Test Run
```bash
bash run_email_blast.sh
```

You'll see output like:
```
SMART SEQUENCE PROGRESSION
Automatically sends next step based on delay_days configuration
================================================================================

Campaign 123: 6 active sequence steps, 150 contacts
Sending step 2 to john@example.com (campaign: 123, delay: 3 days)
Sending step 3 to jane@example.com (campaign: 123, delay: 5 days)
Sending step 1 to new@example.com (campaign: 123, delay: 0 days)

COMPLETE:
  - Emails sent: 3
  - Total contacts checked: 150
  - Skipped (unsubscribed): 2
  - Skipped (not ready/delay pending): 100
  - Skipped (completed all steps): 45
```

---

## Editing Your Sequence

### Via Admin Interface
1. Go to **Lead Campaigns** → **Email Sequences**
2. Find your campaign's sequences
3. Edit any step:
   - Subject line
   - Email body
   - `delay_days` (how long to wait after previous email)
   - `is_active` (turn step on/off)

### Common Changes

**Adjust timing:**
```sql
-- Make step 2 send after 5 days instead of 3
UPDATE email_sequences
SET delay_days = 5
WHERE campaign_id = 123 AND step_number = 2;
```

**Update subject line:**
```sql
UPDATE email_sequences
SET subject = 'New subject line here'
WHERE campaign_id = 123 AND step_number = 3;
```

**Disable a step:**
```sql
UPDATE email_sequences
SET is_active = 0
WHERE campaign_id = 123 AND step_number = 4;
```

---

## Best Practices

### Recommended Timing:

**Step 1 (Day 0):** Initial outreach
- `delay_days = 0` (send immediately)
- Introduce yourself, mention their business
- Soft CTA

**Step 2 (Day 3-7):** Follow-up
- `delay_days = 3-7`
- Reference previous email
- Share social proof
- Stronger CTA

**Step 3 (Day 7-14):** Second follow-up
- `delay_days = 5-7` (from step 2)
- Case study or specific results
- Direct value statement

**Step 4 (Day 14-21):** Different angle
- `delay_days = 7`
- Try different pain point
- Alternative offer

**Step 5 (Day 21-30):** Last value email
- `delay_days = 7-9`
- Best resources or tips
- Very specific CTA

**Step 6 (Day 30+):** Breakup email
- `delay_days = 10+`
- "Haven't heard back, assuming not interested"
- Leave door open
- Often gets highest response rate!

---

## Database Tables

### email_sequences
Stores the 6 email templates:
```sql
CREATE TABLE email_sequences (
    id INT PRIMARY KEY,
    campaign_id INT,
    step_number INT,        -- 1, 2, 3, 4, 5, 6
    name VARCHAR,           -- "Auto Campaign"
    subject TEXT,
    body_text TEXT,
    body_html TEXT,
    delay_days INT,         -- Days to wait after previous step
    is_active BOOLEAN
);
```

### lead_contact_emails
Tracks which steps each contact received:
```sql
CREATE TABLE lead_contact_emails (
    id INT PRIMARY KEY,
    to_email VARCHAR,
    sequence_step INT,      -- Which step was sent (1-6)
    sent_at DATETIME,
    status VARCHAR
);
```

### email_unsubscribes
Contacts who opted out:
```sql
CREATE TABLE email_unsubscribes (
    id INT PRIMARY KEY,
    email VARCHAR UNIQUE,
    reason TEXT,
    created_at DATETIME
);
```

---

## Troubleshooting

### "No emails being sent"

Check:
1. **Daily limit**: Already sent 250 emails today?
   ```bash
   grep "COMPLETE" logs/email_blast.log | tail -1
   ```

2. **Contacts not ready**: Check delay_days requirements
   ```sql
   SELECT * FROM email_sequences WHERE campaign_id = 123 ORDER BY step_number;
   ```

3. **All completed**: Contacts already received all 6 steps
   ```sql
   SELECT to_email, COUNT(*) as steps_received
   FROM lead_contact_emails
   GROUP BY to_email
   HAVING steps_received >= 6;
   ```

### "Step X not sending"

Check if step is active:
```sql
SELECT * FROM email_sequences
WHERE campaign_id = 123 AND step_number = X;
```

Make sure `is_active = 1`

### "Delay not working"

The `delay_days` is calculated from the **last email sent**, not from step 1.

Example:
- Step 2 has `delay_days = 3`
- Contact received step 1 on Day 0
- Contact will receive step 2 on Day 3 (3 days after Day 0)

---

## Benefits of Smart Sequencing

✅ **Automatic progression** - No need to manually schedule 6 separate jobs
✅ **Flexible timing** - Adjust `delay_days` per step
✅ **Respects contact state** - Tracks exactly where each contact is
✅ **No duplicates** - Never sends same step twice
✅ **Unsubscribe compliance** - Checks before every send
✅ **Scalable** - Works with unlimited campaigns and contacts
✅ **Daily limit aware** - Never exceeds 250 emails/day

---

## Migration from Old System

If you were previously sending only step 1:

**Before:**
- System sent step 1 to everyone who hadn't received it
- Follow-ups required manual SQL or separate cron jobs

**After:**
- System automatically sends step 1, then step 2, then step 3, etc.
- All 6 steps handled by single daily job
- Timing controlled by `delay_days` in `email_sequences` table

**No action needed!** The smart sequencing system is backwards compatible and will:
1. Continue sending step 1 to new contacts
2. Start sending step 2+ to existing contacts based on delays
3. Respect all existing `lead_contact_emails` records

---

## Current Automation Schedule

- **10 AM UTC**: Main automation (scrape, enrich, create campaigns)
- **2 PM UTC**: Smart email sequencing (sends next step for all contacts)

One job handles all 6 steps! 🎉

---

## Summary

You don't need to do anything! The system now automatically:
1. Uses your existing 6-step "Auto Campaign" sequence
2. Sends step 1 to new contacts
3. Waits for `delay_days` to pass
4. Sends step 2, 3, 4, 5, 6 automatically
5. Respects unsubscribes and daily limits
6. Tracks everything in the database

Just sit back and let the system nurture your leads through all 6 touchpoints! 📧✨
