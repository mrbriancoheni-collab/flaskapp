-- Migration 018: Add Budget Change Safeguards
-- Adds safeguard settings to prevent drastic budget changes
-- Run this SQL in your MySQL database

-- ============================================
-- ADD SAFEGUARD COLUMNS TO AUTO_BUDGET_SETTINGS
-- ============================================

ALTER TABLE auto_budget_settings
ADD COLUMN IF NOT EXISTS max_daily_change_pct DECIMAL(5, 2) DEFAULT 20.00 COMMENT 'Maximum % budget can change per day',
ADD COLUMN IF NOT EXISTS max_weekly_change_pct DECIMAL(5, 2) DEFAULT 40.00 COMMENT 'Maximum % budget can change per week',
ADD COLUMN IF NOT EXISTS enable_gradual_ramp BOOLEAN DEFAULT TRUE COMMENT 'Spread changes over multiple days',
ADD COLUMN IF NOT EXISTS ramp_days INT DEFAULT 3 COMMENT 'Number of days to ramp up/down',
ADD COLUMN IF NOT EXISTS require_approval_threshold_pct DECIMAL(5, 2) DEFAULT 30.00 COMMENT 'Changes above this % need approval',
ADD COLUMN IF NOT EXISTS enable_rollback BOOLEAN DEFAULT FALSE COMMENT 'Auto-rollback on performance drop',
ADD COLUMN IF NOT EXISTS rollback_window_hours INT DEFAULT 24 COMMENT 'Hours to monitor for rollback',
ADD COLUMN IF NOT EXISTS rollback_performance_drop_pct DECIMAL(5, 2) DEFAULT 20.00 COMMENT 'ROAS drop % that triggers rollback',
ADD COLUMN IF NOT EXISTS alert_threshold_pct DECIMAL(5, 2) DEFAULT 15.00 COMMENT 'Send alerts when changes exceed this %';

-- ============================================
-- ADD SAFEGUARD COLUMNS TO BUDGET_GROUPS
-- ============================================

ALTER TABLE budget_groups
ADD COLUMN IF NOT EXISTS max_daily_change_pct DECIMAL(5, 2) DEFAULT 20.00 COMMENT 'Maximum % budget can change per day',
ADD COLUMN IF NOT EXISTS max_weekly_change_pct DECIMAL(5, 2) DEFAULT 40.00 COMMENT 'Maximum % budget can change per week',
ADD COLUMN IF NOT EXISTS enable_gradual_ramp BOOLEAN DEFAULT TRUE COMMENT 'Spread changes over multiple days',
ADD COLUMN IF NOT EXISTS ramp_days INT DEFAULT 3 COMMENT 'Number of days to ramp up/down',
ADD COLUMN IF NOT EXISTS require_approval_threshold_pct DECIMAL(5, 2) DEFAULT 30.00 COMMENT 'Changes above this % need approval',
ADD COLUMN IF NOT EXISTS enable_rollback BOOLEAN DEFAULT FALSE COMMENT 'Auto-rollback on performance drop',
ADD COLUMN IF NOT EXISTS rollback_window_hours INT DEFAULT 24 COMMENT 'Hours to monitor for rollback',
ADD COLUMN IF NOT EXISTS rollback_performance_drop_pct DECIMAL(5, 2) DEFAULT 20.00 COMMENT 'ROAS drop % that triggers rollback',
ADD COLUMN IF NOT EXISTS alert_threshold_pct DECIMAL(5, 2) DEFAULT 15.00 COMMENT 'Send alerts when changes exceed this %';

-- ============================================
-- ADD PENDING CHANGES TABLE (FOR APPROVAL WORKFLOW)
-- ============================================

