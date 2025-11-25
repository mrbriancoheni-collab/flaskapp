-- Migration 022: Create applied_optimizations table
-- Track Google Ads optimizations that were applied to confirm changes were pushed

CREATE TABLE IF NOT EXISTS applied_optimizations (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    account_id INT NOT NULL,
    user_id INT NULL,

    -- Google Ads identifiers
    customer_id VARCHAR(64) NULL,
    campaign_id VARCHAR(128) NULL,

    -- Optimization details
    optimization_type VARCHAR(64) NOT NULL,
    optimization_title VARCHAR(512) NULL,
    optimization_data JSON NULL,

    -- Application status
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    error_message TEXT NULL,

    -- Google Ads API response
    resource_name VARCHAR(512) NULL,
    api_response JSON NULL,

    -- Timestamps
    applied_at DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- Indexes
    INDEX idx_account_id (account_id),
    INDEX idx_customer_id (customer_id),
    INDEX idx_optimization_type (optimization_type),
    INDEX idx_status (status),
    INDEX idx_created_at (created_at),

    -- Foreign keys
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
