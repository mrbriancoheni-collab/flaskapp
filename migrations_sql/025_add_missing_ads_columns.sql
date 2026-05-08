-- Migration 025: Add missing columns to ads_campaigns and ads tables
-- These columns are defined in SQLAlchemy models but were never migrated.

-- ads_campaigns: budget group assignment
ALTER TABLE ads_campaigns
  ADD COLUMN IF NOT EXISTS budget_group_id INT NULL;

-- ads: A/B testing columns
ALTER TABLE ads
  ADD COLUMN IF NOT EXISTS variant_group VARCHAR(64) NULL,
  ADD COLUMN IF NOT EXISTS is_control TINYINT(1) NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS test_name VARCHAR(128) NULL;

-- Optional index for A/B test lookups
CREATE INDEX IF NOT EXISTS ix_ads_variant_group ON ads (variant_group);
