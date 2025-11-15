-- Migration 015 Rollback: Remove Interactive Tutorial Popup Tables

-- Drop triggers
DROP TRIGGER IF EXISTS tutorial_popups_updated_at_trigger ON tutorial_popups;

-- Drop functions
DROP FUNCTION IF EXISTS update_tutorial_popups_updated_at();

-- Drop tables (order matters due to foreign keys)
DROP TABLE IF EXISTS tutorial_user_progress;
DROP TABLE IF EXISTS tutorial_popups;
