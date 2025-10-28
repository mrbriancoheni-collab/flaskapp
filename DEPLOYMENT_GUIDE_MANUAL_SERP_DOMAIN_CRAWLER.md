# Manual SERP Import & Domain Crawler Guide

## Overview

This guide covers two major features:
1. **Manual SERP Import** - Bypass Google bot detection by pasting HTML
2. **Domain Crawler** - Automatically enrich CRM leads with contact info

---

## Part 1: Manual SERP Import

### Why Manual Import?

Google blocks automated scraping from servers, but you can use **your browser** to get the HTML and paste it for parsing.

### How It Works

```
You → Google Search → View Source → Copy HTML → Paste → Extract Leads
```

The system uses the same parsing logic as the automated scraper, but works with HTML from your legitimate browser session.

---

## Step-by-Step: Manual SERP Import

### Step 1: Access the Interface

Go to: **https://yoursite.com/admin/serp-scraper/manual**

Or navigate: Admin → SERP Scraper → "Go to Manual Import" button

### Step 2: Search Google in Your Browser

1. Open a regular browser window (Chrome, Firefox, Safari)
2. Go to Google.com
3. Search for your target keywords:
   - Example: `plumber denver co`
   - Example: `hvac repair austin texas`
   - Example: `electrician near me phoenix`

### Step 3: View Page Source

**Windows/Linux:**
- Right-click on page → "View Page Source"
- Or press: `Ctrl + U`

**Mac:**
- Right-click on page → "View Page Source"
- Or press: `Cmd + Option + U`

### Step 4: Copy ALL HTML

1. In the source view, select all: `Ctrl+A` (Windows/Linux) or `Cmd+A` (Mac)
2. Copy: `Ctrl+C` (Windows/Linux) or `Cmd+C` (Mac)
3. You should have 50,000+ characters copied

### Step 5: Paste and Parse

1. Return to the Manual Import page
2. Fill in:
   - **Service Type**: What you searched for (e.g., "plumber")
   - **Location**: Where you searched (e.g., "Denver, CO")
   - **HTML Source**: Paste the copied HTML
3. Optional: Check "Automatically add leads to CRM"
4. Click "Parse & Import Leads"

### Step 6: Review Results

The system will:
- Extract Google Ads (PPC) advertisers
- Extract Local Service Ads (LSA) businesses
- Show you all found leads
- Add to CRM (if auto-add checked) or let you review first

### What Gets Extracted

- ✅ Business names
- ✅ Website domains
- ✅ Phone numbers
- ✅ Locations
- ✅ Ad type (PPC vs LSA)
- ✅ Ratings/reviews (if present)

### Expected Results

Typical search will find:
- **Local Service Ads**: 3-8 businesses (top of page with "Google Guaranteed")
- **PPC Ads**: 5-10 businesses (marked with "Sponsored" or "Ad")
- **Total**: Usually 8-18 advertiser leads per search

---

## Part 2: Domain Crawler (Lead Enrichment)

### What It Does

After you have leads in your CRM (from SERP import or other sources), the Domain Crawler:
- Crawls their websites
- Finds contact information
- Discovers team members (CEO, owner, marketing, etc.)
- Enriches your CRM automatically

### How to Use Domain Crawler

#### Access the Interface

Go to: **https://yoursite.com/admin/domain-crawler**

Or navigate: Admin → Domain Crawler

#### Dashboard Shows:

- Total contacts with domains
- Contacts never crawled
- Contacts missing email
- Contacts missing phone

#### Run a Crawl

1. Select number of domains to crawl (10, 25, 50, 100)
2. Optional: Check "Force re-crawl" to crawl even recently crawled domains
3. Click "Start Crawling"

#### What Happens

For each company domain, the crawler:

1. **Finds General Contact Info:**
   - Checks: Homepage, /contact, /about, /contact-us
   - Extracts: Email, phone, business name
   - Updates CRM contact record

2. **Finds Team Contacts:**
   - Checks: /team, /leadership, /about/team, /our-team
   - Extracts: Names, titles, emails, phones
   - Categorizes: Executive, Owner, Marketing, Operations
   - Saves to `company_contacts` table

#### Results Example

```
Crawled 10 domains.
Enriched 8 contacts: 3 emails, 5 phones, 2 names.
Found 15 team contacts (CEO, owner, marketing, etc.).
```

### Success Rates (Typical)

| Data Point | Success Rate |
|------------|--------------|
| Phone numbers | 60-80% |
| Emails | 30-50% |
| Business names | 40-60% |
| Team contacts | 40-60% of companies |
| Contact emails | 20-40% of team members |

### Best Practices

**For Best Results:**
- Crawl smaller batches first (10-25 domains) to test
- Run crawls during off-peak hours (night/weekend)
- Review discovered contacts in database
- Re-crawl after 30+ days for updated info

**Smart Crawling:**
- System automatically skips recently crawled domains (<30 days)
- Only crawls if missing email/phone OR never crawled
- Use "Force re-crawl" only when needed

---

## Part 3: Viewing Discovered Team Contacts

### Via Database Query

```sql
-- View all discovered team contacts with company info
SELECT
  cc.full_name,
  cc.title,
  cc.role_category,
  cc.email,
  cc.phone,
  crm.business_name,
  crm.domain,
  cc.source
FROM company_contacts cc
JOIN crm_contacts crm ON cc.crm_contact_id = crm.id
WHERE cc.role_category IN ('executive', 'owner', 'marketing')
ORDER BY cc.discovered_at DESC
LIMIT 50;
```

### Export to CSV

