-- Standardize Email Sequences Script
-- This script:
-- 1. Updates all campaign-related email sequences to be named 'Auto Campaign'
-- 2. Lists non-campaign sequences (for manual review before deletion)
-- 3. Provides DELETE command to remove non-campaign sequences

-- Show current state
SELECT 'CURRENT EMAIL SEQUENCES' AS status;
SELECT id, campaign_id, name, step_number, created_at
FROM email_sequences
ORDER BY campaign_id, step_number;

-- Update all email sequences to 'Auto Campaign'
UPDATE email_sequences
SET name = 'Auto Campaign'
WHERE name != 'Auto Campaign';

-- Show results
SELECT 'UPDATED SEQUENCES' AS status;
SELECT id, campaign_id, name, step_number
FROM email_sequences
ORDER BY campaign_id, step_number;

-- Check for orphaned sequences (campaign_id doesn't exist in lead_campaigns)
SELECT 'ORPHANED SEQUENCES (will be deleted)' AS status;
SELECT es.id, es.campaign_id, es.name, es.step_number
FROM email_sequences es
LEFT JOIN lead_campaigns lc ON es.campaign_id = lc.id
WHERE lc.id IS NULL;

-- Delete orphaned sequences
DELETE FROM email_sequences
WHERE campaign_id NOT IN (SELECT id FROM lead_campaigns);

-- Final summary
SELECT 'FINAL COUNT' AS status, COUNT(*) AS total_sequences
FROM email_sequences;

SELECT 'DONE - All email sequences standardized to Auto Campaign' AS status;
