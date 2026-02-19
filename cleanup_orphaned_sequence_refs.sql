-- ============================================================================
-- Cleanup Orphaned lead_emails_sent Records
-- ============================================================================
-- Removes lead_emails_sent rows whose sequence_id no longer exists in
-- email_sequences (left over after sequences were manually deleted).
-- ============================================================================

-- Preview: how many orphaned records exist
SELECT COUNT(*) AS orphaned_count
FROM lead_emails_sent le
LEFT JOIN email_sequences es ON le.sequence_id = es.id
WHERE es.id IS NULL;

-- Delete orphaned records
DELETE le
FROM lead_emails_sent le
LEFT JOIN email_sequences es ON le.sequence_id = es.id
WHERE es.id IS NULL;

-- Verify: should return 0
SELECT COUNT(*) AS remaining_orphans
FROM lead_emails_sent le
LEFT JOIN email_sequences es ON le.sequence_id = es.id
WHERE es.id IS NULL;