CREATE TABLE IF NOT EXISTS budget_pending_changes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    account_id INT NOT NULL,
    customer_id VARCHAR(50) NOT NULL,
    budget_group_id INT NULL COMMENT 'NULL for account-level settings',
    campaign_id VARCHAR(50) NOT NULL,
    campaign_name VARCHAR(255),
    current_daily_budget DECIMAL(10, 2) NOT NULL,
    proposed_daily_budget DECIMAL(10, 2) NOT NULL,
    change_amount DECIMAL(10, 2) NOT NULL,
    change_pct DECIMAL(5, 2) NOT NULL,
    reason VARCHAR(500) NOT NULL COMMENT 'Why the adjustment is needed',
    triggered_by ENUM('auto', 'manual', 'agent') DEFAULT 'auto',
    status ENUM('pending', 'approved', 'rejected', 'cancelled', 'expired') DEFAULT 'pending',
    requires_approval BOOLEAN DEFAULT TRUE,
    approved_by INT NULL COMMENT 'User ID who approved',
    approved_at TIMESTAMP NULL,
    rejected_by INT NULL COMMENT 'User ID who rejected',
    rejected_at TIMESTAMP NULL,
    rejection_reason VARCHAR(500),
    expires_at TIMESTAMP NULL COMMENT 'Auto-reject if not reviewed',
    metadata JSON COMMENT 'Additional context (scores, seasonality, etc)',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_account (account_id),
    INDEX idx_customer (customer_id),
    INDEX idx_campaign (campaign_id),
    INDEX idx_status (status),
    INDEX idx_created_at (created_at),
    INDEX idx_expires_at (expires_at),
    FOREIGN KEY (budget_group_id) REFERENCES budget_groups(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================
-- ADD ROLLBACK TRACKING TABLE
-- ============================================

CREATE TABLE IF NOT EXISTS budget_rollback_tracking (
    id INT AUTO_INCREMENT PRIMARY KEY,
    account_id INT NOT NULL,
    customer_id VARCHAR(50) NOT NULL,
    campaign_id VARCHAR(50) NOT NULL,
    campaign_name VARCHAR(255),
    budget_change_log_id INT NOT NULL COMMENT 'Original change that was rolled back',
    old_budget DECIMAL(10, 2) NOT NULL,
    new_budget DECIMAL(10, 2) NOT NULL,
    rollback_budget DECIMAL(10, 2) NOT NULL COMMENT 'Budget restored to',
    trigger_reason VARCHAR(500) COMMENT 'Why rollback was triggered',
    performance_drop_pct DECIMAL(5, 2) COMMENT 'Actual ROAS drop %',
    roas_before DECIMAL(10, 4),
    roas_after DECIMAL(10, 4),
    rollback_executed BOOLEAN DEFAULT FALSE,
    executed_at TIMESTAMP NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_account (account_id),
    INDEX idx_customer (customer_id),
    INDEX idx_campaign (campaign_id),
    INDEX idx_change_log (budget_change_log_id),
    INDEX idx_created_at (created_at),
    FOREIGN KEY (budget_change_log_id) REFERENCES budget_change_log(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================
-- ADD WEEKLY BUDGET TRACKING (FOR WEEKLY LIMITS)
-- ============================================

CREATE TABLE IF NOT EXISTS budget_weekly_changes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    account_id INT NOT NULL,
    customer_id VARCHAR(50) NOT NULL,
    campaign_id VARCHAR(50) NOT NULL,
    week_start_date DATE NOT NULL COMMENT 'Monday of the week',
    week_end_date DATE NOT NULL COMMENT 'Sunday of the week',
    starting_budget DECIMAL(10, 2) NOT NULL,
    current_budget DECIMAL(10, 2) NOT NULL,
    total_change_amount DECIMAL(10, 2) DEFAULT 0,
    total_change_pct DECIMAL(5, 2) DEFAULT 0,
    num_changes INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_account (account_id),
    INDEX idx_customer (customer_id),
    INDEX idx_campaign (campaign_id),
    INDEX idx_week (week_start_date),
    UNIQUE KEY unique_campaign_week (account_id, customer_id, campaign_id, week_start_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================
-- VERIFICATION QUERIES
-- ============================================

-- Check new columns were added:
-- DESCRIBE auto_budget_settings;
-- DESCRIBE budget_groups;

-- Check new tables were created:
-- SHOW TABLES LIKE '%budget_pending_changes%';
-- SHOW TABLES LIKE '%budget_rollback_tracking%';
-- SHOW TABLES LIKE '%budget_weekly_changes%';
