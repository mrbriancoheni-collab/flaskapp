-- Add max_cpc_cents column to ad_groups table
-- This column stores the maximum cost-per-click in cents for ad groups

ALTER TABLE ad_groups ADD COLUMN max_cpc_cents INT DEFAULT NULL AFTER status;
