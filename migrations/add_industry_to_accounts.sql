-- Migration: Add industry column to accounts table
-- Purpose: Support vertical-specific language detection (plumbing, HVAC, pest control, etc.)
-- Date: 2026-01-07

-- Add industry column
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS industry VARCHAR(100);

-- Optional: Set some default industries for existing accounts based on their business
-- UPDATE accounts SET industry = 'plumbing' WHERE name ILIKE '%plumb%';
-- UPDATE accounts SET industry = 'hvac' WHERE name ILIKE '%hvac%' OR name ILIKE '%heating%' OR name ILIKE '%cooling%';
-- UPDATE accounts SET industry = 'pest control' WHERE name ILIKE '%pest%';
-- UPDATE accounts SET industry = 'electrical' WHERE name ILIKE '%electric%';
-- UPDATE accounts SET industry = 'landscaping' WHERE name ILIKE '%landscape%' OR name ILIKE '%lawn%';

-- Verify the column was added
-- SELECT id, name, industry FROM accounts LIMIT 5;
