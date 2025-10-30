-- ============================================================================
-- Migration: Add google_ads_ai_analysis_tracker table for rate limiting
-- Database: MySQL
-- Created: 2025-10-30
-- ============================================================================

-- Create google_ads_ai_analysis_tracker table
CREATE TABLE IF NOT EXISTS `google_ads_ai_analysis_tracker` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `google_ads_customer_id` VARCHAR(20) NOT NULL UNIQUE COMMENT 'Google Ads customer ID',

  -- Last analysis tracking
  `last_analysis_at` DATETIME DEFAULT NULL COMMENT 'When last AI analysis was run',
  `analysis_count_current_month` INT NOT NULL DEFAULT 0 COMMENT 'Number of analyses this month',
  `analysis_count_total` INT NOT NULL DEFAULT 0 COMMENT 'Total analyses ever',

  -- Month tracking (to reset monthly count)
  `current_month_year` VARCHAR(7) DEFAULT NULL COMMENT 'Current month in YYYY-MM format',

  -- Tracking
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  PRIMARY KEY (`id`),
  UNIQUE INDEX `uq_customer_id` (`google_ads_customer_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Tracks AI analysis usage per Google Ads customer for rate limiting (1 per month for free users)';

-- ============================================================================
-- Verify migration
-- ============================================================================
SELECT 'google_ads_ai_analysis_tracker table created successfully' AS status;
SHOW CREATE TABLE `google_ads_ai_analysis_tracker`;

-- ============================================================================
-- Sample usage (optional - for testing)
-- ============================================================================

-- Record first analysis for a customer
-- INSERT INTO google_ads_ai_analysis_tracker (
--   google_ads_customer_id, last_analysis_at, analysis_count_current_month,
--   analysis_count_total, current_month_year
-- ) VALUES (
--   '123-456-7890', NOW(), 1, 1, '2025-10'
-- );

-- Check if customer can run analysis
-- SELECT
--   google_ads_customer_id,
--   analysis_count_current_month,
--   current_month_year,
--   last_analysis_at,
--   CASE
--     WHEN current_month_year = DATE_FORMAT(NOW(), '%Y-%m') AND analysis_count_current_month >= 1
--     THEN 'BLOCKED - Limit Reached'
--     ELSE 'ALLOWED'
--   END AS status
-- FROM google_ads_ai_analysis_tracker
-- WHERE google_ads_customer_id = '123-456-7890';

-- Get usage stats
-- SELECT
--   COUNT(*) AS total_customers,
--   SUM(analysis_count_current_month) AS analyses_this_month,
--   SUM(analysis_count_total) AS total_analyses_ever,
--   AVG(analysis_count_total) AS avg_analyses_per_customer
-- FROM google_ads_ai_analysis_tracker;

-- ============================================================================
-- Rollback (if needed)
-- ============================================================================
-- DROP TABLE IF EXISTS `google_ads_ai_analysis_tracker`;
