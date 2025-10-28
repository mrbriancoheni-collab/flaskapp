-- ROI Settings and Service Pricing Tables
-- Allows admin to configure ROI calculation parameters and pricing

CREATE TABLE IF NOT EXISTS `roi_settings` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `setting_key` VARCHAR(64) NOT NULL UNIQUE,
  `setting_name` VARCHAR(128) NOT NULL,
  `setting_value` TEXT NOT NULL,
  `setting_type` VARCHAR(32) NOT NULL COMMENT 'percentage, multiplier, formula, text',
  `description` TEXT,
  `category` VARCHAR(64) COMMENT 'improvement_rates, pricing, display',
  `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `updated_by` INT,
  INDEX idx_setting_key (`setting_key`),
  INDEX idx_category (`category`),
  FOREIGN KEY (`updated_by`) REFERENCES `users`(`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `service_pricing` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `tier_name` VARCHAR(64) NOT NULL,
  `min_monthly_spend` INT NOT NULL COMMENT 'Minimum monthly ad spend for this tier',
  `max_monthly_spend` INT COMMENT 'Maximum monthly ad spend (NULL = unlimited)',
  `base_price` INT NOT NULL COMMENT 'Base monthly price in cents',
  `percentage_of_savings` FLOAT COMMENT 'Percentage of savings to charge (0.20 = 20%)',
  `description` TEXT,
  `is_active` BOOLEAN DEFAULT TRUE,
  `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_spend_range (`min_monthly_spend`, `max_monthly_spend`),
  INDEX idx_active (`is_active`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
