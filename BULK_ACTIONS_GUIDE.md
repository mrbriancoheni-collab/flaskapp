# Bulk Action Endpoints Guide

## Overview

Three new bulk action endpoints have been added to complete tasks that haven't been processed yet. These allow you to manually trigger scraping, enrichment, and email sending for incomplete work.

## API Endpoints

### 1. Bulk Scrape All Draft Campaigns

**Endpoint**: `POST /admin/lead-campaigns/bulk/scrape-all`

**What it does**: Scrapes all campaigns that haven't been scraped yet (status = 'draft')

**Limits**: Up to 20 campaigns per request

**Response**:
```json
{
  "success": true,
  "campaigns_scraped": 15,
  "total_leads_created": 1250,
  "message": "Scraped 15 campaigns, created 1250 leads"
}
```

**Requirements**:
- SERPAPI_API_KEY must be configured
- Campaigns must have status='draft'

**Usage**:
```bash
curl -X POST http://localhost:5000/admin/lead-campaigns/bulk/scrape-all \
  -H "Authorization: Bearer YOUR_TOKEN"
```

**What gets scraped**:
- Google Ads (if enabled)
- Google Maps / Local Pack (if enabled)
- Local Services Ads (if enabled)
- Organic results (if enabled, top 20)

**Filters applied**:
- Excludes directory sites (Yelp, HomeAdvisor, etc.)
- Excludes social media (Facebook, LinkedIn, etc.)
- Excludes .gov and .org domains
- Deduplicates by company name within campaign

---

### 2. Bulk Enrich All Pending Leads

**Endpoint**: `POST /admin/lead-campaigns/bulk/enrich-all`

**What it does**: Enriches all leads with enrichment_status = 'pending'

**Limits**: Up to 100 leads per request

**Response**:
```json
{
  "success": true,
  "enriched_count": 85,
  "failed_count": 15,
  "message": "Enriched 85 leads, 15 failed"
}
```

**What gets enriched**:
- Decision maker name
- Decision maker title
- Decision maker email
- Decision maker LinkedIn URL
- Email format pattern

**Usage**:
```bash
curl -X POST http://localhost:5000/admin/lead-campaigns/bulk/enrich-all \
  -H "Authorization: Bearer YOUR_TOKEN"
```

**Notes**:
- Leads are marked as 'in_progress' during enrichment
- Failed leads are marked as 'failed'
- Successfully enriched leads are marked as 'completed'
- Campaign enrichment stats are updated after completion

---

### 3. Bulk Send Emails to All Ready Leads

**Endpoint**: `POST /admin/lead-campaigns/bulk/send-emails-all`

**What it does**: Sends emails to all leads ready to be contacted

**Limits**: Up to 100 emails per request

**Response**:
```json
{
  "success": true,
  "sent_count": 92,
  "failed_count": 8,
  "message": "Sent 92 emails, 8 failed"
}
```

**Requirements**:
- Leads must have enrichment_status='completed'
- Leads must have email_status='pending'
- Leads must have a decision_maker_email
- Campaign must have an active email sequence (step 1)

**Email Provider**:
- Uses configured EMAIL_PROVIDER (defaults to Brevo)
- Falls back to Mailgun if Brevo not configured
- Requires BREVO_API_KEY or MAILGUN_API_KEY

**Safety Features**:
- Checks unsubscribe list before sending
- Skips leads with no email sequence configured
- Personalizes emails with company/contact variables
- Records all sent emails in database
- Updates campaign email stats

**Usage**:
```bash
curl -X POST http://localhost:5000/admin/lead-campaigns/bulk/send-emails-all \
  -H "Authorization: Bearer YOUR_TOKEN"
```

---

## Usage Workflow

### Complete Pipeline for New Campaigns

1. **Create/Wait for campaigns to be created** (automated or manual)
   - The automation creates 20 campaigns (one per business type)

2. **Scrape all draft campaigns**:
   ```bash
   POST /admin/lead-campaigns/bulk/scrape-all
   ```
   - Result: Campaigns change from 'draft' → 'ready'
   - Leads created with enrichment_status='pending'

3. **Enrich all pending leads**:
   ```bash
   POST /admin/lead-campaigns/bulk/enrich-all
   ```
   - Result: Leads enriched with contact information
   - enrichment_status changes to 'completed'
   - email_status remains 'pending'

4. **Send emails to all ready leads**:
   ```bash
   POST /admin/lead-campaigns/bulk/send-emails-all
   ```
   - Result: Emails sent to enriched leads
   - email_status changes to 'sent'
   - Email records created in database

### Catching Up After Pause

If automation was paused and you have incomplete work:

