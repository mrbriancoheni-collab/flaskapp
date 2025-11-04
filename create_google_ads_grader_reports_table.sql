-- Migration: Create google_ads_grader_reports table
-- Database: fieljtgr_xyz
-- Date: 2025-11-03

CREATE TABLE IF NOT EXISTS `google_ads_grader_reports` (
  `id` INT NOT NULL AUTO_INCREMENT PRIMARY KEY,

  -- Account links (optional - can run without account)
  `account_id` INT DEFAULT NULL,
  `user_id` INT DEFAULT NULL,

  -- Google Ads account info
  `google_ads_customer_id` VARCHAR(20) NOT NULL,
  `google_ads_account_name` VARCHAR(255) DEFAULT NULL,

  -- Overall score
  `overall_score` FLOAT NOT NULL,
  `overall_grade` VARCHAR(2) DEFAULT NULL,

  -- Key metrics
  `quality_score_avg` FLOAT DEFAULT NULL,
  `ctr_avg` FLOAT DEFAULT NULL,
  `wasted_spend_90d` FLOAT DEFAULT NULL,
  `projected_waste_12m` FLOAT DEFAULT NULL,

  -- Account diagnostics
  `active_campaigns` INT DEFAULT NULL,
  `active_ad_groups` INT DEFAULT NULL,
  `active_text_ads` INT DEFAULT NULL,
  `active_keywords` INT DEFAULT NULL,
  `clicks_90d` INT DEFAULT NULL,
  `conversions_90d` INT DEFAULT NULL,
  `avg_cpa_90d` FLOAT DEFAULT NULL,
  `avg_monthly_spend` FLOAT DEFAULT NULL,

  -- Section scores (0-100)
  `wasted_spend_score` FLOAT DEFAULT NULL,
  `expanded_text_ads_score` FLOAT DEFAULT NULL,
  `text_ad_optimization_score` FLOAT DEFAULT NULL,
  `quality_score_optimization_score` FLOAT DEFAULT NULL,
  `ctr_optimization_score` FLOAT DEFAULT NULL,
  `account_activity_score` FLOAT DEFAULT NULL,
  `long_tail_keywords_score` FLOAT DEFAULT NULL,
  `impression_share_score` FLOAT DEFAULT NULL,
  `landing_page_score` FLOAT DEFAULT NULL,
  `mobile_advertising_score` FLOAT DEFAULT NULL,

  -- Detailed data (JSON)
  `detailed_metrics` JSON DEFAULT NULL,
  `best_practices` JSON DEFAULT NULL,
  `recommendations` JSON DEFAULT NULL,

  -- Report metadata
  `report_date` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `date_range_start` DATETIME DEFAULT NULL,
  `date_range_end` DATETIME DEFAULT NULL,

  -- Tracking
  `pdf_generated` TINYINT(1) NOT NULL DEFAULT 0,
  `pdf_download_count` INT NOT NULL DEFAULT 0,

  -- Timestamps
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  -- Indexes
  INDEX `idx_account_id` (`account_id`),
  INDEX `idx_user_id` (`user_id`),
  INDEX `idx_google_ads_customer_id` (`google_ads_customer_id`)

  -- Foreign keys removed to avoid constraint errors
  -- Add them manually later if needed:
  -- CONSTRAINT `fk_google_ads_grader_reports_account`
  --   FOREIGN KEY (`account_id`) REFERENCES `accounts` (`id`) ON DELETE CASCADE,
  -- CONSTRAINT `fk_google_ads_grader_reports_user`
  --   FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
