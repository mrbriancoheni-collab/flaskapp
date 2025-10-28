-- Migration: Add email tracking tables for campaign performance
-- Date: 2025-10-28
-- Description: Creates tables to track emails sent, opens, and clicks for CRM contacts

-- Table: emails_sent
-- Tracks each email sent to CRM contacts
CREATE TABLE emails_sent (
    id INT AUTO_INCREMENT PRIMARY KEY,
    crm_contact_id INT NOT NULL,
    sent_by_user_id INT NULL,

    -- Email content
    subject VARCHAR(500) NOT NULL,
    body_html LONGTEXT NULL COMMENT 'HTML version of email body',
    body_text TEXT NULL COMMENT 'Plain text version of email body',

    -- Tracking
    tracking_token VARCHAR(64) NOT NULL UNIQUE COMMENT 'Unique token for tracking opens/clicks',
    campaign_name VARCHAR(255) NULL COMMENT 'Optional campaign identifier',

    -- Status
    sent_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    delivered BOOLEAN NOT NULL DEFAULT 1 COMMENT 'Whether email was delivered',
    bounced BOOLEAN NOT NULL DEFAULT 0 COMMENT 'Whether email bounced',
    bounced_at DATETIME NULL,

    FOREIGN KEY (crm_contact_id) REFERENCES crm_contacts(id) ON DELETE CASCADE,
    FOREIGN KEY (sent_by_user_id) REFERENCES users(id) ON DELETE SET NULL,

    INDEX idx_emails_sent_contact (crm_contact_id),
    INDEX idx_emails_sent_user (sent_by_user_id),
    INDEX idx_emails_sent_token (tracking_token),
    INDEX idx_emails_sent_campaign (campaign_name),
    INDEX idx_emails_sent_date (sent_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Table: email_opens
-- Tracks when emails are opened (via tracking pixel)
CREATE TABLE email_opens (
    id INT AUTO_INCREMENT PRIMARY KEY,
    email_sent_id INT NOT NULL,

    opened_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ip_address VARCHAR(45) NULL COMMENT 'IPv4 or IPv6 address',
    user_agent VARCHAR(512) NULL COMMENT 'Browser/email client user agent',

    FOREIGN KEY (email_sent_id) REFERENCES emails_sent(id) ON DELETE CASCADE,

    INDEX idx_email_opens_email (email_sent_id),
    INDEX idx_email_opens_date (opened_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Table: email_clicks
-- Tracks when links in emails are clicked
CREATE TABLE email_clicks (
    id INT AUTO_INCREMENT PRIMARY KEY,
    email_sent_id INT NOT NULL,

    clicked_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    url VARCHAR(2048) NOT NULL COMMENT 'Original destination URL',
    ip_address VARCHAR(45) NULL,
    user_agent VARCHAR(512) NULL,

    FOREIGN KEY (email_sent_id) REFERENCES emails_sent(id) ON DELETE CASCADE,

    INDEX idx_email_clicks_email (email_sent_id),
    INDEX idx_email_clicks_date (clicked_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Rollback script saved in 007_add_email_tracking_tables_rollback.sql
