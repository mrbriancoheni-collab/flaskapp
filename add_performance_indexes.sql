-- Performance optimization indexes for FieldSprout
-- Run this SQL to drastically improve query performance

-- Google OAuth Tokens - most frequently queried table
CREATE INDEX IF NOT EXISTS idx_google_oauth_account_product
    ON google_oauth_tokens(account_id, product, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_google_oauth_account
    ON google_oauth_tokens(account_id);

-- Facebook Tokens
CREATE INDEX IF NOT EXISTS idx_facebook_tokens_account
    ON facebook_tokens(account_id);

CREATE INDEX IF NOT EXISTS idx_fb_tokens_account_refreshed
    ON fb_tokens(account_id, refreshed_at DESC);

-- Facebook Selected Accounts
CREATE INDEX IF NOT EXISTS idx_facebook_selected_accounts
    ON facebook_selected_accounts(account_id);

-- GLSA Accounts
CREATE INDEX IF NOT EXISTS idx_glsa_accounts_account_updated
    ON glsa_accounts(account_id, updated_at DESC);

-- WordPress Connections (if table exists)
CREATE INDEX IF NOT EXISTS idx_wp_connections_account
    ON wp_connections(account_id);

-- User accounts (if not already indexed)
CREATE INDEX IF NOT EXISTS idx_users_email
    ON users(email);

-- Optimize common date range queries
CREATE INDEX IF NOT EXISTS idx_google_oauth_expiry
    ON google_oauth_tokens(token_expiry)
    WHERE token_expiry IS NOT NULL;

SELECT 'Performance indexes created successfully!' as status;
