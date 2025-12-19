# AI Auto-Response System Setup Guide

**Feature:** Automatically respond to prospect email replies with intelligent, context-aware AI responses.

**What it does:**
- 🤖 AI analyzes prospect replies for sentiment and intent
- ✉️ Generates personalized responses automatically
- 🚨 Escalates to human when needed
- 📊 Tracks conversations and creates alerts
- 💬 Shows conversation threads in admin dashboard

---

## Prerequisites

✅ You already have these:
- Brevo API connection (for sending emails)
- OpenAI API key (for AI response generation)
- Environment variables configured

---

## Setup Steps

### Step 1: Run Database Migration (5 minutes)

Create the conversation tracking tables:

**Option A: Via SSH**
```bash
cd /home/fieljtgr/flaskapp
mysql -u YOUR_USERNAME -p YOUR_DATABASE < migrations_sql/011_add_conversation_tracking.sql
```

**Option B: Via cPanel → phpMyAdmin**
1. Open phpMyAdmin
2. Select your database
3. Click "SQL" tab
4. Copy/paste contents of `migrations_sql/011_add_conversation_tracking.sql`
5. Click "Go"

**What this creates:**
- `email_conversations` - Track conversation threads
- `email_conversation_messages` - Store all messages
- `conversation_alerts` - Dashboard notifications

**Verify:**
```sql
SELECT COUNT(*) FROM email_conversations;
SELECT COUNT(*) FROM email_conversation_messages;
SELECT COUNT(*) FROM conversation_alerts;
-- All should return 0 (tables exist but empty)
```

---

### Step 2: Configure Brevo Webhook (10 minutes)

**Why needed:** This tells Brevo to notify your app when prospects reply

1. **Log into Brevo Dashboard:** https://app.brevo.com
2. **Navigate to:** Settings → Transactional → Webhooks
3. **Click:** "Add a new webhook"
4. **Configure:**
   - **URL:** `https://fieldsprout.io/api/email/brevo-webhook`
   - **Events:** Check "Inbound Email"
   - **Description:** "AI Auto-Response for FieldSprout"
5. **Save**

**Test webhook:**
```bash
curl https://fieldsprout.io/api/email/test

# Should return:
# {"status":"ok","message":"Email webhook endpoint is working","endpoints":{...}}
```

---

### Step 3: Configure Brevo Inbound Email Domain (5 minutes)

**Why needed:** Brevo needs to know where to route inbound emails

1. **In Brevo Dashboard:** Settings → Transactional → Inbound parsing
2. **Add domain:** `replies.fieldsprout.io` (or subdomain of your choice)
3. **Configure MX records** in your DNS (Brevo will show you the records)
4. **Set forward-to address:** Use your webhook URL

**Alternative (simpler):** Use Brevo's provided inbound email address like `inbound@in.brevo.com` and configure it to call your webhook.

---

### Step 4: Restart Flask Application

```bash
# Via cPanel
# Go to: Setup Python App → Stop → Start

# Or via SSH
cd /home/fieljtgr/flaskapp
touch flaskapp/passenger_wsgi.py

# Or
passenger-config restart-app /home/fieljtgr/flaskapp
```

---

### Step 5: Verify Setup

**Check logs:**
```bash
# Check if blueprints registered
tail -100 /home/fieljtgr/flaskapp/logs/error.log | grep -i "webhook\|conversation"

# Should see:
# email_webhook_bp registered at /api/email
# conversations_bp registered at /admin/conversations
```

**Test webhook endpoint:**
```bash
curl https://fieldsprout.io/api/email/test
```

**Check admin dashboard:**
- Visit: https://fieldsprout.io/admin/conversations
- Should load without errors (empty list initially)

---

## How It Works

### Inbound Email Flow

```
1. Prospect replies to your automated email
   ↓
2. Brevo receives the reply at replies@mg.fieldsprout.io
   ↓
3. Brevo calls webhook: POST /api/email/brevo-webhook
   ↓
4. Webhook parses email (from, to, subject, body)
   ↓
5. AIConversationService.process_inbound_reply()
   ↓
6. AI analyzes sentiment (positive/negative/interested)
   ↓
7. Decides: Auto-respond OR Escalate to human
   ↓
8. If auto-respond:
   - OpenAI generates contextual response
   - Brevo sends reply
   - Creates "info" alert
   ↓
9. If escalate:
   - Marks conversation as "requires_human"
   - Creates "urgent" alert
   - No AI response sent
```

### AI Decision Making

**AI will auto-respond when:**
- ✅ Sentiment is positive, neutral, or interested
- ✅ Prospect asks questions about your service
- ✅ Conversation has < 10 total messages
- ✅ No explicit request for human

