-- Migration: Add page_views table for user flow tracking
-- Purpose: Track user navigation through the site to analyze conversion funnels and user journeys
-- Date: 2025-10-29

CREATE TABLE page_views (
    id INT AUTO_INCREMENT PRIMARY KEY,
    session_id VARCHAR(64) NOT NULL,
    user_id INT NULL,

    -- Page information
    path VARCHAR(512) NOT NULL,
    page_title VARCHAR(255) NULL,
    referrer VARCHAR(512) NULL,
    query_string VARCHAR(512) NULL,

    -- Timing
    viewed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    time_on_page INT NULL COMMENT 'Seconds spent on page',

    -- Technical details
    ip_address VARCHAR(45) NULL,
    user_agent VARCHAR(512) NULL,
    device_type VARCHAR(20) NULL COMMENT 'desktop, mobile, tablet',
    browser VARCHAR(50) NULL,

    -- UTM parameters for marketing attribution
    utm_source VARCHAR(100) NULL,
    utm_medium VARCHAR(100) NULL,
    utm_campaign VARCHAR(100) NULL,
    utm_term VARCHAR(100) NULL,
    utm_content VARCHAR(100) NULL,

    -- Foreign keys
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,

    -- Indexes for common queries
    INDEX idx_page_views_session (session_id),
    INDEX idx_page_views_user (user_id),
    INDEX idx_page_views_path (path(255)),
    INDEX idx_page_views_date (viewed_at),
    INDEX idx_page_views_session_date (session_id, viewed_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
