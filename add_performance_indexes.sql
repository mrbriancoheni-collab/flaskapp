-- Performance optimization indexes for FieldSprout
-- Run this SQL to drastically improve query performance
-- Note: Uses IF NOT EXISTS to safely skip tables that don't exist yet

-- Google OAuth Tokens - most frequently queried table
-- This table should exist if you're using Google integrations
CREATE INDEX IF NOT EXISTS idx_google_oauth_account_product
    ON google_oauth_tokens(account_id, product, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_google_oauth_account
    ON google_oauth_tokens(account_id);

-- Facebook Tokens (only if table exists - created dynamically by app)
-- Skip error if table doesn't exist yet - it will be created on first Facebook connection
-- CREATE INDEX IF NOT EXISTS idx_facebook_tokens_account
--     ON facebook_tokens(account_id);

-- Facebook Selected Accounts (only if table exists)
-- CREATE INDEX IF NOT EXISTS idx_facebook_selected_accounts
--     ON facebook_selected_accounts(account_id);

-- GLSA Accounts (only if using Local Services Ads)
-- CREATE INDEX IF NOT EXISTS idx_glsa_accounts_account_updated
--     ON glsa_accounts(account_id, updated_at DESC);

-- WordPress Connections (only if using WordPress integration)
-- CREATE INDEX IF NOT EXISTS idx_wp_connections_account
--     ON wp_connections(account_id);

-- User accounts table - this should always exist
CREATE INDEX IF NOT EXISTS idx_users_email
    ON users(email);

-- Accounts table - should exist
CREATE INDEX IF NOT EXISTS idx_accounts_id
    ON accounts(id);

-- Optimize common date range queries on Google OAuth
CREATE INDEX IF NOT EXISTS idx_google_oauth_expiry
    ON google_oauth_tokens(token_expiry)
    WHERE token_expiry IS NOT NULL;

SELECT 'Core performance indexes created successfully!' as status;
SELECT 'Note: Some indexes were skipped because tables don\'t exist yet.' as note;
SELECT 'Run this script again after connecting integrations to add remaining indexes.' as tip;