**AI will escalate to human when:**
- ❌ Sentiment is negative
- ❌ Urgency level is "critical"
- ❌ Prospect asks for "human", "person", "manager"
- ❌ Conversation has 10+ back-and-forths
- ❌ AI confidence is low

---

## Using the Dashboard

### View All Conversations

**URL:** https://fieldsprout.io/admin/conversations

**Features:**
- See all prospect conversations
- Filter by status (active, closed, escalated)
- Filter by sentiment (positive, negative, interested)
- Filter by requires human (yes/no)
- Click to view full thread

### View Conversation Thread

**URL:** https://fieldsprout.io/admin/conversations/<id>

**Shows:**
- Full conversation history
- All messages (inbound and outbound)
- AI-generated responses (marked with 🤖)
- Sentiment for each message
- When conversation was created
- Total messages count

**Actions:**
- Escalate to human (stops AI auto-response)
- Close conversation
- View related lead/contact

### View Alerts

**URL:** https://fieldsprout.io/admin/conversations/alerts

**Alert Types:**
- 🔵 **new_reply** - Prospect replied, AI responded (info)
- 🟡 **interested** - Prospect shows interest (warning)
- 🟠 **question** - Prospect asked question (warning)
- 🔴 **needs_human** - AI escalated to human (urgent)
- 🔴 **negative** - Negative sentiment detected (urgent)

**Features:**
- Badge with unread count
- Filter by severity (info, warning, urgent)
- Mark as read
- Mark all as read
- Direct link to conversation

---

## Email Configuration

### Set Reply-To Address

Update your outbound email templates to include proper Reply-To header:

```python
# In brevo_outreach.py or mailgun_outreach.py
headers = {
    'Reply-To': 'replies@fieldsprout.io',  # or your inbound email
    'X-Conversation-ID': f'conv-{lead_contact.id}'  # for tracking
}
```

### Email Template Best Practices

**Include in signature:**
```
---
The FieldSprout Team
hi@fieldsprout.io

Reply to this email with any questions!
```

**Clear call-to-action:**
- "Reply 'YES' if you're interested"
- "Let me know if you have questions"
- "Would you like to schedule a quick call?"

---

## Testing

### Test AI Response Generation

1. **Send test email:**
   - From your personal email
   - To: replies@fieldsprout.io
   - Subject: Re: Your FieldSprout Quote
   - Body: "Yes, I'm interested! Can you tell me more?"

2. **Check webhook received it:**
```bash
tail -f /home/fieljtgr/flaskapp/logs/error.log | grep -i "brevo webhook"
```

3. **Verify AI responded:**
   - Check your personal email for AI reply
   - Visit /admin/conversations to see thread
   - Check /admin/conversations/alerts for "new_reply" alert

4. **Test escalation:**
   - Send email: "This is terrible, I want to speak to a manager!"
   - Should see "urgent" alert
   - Should NOT receive AI response (escalated)

---

## Monitoring

### Check Webhook Activity

```bash
# View webhook logs
tail -100 /home/fieljtgr/flaskapp/logs/error.log | grep "webhook"

# Check for errors
grep -i "error.*conversation" /home/fieljtgr/flaskapp/logs/error.log | tail -20
```

### Conversation Statistics

**Dashboard widget endpoint:**
```bash
curl https://fieldsprout.io/admin/conversations/stats

# Returns:
# {
#   "total_conversations_7d": 25,
#   "ai_responses_7d": 20,
#   "escalated_7d": 5,
#   "unread_alerts": 3,
#   "positive_sentiment_7d": 15,
#   "interested_7d": 10
# }
```

### Database Queries

```sql
-- Recent conversations
SELECT
    c.id,
    c.status,
    c.last_sentiment,
    c.total_messages,
    c.ai_messages,
    c.requires_human,
    lc.email,
    l.company_name
FROM email_conversations c
JOIN lead_contacts lc ON c.lead_contact_id = lc.id
LEFT JOIN leads l ON lc.lead_id = l.id
ORDER BY c.last_message_at DESC
LIMIT 10;

-- Unread alerts
SELECT
    a.alert_type,
    a.severity,
    a.message,
    a.created_at,
    c.id as conversation_id
FROM conversation_alerts a
JOIN email_conversations c ON a.conversation_id = c.id
WHERE a.is_read = FALSE
ORDER BY a.created_at DESC;

-- AI response rate
SELECT
    COUNT(*) as total_conversations,
    SUM(CASE WHEN ai_messages > 0 THEN 1 ELSE 0 END) as ai_responded,
    SUM(CASE WHEN requires_human THEN 1 ELSE 0 END) as escalated,
    ROUND(AVG(ai_messages), 1) as avg_ai_messages_per_conv
FROM email_conversations
WHERE created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY);
```

