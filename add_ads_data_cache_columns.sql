-- Add columns to cache Google Ads data in database
-- Prevents session cookie overflow and reduces API calls

ALTER TABLE accounts
ADD COLUMN IF NOT EXISTS ads_data_cache LONGTEXT NULL COMMENT 'Cached Google Ads data as JSON',
ADD COLUMN IF NOT EXISTS ads_data_cached_at DATETIME NULL COMMENT 'When ads_data was last cached';

-- Add index for faster cache lookups
CREATE INDEX IF NOT EXISTS idx_accounts_ads_cache_time
ON accounts(id, ads_data_cached_at);
