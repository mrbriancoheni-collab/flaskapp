-- Migration: Add Performance Indexes
-- Date: 2025-12-05
-- Description: Add indexes to improve query performance across the application

-- Accounts table indexes
ALTER TABLE accounts
ADD INDEX IF NOT EXISTS idx_stripe_status (stripe_status),
ADD INDEX IF NOT EXISTS idx_plan (plan),
ADD INDEX IF NOT EXISTS idx_active (active);

-- Users table indexes
ALTER TABLE users
ADD INDEX IF NOT EXISTS idx_account_id (account_id),
ADD INDEX IF NOT EXISTS idx_email (email),
ADD INDEX IF NOT EXISTS idx_active (active);

-- Google OAuth tokens (frequently queried)
ALTER TABLE google_oauth_tokens
ADD INDEX IF NOT EXISTS idx_account_product (account_id, product),
ADD INDEX IF NOT EXISTS idx_token_expiry (token_expiry);

-- Lead campaigns (heavily used)
ALTER TABLE lead_campaigns
ADD INDEX IF NOT EXISTS idx_status (status),
ADD INDEX IF NOT EXISTS idx_created_at (created_at),
ADD INDEX IF NOT EXISTS idx_campaign_status (campaign_name, status);

-- Leads table (large table, needs good indexes)
ALTER TABLE leads
ADD INDEX IF NOT EXISTS idx_campaign_enrichment (campaign_id, enrichment_status),
ADD INDEX IF NOT EXISTS idx_email_sent (email_sent_at),
ADD INDEX IF NOT EXISTS idx_created_at (created_at);

-- Lead contacts (person-level data)
ALTER TABLE lead_contacts
ADD INDEX IF NOT EXISTS idx_lead_id (lead_id),
ADD INDEX IF NOT EXISTS idx_email (email),
ADD INDEX IF NOT EXISTS idx_phone (phone);

-- Lead emails (tracking)
ALTER TABLE lead_emails
ADD INDEX IF NOT EXISTS idx_lead_sent (lead_id, sent_at),
ADD INDEX IF NOT EXISTS idx_status (status);

-- Lead contact emails (new tracking system)
ALTER TABLE lead_contact_emails
ADD INDEX IF NOT EXISTS idx_contact_sent (lead_contact_id, sent_at),
ADD INDEX IF NOT EXISTS idx_status (status);

-- CRM contacts (if table exists)
-- Uncomment if you have these tables
-- ALTER TABLE crm_contacts
-- ADD INDEX IF NOT EXISTS idx_account_stage (account_id, stage),
-- ADD INDEX IF NOT EXISTS idx_created_at (created_at);

-- ALTER TABLE company_contacts
-- ADD INDEX IF NOT EXISTS idx_crm_contact (crm_contact_id),
-- ADD INDEX IF NOT EXISTS idx_email (email);

-- WordPress sites
ALTER TABLE wp_sites
ADD INDEX IF NOT EXISTS idx_account_id (account_id);

-- Facebook tokens
ALTER TABLE fb_tokens
ADD INDEX IF NOT EXISTS idx_account_id (account_id),
ADD INDEX IF NOT EXISTS idx_refreshed_at (refreshed_at);

-- Add composite indexes for common join patterns
ALTER TABLE leads
ADD INDEX IF NOT EXISTS idx_campaign_status_created (campaign_id, enrichment_status, created_at);

ALTER TABLE lead_campaigns
ADD INDEX IF NOT EXISTS idx_active_campaigns (status, created_at, id);

-- Verify indexes were created
SELECT
    TABLE_NAME,
    INDEX_NAME,
    COLUMN_NAME,
    SEQ_IN_INDEX
FROM information_schema.STATISTICS
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME IN ('accounts', 'users', 'leads', 'lead_campaigns', 'lead_contacts')
  AND INDEX_NAME LIKE 'idx_%'
ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX;
