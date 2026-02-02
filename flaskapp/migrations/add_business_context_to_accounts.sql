-- Add business context columns to accounts table for AI agent use
-- These columns allow agents to understand what each business does
-- so they can make intelligent negative keyword decisions.

ALTER TABLE accounts
  ADD COLUMN IF NOT EXISTS business_description TEXT DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS business_services TEXT DEFAULT NULL;
