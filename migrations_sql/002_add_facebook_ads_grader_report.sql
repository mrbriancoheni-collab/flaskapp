-- Migration: Add facebook_ads_grader_reports table
-- Created: 2025-10-26
-- Description: Creates table for storing Facebook Ads Performance Grader reports

CREATE TABLE IF NOT EXISTS `facebook_ads_grader_reports` (
  `id` BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,

  -- Account associations
  `account_id` INT NULL,
  `user_id` INT NULL,

  -- Facebook Ads Account Info
  `fb_ad_account_id` VARCHAR(128) NOT NULL,
  `fb_ad_account_name` VARCHAR(255) NULL,
  `fb_business_id` VARCHAR(128) NULL,
  `fb_business_name` VARCHAR(255) NULL,
  `currency` VARCHAR(10) NULL,

  -- Overall scores
  `overall_score` FLOAT NOT NULL,
  `overall_grade` VARCHAR(3) NULL,

  -- Key metrics
  `ctr_avg` FLOAT NULL,
  `cpc_avg` FLOAT NULL,
  `cpm_avg` FLOAT NULL,
  `relevance_score_avg` FLOAT NULL,
  `roas_avg` FLOAT NULL,
  `conversion_rate_avg` FLOAT NULL,
  `wasted_spend_365d` FLOAT NULL,
  `projected_waste_12m` FLOAT NULL,

  -- Account diagnostics (365 days of historical data)
  `active_campaigns` INT DEFAULT 0,
  `active_ad_sets` INT DEFAULT 0,
  `active_ads` INT DEFAULT 0,
  `total_audiences` INT DEFAULT 0,
  `clicks_365d` INT DEFAULT 0,
  `impressions_365d` BIGINT DEFAULT 0,
  `conversions_365d` INT DEFAULT 0,
  `spend_365d` FLOAT DEFAULT 0,
  `revenue_365d` FLOAT DEFAULT 0,
  `avg_monthly_spend` FLOAT NULL,

  -- Section scores (0-100) - 12 performance categories
  `wasted_spend_score` FLOAT NULL,
  `creative_optimization_score` FLOAT NULL,
  `audience_targeting_score` FLOAT NULL,
  `relevance_score_optimization_score` FLOAT NULL,
  `ctr_optimization_score` FLOAT NULL,
  `account_activity_score` FLOAT NULL,
  `ad_format_diversity_score` FLOAT NULL,
  `campaign_structure_score` FLOAT NULL,
  `landing_page_score` FLOAT NULL,
  `mobile_optimization_score` FLOAT NULL,
  `conversion_tracking_score` FLOAT NULL,
  `roas_score` FLOAT NULL,

  -- Detailed data (JSON columns)
  `detailed_metrics` JSON NULL COMMENT '365 days of comprehensive Facebook Ads data including campaign, ad set, ad, placement, and device performance',
  `best_practices` JSON NULL COMMENT 'Checklist of Facebook Ads best practices',
  `recommendations` JSON NULL COMMENT 'Actionable recommendations based on analysis',

  -- Report metadata
  `report_date` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `date_range_start` DATETIME NULL,
  `date_range_end` DATETIME NULL,

  -- Tracking
  `pdf_download_count` INT NOT NULL DEFAULT 0,

  -- Timestamps
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  -- Indexes for performance
  INDEX `idx_account_id` (`account_id`),
  INDEX `idx_user_id` (`user_id`),
  INDEX `idx_fb_ad_account_id` (`fb_ad_account_id`),
  INDEX `idx_overall_score` (`overall_score`),
  INDEX `idx_created_at` (`created_at`),
  INDEX `idx_report_date` (`report_date`),

  -- Foreign keys (if accounts/users tables exist)
  CONSTRAINT `fk_fb_grader_account`
    FOREIGN KEY (`account_id`)
    REFERENCES `accounts` (`id`)
    ON DELETE SET NULL,

  CONSTRAINT `fk_fb_grader_user`
    FOREIGN KEY (`user_id`)
    REFERENCES `users` (`id`)
    ON DELETE SET NULL

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Add table comment
ALTER TABLE `facebook_ads_grader_reports`
  COMMENT = 'Stores Facebook Ads Performance Grader analysis reports with 365 days of historical data';

-- Note: This table uses BIGINT UNSIGNED for id to support large-scale data storage
-- The detailed_metrics JSON field stores comprehensive 365-day historical data including:
--   - Account performance metrics
--   - Campaign-level data
--   - Ad set performance
--   - Individual ad data
--   - Creative performance
--   - Placement breakdowns (Feed, Stories, Reels, etc.)
--   - Device performance (mobile vs desktop)
--   - Audience insights
