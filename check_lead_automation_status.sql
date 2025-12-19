-- ============================================================================
-- Lead Automation Diagnostic Report
-- ============================================================================
-- Checks why only 8 emails were sent when the target is 50+/day
-- ============================================================================

SELECT '============================================================' as '';
SELECT 'LEAD AUTOMATION DIAGNOSTIC REPORT' as '';
SELECT '============================================================' as '';
SELECT '' as '';

-- ============================================================================
-- 1. CAMPAIGN STATUS
-- ============================================================================
SELECT '============================================================' as '';
SELECT '1. CAMPAIGN STATUS' as '';
SELECT '============================================================' as '';
SELECT '' as '';

SELECT 'Total Campaigns:' as '', COUNT(*) as count FROM lead_campaigns;

SELECT '' as '';
SELECT 'Breakdown by status:' as '';
SELECT status, COUNT(*) as count
FROM lead_campaigns
GROUP BY status
ORDER BY count DESC;

-- ============================================================================
-- 2. LEAD STATUS
-- ============================================================================
SELECT '' as '';
SELECT '============================================================' as '';
SELECT '2. LEAD STATUS' as '';
SELECT '============================================================' as '';
SELECT '' as '';

SELECT 'Total Leads:' as '', COUNT(*) as count FROM leads;

SELECT '' as '';
SELECT 'By Enrichment Status:' as '';
SELECT enrichment_status, COUNT(*) as count
FROM leads
GROUP BY enrichment_status
ORDER BY count DESC;

SELECT '' as '';
SELECT 'By Email Status:' as '';
SELECT email_status, COUNT(*) as count
FROM leads
GROUP BY email_status
ORDER BY count DESC;

-- ============================================================================
-- 3. LEADS READY TO EMAIL
-- ============================================================================
SELECT '' as '';
SELECT '============================================================' as '';
SELECT '3. LEADS READY TO EMAIL' as '';
SELECT '============================================================' as '';
SELECT '' as '';

SELECT 'Enriched leads (completed):' as '', COUNT(*) as count
FROM leads
WHERE enrichment_status = 'completed';

SELECT '' as '';
SELECT 'Leads with pending contacts:' as '', COUNT(DISTINCT lead_id) as count
FROM lead_contacts
WHERE email_status = 'pending'
AND email IS NOT NULL;

SELECT '' as '';
SELECT 'Total pending contacts:' as '', COUNT(*) as count
FROM lead_contacts
WHERE email_status = 'pending'
AND email IS NOT NULL;

-- ============================================================================
-- 4. TODAY'S EMAIL ACTIVITY
-- ============================================================================
SELECT '' as '';
SELECT '============================================================' as '';
SELECT '4. TODAYS EMAIL ACTIVITY' as '';
SELECT '============================================================' as '';
SELECT '' as '';

SELECT 'Emails sent today:' as '', COUNT(*) as count
FROM lead_emails
WHERE DATE(sent_at) = CURDATE();

SELECT 'Daily limit: 250' as '';
SELECT '' as '';

SELECT CONCAT('Remaining capacity: ', 250 - COUNT(*)) as ''
FROM lead_emails
WHERE DATE(sent_at) = CURDATE();

SELECT CONCAT('WARNING: Only ', COUNT(*), ' emails sent, target minimum is 50!') as ''
FROM lead_emails
WHERE DATE(sent_at) = CURDATE()
HAVING COUNT(*) < 50;

-- ============================================================================
-- 5. ENRICHMENT ACTIVITY
-- ============================================================================
SELECT '' as '';
SELECT '============================================================' as '';
SELECT '5. ENRICHMENT ACTIVITY' as '';
SELECT '============================================================' as '';
SELECT '' as '';

SELECT 'Leads enriched today:' as '', COUNT(*) as count
FROM leads
WHERE DATE(enrichment_completed_at) = CURDATE();

SELECT 'Daily limit: 100' as '';
SELECT '' as '';

SELECT 'Pending enrichments:' as '', COUNT(*) as count
FROM leads
WHERE enrichment_status = 'pending';

-- ============================================================================
-- 6. SCRAPING ACTIVITY
-- ============================================================================
SELECT '' as '';
SELECT '============================================================' as '';
SELECT '6. SCRAPING ACTIVITY' as '';
SELECT '============================================================' as '';
SELECT '' as '';

SELECT 'Campaigns scraped today:' as '', COUNT(*) as count
FROM lead_campaigns
WHERE DATE(last_scraped_at) = CURDATE();

SELECT 'Daily limit: 50' as '';
SELECT '' as '';

SELECT 'Ready campaigns not scraped today:' as '', COUNT(*) as count
FROM lead_campaigns
WHERE status = 'ready'
AND (last_scraped_at IS NULL OR DATE(last_scraped_at) < CURDATE());

-- ============================================================================
-- 7. SAMPLE OF PENDING CONTACTS (First 10)
-- ============================================================================
SELECT '' as '';
SELECT '============================================================' as '';
SELECT '7. SAMPLE OF PENDING CONTACTS' as '';
SELECT '============================================================' as '';
SELECT '' as '';

SELECT
    lc.id,
    lc.email,
    lc.name,
    lc.title,
    l.company_name,
    l.enrichment_status,
    lc.email_status
FROM lead_contacts lc
JOIN leads l ON l.id = lc.lead_id
WHERE lc.email_status = 'pending'
AND lc.email IS NOT NULL
ORDER BY lc.created_at DESC
LIMIT 10;

-- ============================================================================
-- 8. RECENT EMAIL SENDS (Last 10)
-- ============================================================================
SELECT '' as '';
SELECT '============================================================' as '';
SELECT '8. RECENT EMAIL SENDS' as '';
SELECT '============================================================' as '';
SELECT '' as '';

SELECT
    le.id,
    le.sent_at,
    le.status,
    l.company_name,
    l.decision_maker_email,
    lc.name
FROM lead_emails le
JOIN leads l ON l.id = le.lead_id
LEFT JOIN lead_campaigns lc ON lc.id = le.campaign_id
ORDER BY le.sent_at DESC
LIMIT 10;

-- ============================================================================
-- 9. BOTTLENECK SUMMARY
-- ============================================================================
SELECT '' as '';
SELECT '============================================================' as '';
SELECT '9. BOTTLENECK SUMMARY' as '';
SELECT '============================================================' as '';
SELECT '' as '';

SELECT 'Check the numbers above to identify bottlenecks:' as '';
SELECT '' as '';
SELECT '1. If Total Campaigns = 0: CREATE CAMPAIGNS' as '';
SELECT '2. If Ready campaigns = 0: ACTIVATE CAMPAIGNS' as '';
SELECT '3. If Campaigns scraped today = 0: RUN SCRAPING' as '';
SELECT '4. If Total Leads = 0: SCRAPING NOT GENERATING LEADS' as '';
SELECT '5. If Pending enrichments > 0 but Leads enriched today = 0: RUN ENRICHMENT' as '';
SELECT '6. If Enriched leads > 0 but Pending contacts = 0: ENRICHMENT NOT FINDING CONTACTS' as '';
SELECT '7. If Pending contacts > 0 but Emails sent < 50: EMAIL SENDING PROBLEM' as '';

SELECT '' as '';
SELECT '============================================================' as '';
SELECT 'END OF REPORT' as '';
SELECT '============================================================' as '';