```bash
# Check what needs to be done
# - Draft campaigns → Need scraping
# - Pending enrichment → Need enriching
# - Pending emails → Need sending

# Run all three in sequence
POST /admin/lead-campaigns/bulk/scrape-all
POST /admin/lead-campaigns/bulk/enrich-all
POST /admin/lead-campaigns/bulk/send-emails-all
```

### Testing Individual Steps

To test each step of the pipeline:

```bash
# 1. Create a test campaign manually via UI
# 2. Scrape it
POST /admin/lead-campaigns/bulk/scrape-all

# 3. Check leads were created
GET /admin/lead-campaigns/{campaign_id}

# 4. Enrich the leads
POST /admin/lead-campaigns/bulk/enrich-all

# 5. Check enrichment worked
GET /admin/lead-campaigns/{campaign_id}

# 6. Create email sequence for campaign (via UI)
# 7. Send emails
POST /admin/lead-campaigns/bulk/send-emails-all
```

---

## Integration with Automation

These bulk endpoints complement the daily automation:

**Daily Automation** (Automatic):
- Runs via cron job
- Respects daily limits (50 scrapes, 100 enrichments, 250 emails)
- Processes campaigns sequentially
- Resumes from where it stopped

**Bulk Endpoints** (Manual):
- Triggered manually or via API
- Process incomplete tasks in batches
- Useful for catching up or testing
- Same logic as automation, just manual trigger

**When to use bulk endpoints**:
- ✅ Testing the pipeline
- ✅ Catching up after automation pause
- ✅ Processing urgent campaigns
- ✅ Manually completing specific batches
- ❌ Don't use if automation is running (may cause conflicts)

---

## Error Handling

All endpoints handle errors gracefully:

- **Individual failures don't stop the batch**
  - If one campaign fails to scrape, others continue
  - If one lead fails enrichment, others continue
  - If one email fails to send, others continue

- **Partial success is reported**
  - Response includes both success and failure counts
  - Logs show details of each failure

- **Database consistency**
  - Each item is committed individually
  - Rollback on error for that item only
  - Other items remain processed

---

## Monitoring

Check results in the admin interface:

1. **Campaign List**: `/admin/lead-campaigns/`
   - Shows newest 20 campaigns
   - Displays scraped/enriched/sent counts

2. **Automation Status**: `/admin/lead-campaigns/automation-status`
   - Shows overall progress
   - Daily statistics
   - Automation state

3. **Activity Feed**: `/admin/lead-campaigns/activity`
   - Recent leads scraped
   - Recent enrichments
   - Recent emails sent

4. **Email Activity**: `/admin/lead-campaigns/email-activity`
   - Detailed email log
   - Open/bounce tracking
   - Filter by campaign or status

---

## Example: Complete a Full Batch

Here's a complete example of processing all incomplete work:

```javascript
// In your admin UI or via API client

// 1. Scrape all draft campaigns
const scrapeResult = await fetch('/admin/lead-campaigns/bulk/scrape-all', {
  method: 'POST',
  headers: { 'Authorization': 'Bearer YOUR_TOKEN' }
});
console.log(await scrapeResult.json());
// { campaigns_scraped: 20, total_leads_created: 2000 }

// 2. Wait a moment, then enrich
await sleep(2000);

const enrichResult = await fetch('/admin/lead-campaigns/bulk/enrich-all', {
  method: 'POST',
  headers: { 'Authorization': 'Bearer YOUR_TOKEN' }
});
console.log(await enrichResult.json());
// { enriched_count: 100, failed_count: 0 }

// 3. Keep enriching until all done
while (true) {
  const result = await fetch('/admin/lead-campaigns/bulk/enrich-all', { 
    method: 'POST' 
  });
  const data = await result.json();
  if (data.enriched_count === 0) break;
  console.log(`Enriched ${data.enriched_count} more leads`);
  await sleep(5000); // Rate limit between batches
}

// 4. Send emails (make sure sequences are configured first!)
const emailResult = await fetch('/admin/lead-campaigns/bulk/send-emails-all', {
  method: 'POST',
  headers: { 'Authorization': 'Bearer YOUR_TOKEN' }
});
console.log(await emailResult.json());
// { sent_count: 100, failed_count: 0 }
```

---

## Summary

✅ **Three bulk endpoints added**:
1. Scrape all draft campaigns (up to 20)
2. Enrich all pending leads (up to 100)
3. Send emails to all ready leads (up to 100)

✅ **Safe to use**:
- Error handling per item
- Respects unsubscribe list
- Updates campaign stats
- Logs all activity

✅ **Flexible**:
- Works with Brevo or Mailgun
- Processes incomplete tasks only
- Can be run multiple times safely

✅ **Complements automation**:
- Same logic as daily automation
- Manual trigger for control
- Great for testing and catch-up
