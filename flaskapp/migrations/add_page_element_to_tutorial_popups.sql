-- Migration: Add page_element column to tutorial_popups table
-- This column stores the CSS selector to highlight during tutorials

-- Add page_element column if it doesn't exist
ALTER TABLE tutorial_popups
ADD COLUMN IF NOT EXISTS page_element VARCHAR(500) DEFAULT NULL
COMMENT 'CSS selector to highlight during tutorial (optional)';

-- For MySQL (doesn't support IF NOT EXISTS in ALTER TABLE ADD COLUMN)
-- Use this alternative if the above doesn't work:
-- ALTER TABLE tutorial_popups ADD COLUMN page_element VARCHAR(500) DEFAULT NULL COMMENT 'CSS selector to highlight during tutorial (optional)';
