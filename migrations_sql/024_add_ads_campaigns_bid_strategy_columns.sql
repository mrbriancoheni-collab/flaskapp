-- Migration 024: Add bid_strategy, target_cpa_micros, target_roas to ads_campaigns
-- These columns are defined in the AdsCampaign SQLAlchemy model but missing from the table.

ALTER TABLE ads_campaigns
  ADD COLUMN IF NOT EXISTS bid_strategy VARCHAR(32) NULL DEFAULT 'manual_cpc',
  ADD COLUMN IF NOT EXISTS target_cpa_micros BIGINT NULL,
  ADD COLUMN IF NOT EXISTS target_roas FLOAT NULL;
