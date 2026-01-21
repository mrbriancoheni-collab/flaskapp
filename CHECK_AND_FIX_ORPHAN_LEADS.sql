-- SQL Script to Check and Fix Orphan Leads
-- Run this BEFORE creating the 20 new campaigns to ensure data integrity

-- =================================================================
-- Step 1: Identify Orphan Leads (leads without valid campaigns)
-- =================================================================

-- Check for leads with invalid campaign_id
SELECT
    l.id AS lead_id,
    l.campaign_id,
    l.company_name,
    l.created_at,
    'Invalid campaign_id' AS issue
FROM leads l
LEFT JOIN lead_campaigns lc ON l.campaign_id = lc.id
WHERE lc.id IS NULL;

-- Count orphan leads
SELECT COUNT(*) AS orphan_lead_count
FROM leads l
LEFT JOIN lead_campaigns lc ON l.campaign_id = lc.id
WHERE lc.id IS NULL;


-- =================================================================
-- Step 2: Check for Orphan Email Records
-- =================================================================

-- Check for emails pointing to non-existent leads
SELECT
    e.id AS email_id,
    e.lead_id,
    e.sent_at,
    'Lead not found' AS issue
FROM lead_emails e
LEFT JOIN leads l ON e.lead_id = l.id
WHERE l.id IS NULL;


-- =================================================================
-- Step 3: Check for Orphan Contact Emails
-- =================================================================

-- Check for contact emails pointing to non-existent contacts
SELECT
    ce.id AS contact_email_id,
    ce.contact_id,
    ce.sent_at,
    'Contact not found' AS issue
FROM lead_contact_emails ce
LEFT JOIN lead_contacts lc ON ce.contact_id = lc.id
WHERE lc.id IS NULL;


-- =================================================================
-- Step 4: FIX - Delete Orphan Leads (USE WITH CAUTION!)
-- =================================================================

-- BACKUP FIRST: Export orphan leads before deleting
-- Uncomment to create a backup table:
/*
CREATE TABLE IF NOT EXISTS orphan_leads_backup AS
SELECT l.*
FROM leads l
LEFT JOIN lead_campaigns lc ON l.campaign_id = lc.id
WHERE lc.id IS NULL;
*/

-- DELETE orphan leads (this will cascade to related records)
-- Uncomment when you're ready to clean up:
/*
DELETE l FROM leads l
LEFT JOIN lead_campaigns lc ON l.campaign_id = lc.id
WHERE lc.id IS NULL;
*/


-- =================================================================
-- Step 5: FIX - Delete Orphan Email Records
-- =================================================================

-- Delete emails with no lead
-- Uncomment to execute:
/*
DELETE e FROM lead_emails e
LEFT JOIN leads l ON e.lead_id = l.id
WHERE l.id IS NULL;

DELETE ce FROM lead_contact_emails ce
LEFT JOIN lead_contacts lc ON ce.contact_id = lc.id
WHERE lc.id IS NULL;
*/


-- =================================================================
-- Step 6: Add Foreign Key Constraints (if not already present)
-- =================================================================

-- Ensure foreign keys have ON DELETE CASCADE
-- This prevents orphans in the future

-- Check existing foreign keys
SELECT
    TABLE_NAME,
    COLUMN_NAME,
    CONSTRAINT_NAME,
    REFERENCED_TABLE_NAME,
    REFERENCED_COLUMN_NAME
FROM information_schema.KEY_COLUMN_USAGE
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME IN ('leads', 'lead_emails', 'lead_contact_emails', 'email_sequences')
  AND REFERENCED_TABLE_NAME IS NOT NULL;

-- If foreign keys don't have CASCADE, you may need to recreate them:
-- (Check your existing constraints first!)

/*
-- Example: Recreate lead_emails foreign key with CASCADE
ALTER TABLE lead_emails
DROP FOREIGN KEY lead_emails_ibfk_1;  -- Replace with actual constraint name

ALTER TABLE lead_emails
ADD CONSTRAINT lead_emails_lead_fk
FOREIGN KEY (lead_id) REFERENCES leads(id)
ON DELETE CASCADE;
*/


-- =================================================================
-- Step 7: Verify Data Integrity After Cleanup
-- =================================================================

-- Verify no orphan leads remain
SELECT COUNT(*) AS remaining_orphans
FROM leads l
LEFT JOIN lead_campaigns lc ON l.campaign_id = lc.id
WHERE lc.id IS NULL;
-- Should return 0

-- Verify no orphan emails remain
SELECT COUNT(*) AS orphan_emails
FROM lead_emails e
LEFT JOIN leads l ON e.lead_id = l.id
WHERE l.id IS NULL;
-- Should return 0

-- Show campaign distribution
SELECT
    lc.id,
    lc.name,
    lc.is_core,
    COUNT(l.id) AS lead_count
FROM lead_campaigns lc
LEFT JOIN leads l ON lc.id = l.campaign_id
GROUP BY lc.id, lc.name, lc.is_core
ORDER BY lc.id;


-- =================================================================
-- Step 8: Safe Approach - Reassign Orphan Leads to Default Campaign
-- =================================================================

-- Alternative to deletion: Create a "Miscellaneous" campaign and reassign orphans

/*
-- Create a catch-all campaign
INSERT INTO lead_campaigns
(name, industry_service, location, status, is_core, created_at, updated_at)
VALUES
('Miscellaneous Leads', 'general', 'United States', 'paused', 0, NOW(), NOW());

-- Get the ID of the new campaign
SET @misc_campaign_id = LAST_INSERT_ID();

-- Reassign orphan leads to this campaign
UPDATE leads l
LEFT JOIN lead_campaigns lc ON l.campaign_id = lc.id
SET l.campaign_id = @misc_campaign_id
WHERE lc.id IS NULL;
*/


-- =================================================================
-- RECOMMENDED WORKFLOW
-- =================================================================

/*
1. Run Step 1-3 queries to IDENTIFY orphan records
2. Review the results - decide if you want to delete or reassign
3. If deleting:
   - Uncomment Step 4 backup creation
   - Run backup
   - Uncomment Step 4 deletion
   - Run deletion
4. If reassigning:
   - Use Step 8 to create miscellaneous campaign
   - Reassign orphans
5. Run Step 7 verification queries
6. Proceed with CREATE_20_CORE_CAMPAIGNS.sql
*/


-- =================================================================
-- Notes
-- =================================================================

/*
ABOUT CASCADE DELETION:
The SQLAlchemy models have cascade="all, delete-orphan" which means:
- When a campaign is deleted, all its leads are deleted
- When a lead is deleted, all its emails are deleted
- This is enforced at the ORM level

However, if you're doing direct SQL operations (not through Flask),
you need to ensure your database has proper foreign key constraints
with ON DELETE CASCADE.

PREVENTING FUTURE ORPHANS:
1. Always create campaigns before leads
2. Never delete campaigns that have leads (or accept that leads will be deleted)
3. Use the ORM (SQLAlchemy) for deletions to ensure cascade works
4. Regularly run Step 1-3 queries to check for orphans

SAFE OPERATION ORDER:
1. Run MIGRATION_AUTOMATION.sql (adds is_core column)
2. Run this cleanup script (check and fix orphans)
3. Run CREATE_20_CORE_CAMPAIGNS.sql (create core campaigns)
4. Use the automation system to scrape leads
*/
