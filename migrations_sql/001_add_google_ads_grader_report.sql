-- Migration: Add google_ads_grader_reports table
-- Created: 2025-10-25
-- Description: Creates table for storing Google Ads Quality Checker reports

CREATE TABLE IF NOT EXISTS `google_ads_grader_reports` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,

  -- Account associations
  `account_id` INT NULL,
  `user_id` INT NULL,
  `google_ads_customer_id` VARCHAR(20) NOT NULL,
  `google_ads_account_name` VARCHAR(255) NULL,

  -- Overall scores
  `overall_score` FLOAT NOT NULL,
  `overall_grade` VARCHAR(2) NULL,

  -- Key metrics
  `quality_score_avg` FLOAT NULL,
  `ctr_avg` FLOAT NULL,
  `wasted_spend_90d` FLOAT NULL,
  `projected_waste_12m` FLOAT NULL,

  -- Account diagnostics
  `active_campaigns` INT NULL,
  `active_ad_groups` INT NULL,
  `active_text_ads` INT NULL,
  `active_keywords` INT NULL,
  `clicks_90d` INT NULL,
  `conversions_90d` INT NULL,
  `avg_cpa_90d` FLOAT NULL,
  `avg_monthly_spend` FLOAT NULL,

  -- Section scores (0-100)
  `wasted_spend_score` FLOAT NULL,
  `expanded_text_ads_score` FLOAT NULL,
  `text_ad_optimization_score` FLOAT NULL,
  `quality_score_optimization_score` FLOAT NULL,
  `ctr_optimization_score` FLOAT NULL,
  `account_activity_score` FLOAT NULL,
  `long_tail_keywords_score` FLOAT NULL,
  `impression_share_score` FLOAT NULL,
  `landing_page_score` FLOAT NULL,
  `mobile_advertising_score` FLOAT NULL,

  -- Detailed data (JSON columns)
  `detailed_metrics` JSON NULL,
  `best_practices` JSON NULL,
  `recommendations` JSON NULL,

  -- Report metadata
  `report_date` DATETIME NULL,
  `date_range_start` DATE NULL,
  `date_range_end` DATE NULL,

  -- Timestamps
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  -- Tracking
  `view_count` INT NOT NULL DEFAULT 0,
  `pdf_download_count` INT NOT NULL DEFAULT 0,

  -- Indexes
  INDEX `idx_account_id` (`account_id`),
  INDEX `idx_user_id` (`user_id`),
  INDEX `idx_customer_id` (`google_ads_customer_id`),
  INDEX `idx_created_at` (`created_at`),

  -- Foreign keys (if accounts/users tables exist)
  CONSTRAINT `fk_grader_account`
    FOREIGN KEY (`account_id`)
    REFERENCES `accounts` (`id`)
    ON DELETE SET NULL,

  CONSTRAINT `fk_grader_user`
    FOREIGN KEY (`user_id`)
    REFERENCES `users` (`id`)
    ON DELETE SET NULL

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Add some helpful comments
ALTER TABLE `google_ads_grader_reports`
  COMMENT = 'Stores Google Ads Quality Checker analysis reports';
