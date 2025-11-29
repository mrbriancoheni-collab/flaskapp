-- Add google_keyword_id column to keywords table
-- This column stores the Google Ads API keyword ID for syncing

ALTER TABLE keywords ADD COLUMN google_keyword_id VARCHAR(64) DEFAULT NULL AFTER max_cpc_cents;
CREATE INDEX idx_keywords_google_keyword_id ON keywords(google_keyword_id);
