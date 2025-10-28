-- Rollback: Remove domain crawl tracking from CRM contacts
-- Date: 2025-10-28

-- Remove index first
ALTER TABLE crm_contacts DROP INDEX idx_crm_contacts_last_crawled;

-- Remove columns
ALTER TABLE crm_contacts
    DROP COLUMN last_crawled_at,
    DROP COLUMN crawl_attempts;
