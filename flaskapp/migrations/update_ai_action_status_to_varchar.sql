-- Migration: Expand ai_actions.status from ENUM to VARCHAR(20)
-- Allows new values: pending_review, dismissed
-- Safe to run multiple times (idempotent via column type check)

ALTER TABLE ai_actions
  MODIFY COLUMN status VARCHAR(20) NOT NULL DEFAULT 'pending';

-- Add shareable_token to google_ads_grader_reports (nullable, unique)
ALTER TABLE google_ads_grader_reports
  ADD COLUMN IF NOT EXISTS shareable_token VARCHAR(64) NULL DEFAULT NULL,
  ADD UNIQUE INDEX IF NOT EXISTS uq_grader_shareable_token (shareable_token);

-- Create account_settings table if not exists
CREATE TABLE IF NOT EXISTS account_settings (
  id          INT UNSIGNED NOT NULL AUTO_INCREMENT,
  account_id  INT NOT NULL,
  setting_key VARCHAR(100) NOT NULL,
  setting_value TEXT,
  created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_account_setting (account_id, setting_key),
  KEY idx_account_settings_account (account_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
