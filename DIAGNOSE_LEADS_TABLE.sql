-- Diagnostic Script for Leads Table Issues
-- Run this to identify any problems with the leads table

-- =================================================================
-- Step 1: Verify Table Exists
-- =================================================================

-- Check if leads table exists
SELECT TABLE_NAME, TABLE_TYPE, ENGINE, TABLE_COLLATION
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME = 'leads';

-- Expected: Should return 1 row with TABLE_NAME = 'leads'


-- =================================================================
-- Step 2: Check Table Structure
-- =================================================================

-- Show all columns in leads table
DESCRIBE leads;

-- Expected columns:
-- id, campaign_id, crm_contact_id, company_name, website, phone, address,
-- source_type, source_url, serp_position, email_format, decision_maker_name,
-- decision_maker_title, decision_maker_email, decision_maker_linkedin,
-- enrichment_status, enrichment_attempts, enriched_at, email_status,
-- current_sequence_step, last_email_sent_at, first_opened_at, replied_at,
-- unsubscribed_at, auto_delete_at, extra_data, created_at, updated_at


-- =================================================================
-- Step 3: Check for Data Integrity Issues
-- =================================================================

-- Count total leads
SELECT COUNT(*) AS total_leads FROM leads;

-- Check for NULL campaign_id (should be 0 - campaign_id is NOT NULL)
SELECT COUNT(*) AS leads_with_null_campaign
FROM leads
WHERE campaign_id IS NULL;

-- Check for invalid campaign_id (orphan leads)
SELECT COUNT(*) AS orphan_leads
FROM leads l
LEFT JOIN lead_campaigns lc ON l.campaign_id = lc.id
WHERE lc.id IS NULL;

-- Check for NULL company_name (should be 0 - company_name is NOT NULL)
SELECT COUNT(*) AS leads_with_null_company
FROM leads
WHERE company_name IS NULL OR company_name = '';


-- =================================================================
-- Step 4: Check ENUM Values
-- =================================================================

-- Check source_type enum values
SELECT DISTINCT source_type, COUNT(*) AS count
FROM leads
GROUP BY source_type
ORDER BY count DESC;
-- Expected: 'ad', 'map', 'lsa', 'organic'

-- Check enrichment_status enum values
SELECT DISTINCT enrichment_status, COUNT(*) AS count
FROM leads
GROUP BY enrichment_status
ORDER BY count DESC;
-- Expected: 'pending', 'in_progress', 'completed', 'failed'

-- Check email_status enum values
SELECT DISTINCT email_status, COUNT(*) AS count
FROM leads
GROUP BY email_status
ORDER BY count DESC;
-- Expected: 'pending', 'sending', 'sent', 'opened', 'replied', 'bounced', 'unsubscribed'


-- =================================================================
-- Step 5: Check Foreign Key Constraints
-- =================================================================

-- Check foreign keys on leads table
SELECT
    CONSTRAINT_NAME,
    COLUMN_NAME,
    REFERENCED_TABLE_NAME,
    REFERENCED_COLUMN_NAME,
    UPDATE_RULE,
    DELETE_RULE
FROM information_schema.KEY_COLUMN_USAGE kcu
JOIN information_schema.REFERENTIAL_CONSTRAINTS rc
    ON kcu.CONSTRAINT_NAME = rc.CONSTRAINT_NAME
    AND kcu.TABLE_SCHEMA = rc.CONSTRAINT_SCHEMA
WHERE kcu.TABLE_SCHEMA = DATABASE()
  AND kcu.TABLE_NAME = 'leads'
  AND kcu.REFERENCED_TABLE_NAME IS NOT NULL;

-- Expected:
-- campaign_id -> lead_campaigns.id
-- crm_contact_id -> crm_contacts.id (if applicable)


-- =================================================================
-- Step 6: Check Indexes
-- =================================================================

-- Show all indexes on leads table
SHOW INDEX FROM leads;

-- Expected indexes:
-- PRIMARY (id)
-- campaign_id (for foreign key)
-- decision_maker_email (for searching)
-- email_status (for filtering)


-- =================================================================
-- Step 7: Check for Common Errors
-- =================================================================

-- Check for duplicate leads (same company in same campaign)
SELECT
    campaign_id,
    company_name,
    COUNT(*) AS duplicate_count