---

## Troubleshooting

### Issue: Webhook not receiving emails

**Check:**
1. Brevo webhook is configured correctly
2. URL is https://fieldsprout.io/api/email/brevo-webhook (no typo)
3. "Inbound Email" event is selected
4. Inbound parsing is configured in Brevo

**Test:**
```bash
# Test webhook endpoint is accessible
curl https://fieldsprout.io/api/email/test

# Send test webhook from Brevo dashboard
# (Brevo has a "Send test" button)
```

### Issue: AI not responding

**Check logs:**
```bash
grep -i "error.*ai.*response" /home/fieljtgr/flaskapp/logs/error.log | tail -20
```

**Common causes:**
- OPENAI_API_KEY not set or invalid
- OpenAI API rate limit exceeded
- Conversation automatically escalated (check alerts)

**Verify API keys:**
```bash
# In Python shell
import os
print(os.getenv('OPENAI_API_KEY'))  # Should show sk-...
print(os.getenv('BREVO_API_KEY'))   # Should show xkeysib-...
```

### Issue: Conversations not showing in dashboard

**Check:**
1. Blueprint registered: `grep "conversations_bp" /home/fieljtgr/flaskapp/logs/error.log`
2. Tables exist: `SHOW TABLES LIKE 'email_%';`
3. URL is correct: https://fieldsprout.io/admin/conversations (not /conversation)

### Issue: "No contact found for email" error

**Cause:** Prospect replied from email not in `lead_contacts` table

**Fix:**
- AI service looks up contact by `from_email`
- Make sure leads were properly enriched with email addresses
- Check: `SELECT * FROM lead_contacts WHERE email = 'prospect@email.com';`

### Issue: All conversations being escalated

**Check AI model settings:**
- Model might be too conservative
- Adjust escalation logic in `ai_conversation_service.py`
- Review `_should_escalate_to_human()` method

---

## Customization

### Adjust AI Personality

Edit `/home/fieljtgr/flaskapp/flaskapp/app/services/ai_conversation_service.py`:

```python
system_prompt = f"""You are a helpful sales assistant for FieldSprout.

YOUR PERSONALITY:
- Friendly and professional
- Helpful but not pushy
- Technical when needed
- Brief and concise

[Customize this to match your brand voice]
"""
```

### Change Auto-Escalation Rules

```python
def _should_escalate_to_human(self, analysis, conversation):
    # Add custom rules:

    # Escalate high-value prospects
    if conversation.lead_score > 80:
        return True

    # Escalate specific keywords
    intent = analysis.get('intent', '').lower()
    if 'pricing' in intent or 'contract' in intent:
        return True

    # [Add your custom logic]
```

### Add Custom Alert Types

In `ai_conversation_service.py`:

```python
# Create custom alert for high-value prospects
if lead.estimated_value > 10000:
    self._create_alert(
        conversation=conversation,
        alert_type='high_value',  # Add to enum in models
        message=f"High-value prospect replied! Estimated value: ${lead.estimated_value}",
        severity='urgent'
    )
```

---

## Next Steps (Future Enhancements)

1. **UI Templates** - Create beautiful conversation thread viewer
2. **Real-time notifications** - WebSocket for live alerts
3. **Response templates** - Pre-approved responses for common scenarios
4. **A/B testing** - Test different AI personalities
5. **Sentiment tracking** - Chart sentiment over time
6. **Integration with CRM** - Sync conversations to ServiceTitan
7. **Mobile alerts** - SMS/push when urgent escalation
8. **AI learning** - Train on your best responses

---

## Summary Checklist

Before going live:

- [ ] Run SQL migration (create tables)
- [ ] Configure Brevo webhook
- [ ] Set up inbound email domain/address
- [ ] Verify OPENAI_API_KEY is set
- [ ] Verify BREVO_API_KEY is set
- [ ] Restart Flask application
- [ ] Test webhook endpoint (`/api/email/test`)
- [ ] Send test email and verify AI responds
- [ ] Check /admin/conversations dashboard loads
- [ ] Check /admin/conversations/alerts shows alerts
- [ ] Test escalation scenario

**Time to set up:** ~20 minutes
**Ongoing maintenance:** Check alerts daily

---

## Support

**View conversations:** https://fieldsprout.io/admin/conversations
**View alerts:** https://fieldsprout.io/admin/conversations/alerts
**Test webhook:** https://fieldsprout.io/api/email/test

**Logs location:**
- Application: `/home/fieljtgr/flaskapp/logs/error.log`
- Automation: `/home/fieljtgr/flaskapp/logs/automation.log`

**Database tables:**
- `email_conversations`
- `email_conversation_messages`
- `conversation_alerts`
