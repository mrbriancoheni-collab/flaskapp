-- Add google_ad_group_id column to ad_groups table
-- This column stores the Google Ads API ad group ID for syncing

ALTER TABLE ad_groups ADD COLUMN google_ad_group_id VARCHAR(64) DEFAULT NULL AFTER max_cpc_cents;
CREATE INDEX idx_ad_groups_google_ad_group_id ON ad_groups(google_ad_group_id);