FROM leads
GROUP BY campaign_id, company_name
HAVING COUNT(*) > 1
ORDER BY duplicate_count DESC
LIMIT 10;

-- Check for leads with invalid email_status progression
-- (e.g., email_status='sent' but last_email_sent_at is NULL)
SELECT COUNT(*) AS invalid_email_status_leads
FROM leads
WHERE email_status IN ('sent', 'opened', 'replied')
  AND last_email_sent_at IS NULL;


-- =================================================================
-- Step 8: Sample Data Review
-- =================================================================

-- Show recent leads
SELECT
    id,
    campaign_id,
    company_name,
    source_type,
    enrichment_status,
    email_status,
    created_at
FROM leads
ORDER BY created_at DESC
LIMIT 10;

-- Show leads by campaign
SELECT
    lc.id AS campaign_id,
    lc.name AS campaign_name,
    lc.is_core,
    COUNT(l.id) AS lead_count,
    SUM(CASE WHEN l.enrichment_status = 'completed' THEN 1 ELSE 0 END) AS enriched_count,
    SUM(CASE WHEN l.email_status IN ('sent', 'opened', 'replied') THEN 1 ELSE 0 END) AS emailed_count
FROM lead_campaigns lc
LEFT JOIN leads l ON lc.id = l.campaign_id
GROUP BY lc.id, lc.name, lc.is_core
ORDER BY lead_count DESC
LIMIT 20;


-- =================================================================
-- Step 9: Check Related Tables
-- =================================================================

-- Verify lead_emails table exists
SELECT COUNT(*) AS lead_emails_count FROM lead_emails;

-- Verify lead_contacts table exists (if used)
-- SELECT COUNT(*) AS lead_contacts_count FROM lead_contacts;

-- Verify email_sequences table exists
SELECT COUNT(*) AS email_sequences_count FROM email_sequences;


-- =================================================================
-- Step 10: Error Patterns
-- =================================================================

-- If you're seeing a specific error, uncomment and run relevant checks:

-- ERROR: Table doesn't exist
/*
SHOW TABLES LIKE '%lead%';
*/

-- ERROR: Column doesn't exist
/*
SHOW COLUMNS FROM leads;
*/

-- ERROR: Foreign key constraint fails
/*
SELECT l.id, l.campaign_id
FROM leads l
LEFT JOIN lead_campaigns lc ON l.campaign_id = lc.id
WHERE lc.id IS NULL
LIMIT 10;
*/

-- ERROR: Data too long for column
/*
SELECT
    id,
    LENGTH(company_name) AS company_name_length,
    LENGTH(website) AS website_length,
    LENGTH(address) AS address_length
FROM leads
WHERE LENGTH(company_name) > 255
   OR LENGTH(website) > 500
   OR LENGTH(address) > 500
LIMIT 10;
*/

-- ERROR: Incorrect integer value / enum value
/*
SELECT id, source_type, enrichment_status, email_status
FROM leads
WHERE source_type NOT IN ('ad', 'map', 'lsa', 'organic')
   OR enrichment_status NOT IN ('pending', 'in_progress', 'completed', 'failed')
   OR email_status NOT IN ('pending', 'sending', 'sent', 'opened', 'replied', 'bounced', 'unsubscribed')
LIMIT 10;
*/


-- =================================================================
-- INTERPRETATION GUIDE
-- =================================================================

/*
COMMON ISSUES AND FIXES:

1. Table doesn't exist:
   - Run migrations: flask db upgrade
   - Check database name is correct

2. Orphan leads (leads with invalid campaign_id):
   - Run CHECK_AND_FIX_ORPHAN_LEADS.sql
   - Either delete orphans or reassign to misc campaign

3. Column doesn't exist:
   - You may be running old code against new schema
   - Check if migrations are up to date
   - Verify you're in the correct database

4. Foreign key constraint fails:
   - Trying to insert lead with non-existent campaign_id
   - Create the campaign first, then create leads

5. Enum value error:
   - Trying to insert invalid source_type, enrichment_status, or email_status
   - Use only allowed values (see Step 4 expected values)

6. Duplicate leads:
   - Multiple leads with same company_name in same campaign
   - This is allowed but may indicate scraping ran twice
   - Review scraping logic to prevent duplicates

7. Performance issues:
   - Check indexes exist (Step 6)
   - Analyze query execution plans
   - Consider adding indexes on frequently queried columns
*/
