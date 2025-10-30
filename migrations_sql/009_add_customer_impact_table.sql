-- ============================================================================
-- Migration: Add customer_impact table for tracking savings and leads
-- Database: MySQL
-- Created: 2025-10-30
-- ============================================================================

-- Create customer_impact table
CREATE TABLE IF NOT EXISTS `customer_impact` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `account_id` BIGINT NOT NULL UNIQUE,

  -- Baseline metrics (pre-FieldSprout)
  `baseline_start_date` DATE DEFAULT NULL,
  `baseline_end_date` DATE DEFAULT NULL,
  `baseline_monthly_spend` DECIMAL(10,2) DEFAULT 0,
  `baseline_monthly_leads` DECIMAL(10,2) DEFAULT 0,
  `baseline_cost_per_lead` DECIMAL(10,2) DEFAULT 0,

  -- Current performance
  `current_monthly_spend` DECIMAL(10,2) DEFAULT 0,
  `current_monthly_leads` DECIMAL(10,2) DEFAULT 0,
  `current_cost_per_lead` DECIMAL(10,2) DEFAULT 0,

  -- Running totals
  `total_savings` DECIMAL(12,2) NOT NULL DEFAULT 0 COMMENT 'Cumulative savings in dollars',
  `total_additional_leads` DECIMAL(12,2) NOT NULL DEFAULT 0 COMMENT 'Cumulative additional leads',

  -- Monthly tracking
  `monthly_savings` DECIMAL(10,2) DEFAULT 0 COMMENT 'Last calculated monthly savings',
  `monthly_additional_leads` DECIMAL(10,2) DEFAULT 0 COMMENT 'Last calculated monthly leads',

  -- Tracking
  `last_calculated_at` DATETIME DEFAULT NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  PRIMARY KEY (`id`),
  INDEX `ix_customer_impact_account_id` (`account_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Tracks cumulative savings and additional leads per customer vs pre-FieldSprout baseline';

-- ============================================================================
-- Verify migration
-- ============================================================================
SELECT 'customer_impact table created successfully' AS status;
SHOW CREATE TABLE `customer_impact`;

-- ============================================================================
-- Sample usage (optional - for testing)
-- ============================================================================

-- Set baseline for a customer
-- INSERT INTO customer_impact (
--   account_id, baseline_start_date, baseline_end_date,
--   baseline_monthly_spend, baseline_monthly_leads, baseline_cost_per_lead
-- ) VALUES (
--   1, '2024-01-01', '2024-03-31', 5000.00, 50.00, 100.00
-- );

-- Update current metrics
-- UPDATE customer_impact
-- SET
--   current_monthly_spend = 4000.00,
--   current_monthly_leads = 60.00,
--   current_cost_per_lead = 66.67,
--   monthly_savings = 1000.00,
--   monthly_additional_leads = 10.00,
--   total_savings = total_savings + 1000.00,
--   total_additional_leads = total_additional_leads + 10.00,
--   last_calculated_at = NOW()
-- WHERE account_id = 1;

-- Query aggregate metrics
-- SELECT
--   COUNT(*) AS customer_count,
--   SUM(total_savings) AS total_savings,
--   SUM(total_additional_leads) AS total_additional_leads,
--   AVG(monthly_savings) AS avg_monthly_savings,
--   AVG(monthly_additional_leads) AS avg_monthly_additional_leads
-- FROM customer_impact
-- WHERE total_savings > 0;

-- ============================================================================
-- Rollback (if needed)
-- ============================================================================
-- DROP TABLE IF EXISTS `customer_impact`;
