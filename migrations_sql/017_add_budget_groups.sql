-- Migration 017: Add Budget Groups
-- Allows creating multiple budgets and assigning campaigns to each budget group

-- Budget Groups (e.g., "HVAC Budget - $5,000/mo", "Plumbing Budget - $3,000/mo")
CREATE TABLE IF NOT EXISTS budget_groups (
    id INT AUTO_INCREMENT PRIMARY KEY,
    account_id INT NOT NULL,
    customer_id VARCHAR(50) NOT NULL,
    name VARCHAR(255) NOT NULL COMMENT 'User-friendly name: "HVAC Campaigns Budget"',
    description TEXT COMMENT 'Optional description',
    monthly_budget_target DECIMAL(10, 2) NOT NULL,
    min_daily_budget DECIMAL(10, 2) DEFAULT 10.00,
    max_daily_budget DECIMAL(10, 2) DEFAULT 1000.00,
    enabled BOOLEAN DEFAULT TRUE,
    adjustment_frequency ENUM('hourly', 'daily', 'weekly') DEFAULT 'daily',
    performance_weight DECIMAL(3, 2) DEFAULT 0.70,
    seasonality_weight DECIMAL(3, 2) DEFAULT 0.20,
    capacity_weight DECIMAL(3, 2) DEFAULT 0.10,
    industry VARCHAR(50) DEFAULT 'hvac_heating' COMMENT 'For seasonality curves',
    send_notifications BOOLEAN DEFAULT TRUE,
    color VARCHAR(7) DEFAULT '#3B82F6' COMMENT 'Hex color for UI',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_account (account_id),
    INDEX idx_customer (customer_id),
    INDEX idx_enabled (enabled)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Budget Group Campaign Assignments (many-to-many)
CREATE TABLE IF NOT EXISTS budget_group_campaigns (
    id INT AUTO_INCREMENT PRIMARY KEY,
    budget_group_id INT NOT NULL,
    account_id INT NOT NULL,
    customer_id VARCHAR(50) NOT NULL,
    campaign_id VARCHAR(50) NOT NULL COMMENT 'Google Ads campaign ID',
    campaign_name VARCHAR(255),
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (budget_group_id) REFERENCES budget_groups(id) ON DELETE CASCADE,
    UNIQUE KEY unique_campaign_assignment (budget_group_id, campaign_id),
    INDEX idx_budget_group (budget_group_id),
    INDEX idx_account (account_id),
    INDEX idx_campaign (campaign_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Budget Group Performance Snapshot (daily rollup)
CREATE TABLE IF NOT EXISTS budget_group_performance (
    id INT AUTO_INCREMENT PRIMARY KEY,
    budget_group_id INT NOT NULL,
    account_id INT NOT NULL,
    snapshot_date DATE NOT NULL,
    total_spend DECIMAL(10, 2) DEFAULT 0,
    total_conversions INT DEFAULT 0,
    avg_cpl DECIMAL(10, 2) DEFAULT 0,
    total_clicks INT DEFAULT 0,
    total_impressions INT DEFAULT 0,
    avg_ctr DECIMAL(5, 2) DEFAULT 0,
    avg_roas DECIMAL(5, 2) DEFAULT 0,
    campaigns_active INT DEFAULT 0,
    budget_utilization_pct DECIMAL(5, 2) DEFAULT 0 COMMENT 'Spend / Target * 100',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (budget_group_id) REFERENCES budget_groups(id) ON DELETE CASCADE,
    UNIQUE KEY unique_snapshot (budget_group_id, snapshot_date),
    INDEX idx_budget_group (budget_group_id),
    INDEX idx_snapshot_date (snapshot_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Verification queries:
-- SELECT * FROM budget_groups;
-- SELECT * FROM budget_group_campaigns;
-- SELECT * FROM budget_group_performance;
