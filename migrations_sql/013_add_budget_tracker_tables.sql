-- Migration: Add budget tracking tables
-- Purpose: Track Google Ads budgets and send alerts when thresholds are reached
-- Date: 2025-11-11

-- Create budget_trackers table
CREATE TABLE budget_trackers (
    id INT AUTO_INCREMENT PRIMARY KEY,
    account_id INT NOT NULL COMMENT 'Reference to the account',
    user_id INT NOT NULL COMMENT 'User who created this budget tracker',

    -- Google Ads identifiers
    customer_id VARCHAR(32) NOT NULL COMMENT 'Google Ads customer/account ID',
    campaign_id VARCHAR(32) NULL COMMENT 'Optional: specific campaign ID to track',
    campaign_name VARCHAR(255) NULL COMMENT 'Campaign name for display purposes',

    -- Budget configuration
    budget_type ENUM('monthly', 'weekly', 'daily', 'campaign') NOT NULL DEFAULT 'monthly' COMMENT 'Type of budget period',
    budget_amount INT NOT NULL COMMENT 'Budget amount in cents',

    -- Time period
    start_date DATETIME NOT NULL COMMENT 'Budget period start date',
    end_date DATETIME NOT NULL COMMENT 'Budget period end date',

    -- Alert configuration
    alert_threshold_percent INT NOT NULL DEFAULT 80 COMMENT 'Percentage threshold for alerts',
    alert_enabled BOOLEAN NOT NULL DEFAULT TRUE COMMENT 'Whether alerts are enabled',

    -- Status
    status ENUM('active', 'paused', 'completed', 'cancelled') NOT NULL DEFAULT 'active' COMMENT 'Budget tracker status',

    -- Tracking data
    last_checked_at DATETIME NULL COMMENT 'Last time we checked spend for this budget',
    last_spend_amount INT NULL COMMENT 'Last known spend amount in cents',

    -- Timestamps
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- Foreign keys
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,

    -- Indexes for common queries
    INDEX idx_budget_trackers_account (account_id),
    INDEX idx_budget_trackers_user (user_id),
    INDEX idx_budget_trackers_customer (customer_id),
    INDEX idx_budget_trackers_campaign (campaign_id),
    INDEX idx_budget_trackers_status (status),
    INDEX idx_budget_trackers_end_date (end_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Create budget_alerts table
CREATE TABLE budget_alerts (
    id INT AUTO_INCREMENT PRIMARY KEY,
    budget_tracker_id INT NOT NULL COMMENT 'Reference to the budget tracker',

    -- Alert details
    alert_type ENUM('threshold_reached', 'overspend', 'underspend', 'pacing_ahead', 'pacing_behind', 'budget_depleted') NOT NULL COMMENT 'Type of alert',
    alert_message TEXT NOT NULL COMMENT 'Alert message to display/send',
    severity ENUM('info', 'warning', 'critical') NOT NULL DEFAULT 'warning' COMMENT 'Alert severity level',

    -- Spend details at time of alert
    spend_amount INT NOT NULL COMMENT 'Spend amount at time of alert (cents)',
    budget_amount INT NOT NULL COMMENT 'Budget amount at time of alert (cents)',
    spend_percentage FLOAT NOT NULL COMMENT 'Percentage of budget spent',

    -- Notification tracking
    sent_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'When alert was sent',
    acknowledged BOOLEAN NOT NULL DEFAULT FALSE COMMENT 'Whether user acknowledged alert',
    acknowledged_at DATETIME NULL COMMENT 'When alert was acknowledged',
    acknowledged_by_user_id INT NULL COMMENT 'User who acknowledged the alert',

    -- Foreign keys
    FOREIGN KEY (budget_tracker_id) REFERENCES budget_trackers(id) ON DELETE CASCADE,
    FOREIGN KEY (acknowledged_by_user_id) REFERENCES users(id) ON DELETE SET NULL,

    -- Indexes for common queries
    INDEX idx_budget_alerts_tracker (budget_tracker_id),
    INDEX idx_budget_alerts_type (alert_type),
    INDEX idx_budget_alerts_sent (sent_at),
    INDEX idx_budget_alerts_ack (acknowledged)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
