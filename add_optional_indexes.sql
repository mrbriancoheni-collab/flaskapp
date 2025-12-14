-- Optional performance indexes for FieldSprout
-- Run this ONLY AFTER you've connected the respective integrations
-- These tables are created dynamically when you connect each integration

-- Facebook Tokens (run after connecting Facebook)
-- Uncomment and run after first Facebook Ads connection:
-- CREATE INDEX IF NOT EXISTS idx_facebook_tokens_account
--     ON facebook_tokens(account_id);
-- CREATE INDEX IF NOT EXISTS idx_facebook_tokens_expires
--     ON facebook_tokens(expires_at);

-- Facebook Selected Accounts (run after selecting Facebook ad account)
-- Uncomment and run after selecting an ad account:
-- CREATE INDEX IF NOT EXISTS idx_facebook_selected_accounts
--     ON facebook_selected_accounts(account_id);

-- GLSA Accounts (run after connecting Local Services Ads)
-- Uncomment and run if using Local Services Ads:
-- CREATE INDEX IF NOT EXISTS idx_glsa_accounts_account_updated
--     ON glsa_accounts(account_id, updated_at DESC);

-- WordPress Connections (run after connecting WordPress)
-- Uncomment and run if using WordPress integration:
-- CREATE INDEX IF NOT EXISTS idx_wp_connections_account
--     ON wp_connections(account_id);

-- LinkedIn Connections (run after connecting LinkedIn)
-- Uncomment and run if using LinkedIn integration:
-- CREATE INDEX IF NOT EXISTS idx_linkedin_tokens_account
--     ON linkedin_tokens(account_id);

-- Yelp Connections (run after connecting Yelp)
-- Uncomment and run if using Yelp integration:
-- CREATE INDEX IF NOT EXISTS idx_yelp_accounts_account
--     ON yelp_accounts(account_id);

SELECT 'Optional indexes file loaded. Uncomment and run indexes for integrations you are using.' as instructions;
