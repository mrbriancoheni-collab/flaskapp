-- Add max_cpc_cents column to keywords table
-- This column stores the maximum cost-per-click in cents for keywords

ALTER TABLE keywords ADD COLUMN max_cpc_cents INT DEFAULT NULL AFTER status;