```sql
-- Export team contacts for outreach
SELECT
  cc.full_name AS 'Contact Name',
  cc.title AS 'Job Title',
  cc.email AS 'Email',
  cc.phone AS 'Phone',
  crm.business_name AS 'Company',
  crm.domain AS 'Website',
  cc.role_category AS 'Role',
  cc.source AS 'Found On'
FROM company_contacts cc
JOIN crm_contacts crm ON cc.crm_contact_id = crm.id
WHERE cc.email IS NOT NULL
ORDER BY cc.discovered_at DESC
INTO OUTFILE '/tmp/team_contacts_export.csv'
FIELDS TERMINATED BY ','
ENCLOSED BY '"'
LINES TERMINATED BY '\n';
```

---

## Part 4: Complete Workflow Example

### Scenario: Find HVAC Companies in Phoenix

**Step 1: Get Advertiser Leads**
1. Search Google for "hvac repair phoenix az"
2. View page source, copy HTML
3. Go to /admin/serp-scraper/manual
4. Paste HTML, add service="hvac repair", location="Phoenix, AZ"
5. Import → 12 advertiser leads added to CRM

**Step 2: Enrich with Contact Info**
1. Go to /admin/domain-crawler
2. Select "10 domains" to crawl
3. Click "Start Crawling"
4. Results:
   - 8 companies enriched with phone/email
   - 15 team contacts found (5 CEOs, 4 owners, 6 marketing)

**Step 3: Segment for Outreach**
```sql
-- CEOs/Owners for partnership discussions
SELECT * FROM company_contacts
WHERE role_category IN ('executive', 'owner')
AND email IS NOT NULL;

-- Marketing contacts for advertising opportunities
SELECT * FROM company_contacts
WHERE role_category = 'marketing'
AND email IS NOT NULL;
```

**Step 4: Export and Use**
- Export to CSV for email campaigns
- Import to CRM/email tool
- Personalize outreach based on role

---

## Part 5: Automated Daily Crawling

### Set Up Cron Job (Optional)

To automatically crawl 50 domains every night at 2 AM:

```bash
# Edit crontab
crontab -e

# Add this line:
0 2 * * * cd /home/fieljtgr/flaskapp && /usr/bin/python3 -c "from app import create_app; from app.tasks.domain_crawler_task import run_daily_crawler; app = create_app(); app.app_context().push(); run_daily_crawler(max_domains=50)" >> /home/fieljtgr/logs/domain_crawler.log 2>&1
```

This will:
- Run daily at 2 AM
- Crawl up to 50 domains
- Log results to file
- Skip recently crawled domains
- Automatically enrich CRM

---

## Part 6: Monitoring & Troubleshooting

### Check Crawler Status

```sql
-- See recent crawl activity
SELECT
  business_name,
  domain,
  last_crawled_at,
  crawl_attempts,
  CASE WHEN email IS NOT NULL THEN 'Yes' ELSE 'No' END as has_email,
  CASE WHEN phone IS NOT NULL THEN 'Yes' ELSE 'No' END as has_phone
FROM crm_contacts
WHERE last_crawled_at IS NOT NULL
ORDER BY last_crawled_at DESC
LIMIT 20;
```

### Check Discovered Contacts

```sql
-- Count contacts by role
SELECT
  role_category,
  COUNT(*) as count,
  SUM(CASE WHEN email IS NOT NULL THEN 1 ELSE 0 END) as with_email,
  SUM(CASE WHEN phone IS NOT NULL THEN 1 ELSE 0 END) as with_phone
FROM company_contacts
GROUP BY role_category
ORDER BY count DESC;
```

### Common Issues

**Issue: Manual import finds 0 leads**
- Make sure you copied the FULL page source (should be 50k+ chars)
- Check if ads are present on the page you searched
- Try a different search term with more advertisers

**Issue: Domain crawler finds no contacts**
- Some websites don't have /team or /about pages
- Small businesses may not list individual contacts
- Check the source field to see which pages were checked

**Issue: Emails not found**
- Many businesses use contact forms instead of mailto: links
- Some hide emails behind JavaScript
- Phone numbers are more commonly found

---

## Part 7: Tips for Maximum Success

### For Manual SERP Import:
✅ Search specific services (not generic terms)
✅ Include location in search
✅ Look for searches with 5+ ads showing
✅ Copy from "View Source" not from page itself
✅ Import multiple searches to build lead list

### For Domain Crawler:
✅ Start with small batches (10-25 domains)
✅ Crawl during business hours (contact info more visible)
✅ Re-crawl after 60+ days for updated info
✅ Focus on companies with professional websites
✅ Check discovered contacts for quality

### For Outreach:
✅ Segment by role (CEO vs Marketing)
✅ Personalize messages based on title
✅ Mention their company name/website
✅ Track which contacts respond best
✅ Follow up with non-responders

---

## Summary

You now have two powerful lead generation tools:

1. **Manual SERP Import** - Bypasses Google blocking, gets advertiser leads
2. **Domain Crawler** - Automatically enriches leads with contact info

**Workflow:**
```
Google Search → Manual Import → CRM Leads → Domain Crawler → Enriched Contacts → Outreach
```

**Next Steps:**
1. Upload latest code to server
2. Try manual SERP import with 1-2 searches
3. Run domain crawler on imported leads
4. Check database for discovered contacts
5. Export and start outreach!

---

Need help? Check the logs:
- Flask app logs: `/home/fieljtgr/logs/` (or wherever your logs are)
- Manual import: Watch for "Manual SERP parse:" in logs
- Domain crawler: Watch for "Crawling domain:" in logs
