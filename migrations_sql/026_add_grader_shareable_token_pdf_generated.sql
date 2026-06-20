-- Migration 026: Add missing columns to google_ads_grader_reports
-- Created: 2026-06-20
-- Safe to run multiple times (ADD COLUMN IF NOT EXISTS)
--
-- Adds:
--   shareable_token  VARCHAR(64)  NULL  UNIQUE  — public share links
--   pdf_generated    TINYINT(1)   NOT NULL DEFAULT 0  — PDF export tracking

ALTER TABLE `google_ads_grader_reports`
  ADD COLUMN IF NOT EXISTS `shareable_token` VARCHAR(64) NULL DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS `pdf_generated`   TINYINT(1) NOT NULL DEFAULT 0;

-- Unique index on shareable_token (skip if already exists)
-- MySQL 8.0+: CREATE INDEX IF NOT EXISTS is supported
CREATE UNIQUE INDEX IF NOT EXISTS `uq_grader_shareable_token`
  ON `google_ads_grader_reports` (`shareable_token`);
