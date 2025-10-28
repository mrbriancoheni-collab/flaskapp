-- Migration: Add domain crawl tracking to CRM contacts
-- Date: 2025-10-28
-- Description: Adds last_crawled_at and crawl_attempts fields to track website crawling for lead enrichment

ALTER TABLE crm_contacts
    ADD COLUMN last_crawled_at DATETIME NULL COMMENT 'Timestamp of last domain crawl',
    ADD COLUMN crawl_attempts INT NOT NULL DEFAULT 0 COMMENT 'Number of domain crawl attempts';

-- Add index for efficient querying of crawl candidates
ALTER TABLE crm_contacts
    ADD INDEX idx_crm_contacts_last_crawled (last_crawled_at);

-- Rollback script saved in 005_add_crm_domain_crawl_tracking_rollback.sql
