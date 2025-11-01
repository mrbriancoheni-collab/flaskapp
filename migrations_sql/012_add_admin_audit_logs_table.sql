-- Migration: Add admin_audit_logs table for admin action tracking
-- Purpose: Track all admin actions for security, compliance, and auditing purposes
-- Date: 2025-10-30

CREATE TABLE admin_audit_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    admin_user_id INT NULL COMMENT 'The admin user who performed the action',

    -- Action details
    action VARCHAR(64) NOT NULL COMMENT 'Type of action performed',
    target_user_id INT NULL COMMENT 'User affected by the action',
    target_account_id INT NULL COMMENT 'Account affected by the action',
    note VARCHAR(1000) NOT NULL DEFAULT '' COMMENT 'Additional context about the action',

    -- Request metadata
    ip VARCHAR(45) NULL COMMENT 'IP address of the admin user',
    user_agent VARCHAR(255) NULL COMMENT 'Browser/client user agent',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Foreign keys
    FOREIGN KEY (admin_user_id) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (target_user_id) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (target_account_id) REFERENCES accounts(id) ON DELETE SET NULL,

    -- Indexes for common queries
    INDEX idx_admin_audit_logs_admin (admin_user_id),
    INDEX idx_admin_audit_logs_action (action),
    INDEX idx_admin_audit_logs_target_user (target_user_id),
    INDEX idx_admin_audit_logs_target_account (target_account_id),
    INDEX idx_admin_audit_logs_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
