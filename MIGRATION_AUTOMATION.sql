-- Database Migration for One-Click Campaign Automation
-- Run this SQL file manually in your MySQL/MariaDB database

-- =================================================================
-- Step 1: Add columns to lead_campaigns table
-- =================================================================

ALTER TABLE lead_campaigns
ADD COLUMN is_core BOOLEAN DEFAULT FALSE COMMENT 'Flag for core 20 campaigns';

ALTER TABLE lead_campaigns
ADD COLUMN last_automation_run DATETIME NULL COMMENT 'Last automation run timestamp';


-- =================================================================
-- Step 2: Create campaign_automation_config table
-- =================================================================

CREATE TABLE IF NOT EXISTS campaign_automation_config (
    id INT AUTO_INCREMENT PRIMARY KEY,
    enabled BOOLEAN DEFAULT FALSE,
    run_time VARCHAR(5) DEFAULT '09:00' COMMENT 'HH:MM format',
    run_days JSON NULL COMMENT '[0,1,2,3,4] for Mon-Fri, 0=Monday',
    daily_email_limit INT DEFAULT 250,
    skip_weekends BOOLEAN DEFAULT TRUE,
    next_run_at DATETIME NULL,
    last_run_at DATETIME NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- =================================================================
-- Step 3: Create automation_runs table
-- =================================================================

CREATE TABLE IF NOT EXISTS automation_runs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    job_id VARCHAR(36) UNIQUE NOT NULL COMMENT 'UUID for job tracking',
    trigger_type VARCHAR(20) COMMENT 'manual or scheduled',
    status VARCHAR(20) COMMENT 'running, completed, failed',
    started_at DATETIME NOT NULL,
    completed_at DATETIME NULL,
    duration_minutes INT NULL,
    campaigns_processed INT DEFAULT 0,
    leads_scraped INT DEFAULT 0,
    leads_enriched INT DEFAULT 0,
    emails_sent INT DEFAULT 0,
    error_count INT DEFAULT 0,
    error_message TEXT NULL,
    INDEX idx_job_id (job_id),
    INDEX idx_started_at (started_at),
    INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- =================================================================
-- Verification Queries
-- =================================================================

-- Verify new columns were added
DESCRIBE lead_campaigns;

-- Verify new tables were created
SHOW TABLES LIKE '%automation%';

-- Check structure of automation tables
DESCRIBE campaign_automation_config;
DESCRIBE automation_runs;


-- =================================================================
-- Optional: Initialize default configuration
-- =================================================================

-- Insert default automation config (disabled by default)
INSERT INTO campaign_automation_config
(enabled, run_time, run_days, daily_email_limit, skip_weekends)
VALUES
(FALSE, '09:00', '[0,1,2,3,4]', 250, TRUE)
ON DUPLICATE KEY UPDATE id=id;  -- Don't insert if already exists


-- =================================================================
-- Rollback SQL (if needed)
-- =================================================================

/*
-- To rollback these changes, run:

ALTER TABLE lead_campaigns DROP COLUMN is_core;
ALTER TABLE lead_campaigns DROP COLUMN last_automation_run;
DROP TABLE IF EXISTS automation_runs;
DROP TABLE IF EXISTS campaign_automation_config;
*/
