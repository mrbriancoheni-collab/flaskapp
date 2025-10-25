-- ============================================================================
-- Migration: Add PerformanceMetrics table for unified metrics storage
-- Database: MySQL
-- Created: 2025-10-23
-- ============================================================================

-- Create performance_metrics table
CREATE TABLE IF NOT EXISTS `performance_metrics` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `account_id` BIGINT NOT NULL,

  -- Source identification
  `source_type` VARCHAR(32) NOT NULL COMMENT 'google_ads, google_analytics, search_console, glsa, gmb, fbads',
  `source_id` VARCHAR(255) DEFAULT NULL COMMENT 'Property ID, Site URL, Customer ID, Page ID, etc.',

  -- Time dimension
  `date` DATE NOT NULL,
  `timeframe` VARCHAR(16) NOT NULL DEFAULT 'daily' COMMENT 'daily, weekly, monthly',

  -- Entity hierarchy (optional, for drilldown)
  `entity_type` VARCHAR(32) DEFAULT NULL COMMENT 'account, campaign, ad_group, ad, keyword, page, etc.',
  `entity_id` VARCHAR(255) DEFAULT NULL,
  `entity_name` VARCHAR(255) DEFAULT NULL,

  -- Core metrics (flexible JSON blob for source-specific metrics)
  `metrics_json` TEXT NOT NULL COMMENT 'JSON object with all metrics',

  -- Computed aggregates (for quick queries without parsing JSON)
  `impressions` BIGINT DEFAULT NULL,
  `clicks` BIGINT DEFAULT NULL,
  `spend` DECIMAL(10,2) DEFAULT NULL COMMENT 'In dollars',
  `conversions` DECIMAL(10,2) DEFAULT NULL,

  -- Audit fields
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  PRIMARY KEY (`id`),

  -- Unique constraint: one record per account/source/entity/date
  UNIQUE KEY `uq_perf_metrics` (
    `account_id`, `source_type`, `source_id`, `entity_type`, `entity_id`, `date`, `timeframe`
  ),

  -- Indexes for common queries
  INDEX `ix_perf_account_source_date` (`account_id`, `source_type`, `date`),
  INDEX `ix_perf_source_entity_date` (`source_type`, `entity_type`, `date`),
  INDEX `ix_perf_account_id` (`account_id`),
  INDEX `ix_perf_source_type` (`source_type`),
  INDEX `ix_perf_source_id` (`source_id`),
  INDEX `ix_perf_entity_type` (`entity_type`),
  INDEX `ix_perf_entity_id` (`entity_id`),
  INDEX `ix_perf_date` (`date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Unified storage for historical performance metrics across all platforms';

-- ============================================================================
-- Verify migration
-- ============================================================================
SELECT 'Table created successfully' AS status;
SHOW CREATE TABLE `performance_metrics`;

-- ============================================================================
-- Sample usage (optional - for testing)
-- ============================================================================

-- Insert sample Google Ads metrics
-- INSERT INTO performance_metrics (
--   account_id, source_type, source_id, entity_type, entity_id, entity_name,
--   date, timeframe, metrics_json, impressions, clicks, spend, conversions
-- ) VALUES (
--   1, 'google_ads', '123-456-7890', 'campaign', '987654321', 'Summer Sale Campaign',
--   '2025-10-01', 'daily',
--   '{"impressions": 10000, "clicks": 500, "cost": 250.50, "conversions": 25, "ctr": 5.0, "cpc": 0.50}',
--   10000, 500, 250.50, 25
-- );

-- Insert sample Facebook Ads metrics
-- INSERT INTO performance_metrics (
--   account_id, source_type, source_id, entity_type, entity_id, entity_name,
--   date, timeframe, metrics_json, impressions, clicks, spend, conversions
-- ) VALUES (
--   1, 'fbads', 'act_123456789', 'campaign', '23851234567890123', 'Q4 Lead Gen',
--   '2025-10-01', 'daily',
--   '{"reach": 15000, "impressions": 20000, "clicks": 600, "spend": 180.00, "leads": 30, "cpm": 9.00}',
--   20000, 600, 180.00, 30
-- );

-- Query metrics for last 30 days
-- SELECT
--   date,
--   source_type,
--   entity_name,
--   impressions,
--   clicks,
--   spend,
--   conversions,
--   CASE
--     WHEN impressions > 0 THEN ROUND((clicks / impressions) * 100, 2)
--     ELSE 0
--   END AS ctr_percent,
--   CASE
--     WHEN clicks > 0 THEN ROUND(spend / clicks, 2)
--     ELSE 0
--   END AS cpc
-- FROM performance_metrics
-- WHERE account_id = 1
--   AND date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
-- ORDER BY date DESC, source_type, entity_name;

-- ============================================================================
-- Rollback (if needed)
-- ============================================================================
-- DROP TABLE IF EXISTS `performance_metrics`;
