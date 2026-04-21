-- ============================================================================
-- Location-Based Budget Management Migration
-- ============================================================================
-- Adds location targeting to budget groups for geographic budget allocation
-- Examples: "Nashville Market - $10k/mo", "Memphis Market - $5k/mo"

-- Add location fields to campaign_budget_groups
ALTER TABLE campaign_budget_groups
ADD COLUMN target_location VARCHAR(255) DEFAULT NULL COMMENT 'Geographic target (e.g., "Nashville, TN", "Tennessee", "37203")' AFTER description,
ADD COLUMN location_type ENUM('city', 'state', 'zip', 'dma', 'radius', 'country', 'custom') DEFAULT NULL COMMENT 'Type of location targeting' AFTER target_location,
ADD COLUMN location_radius_miles INT DEFAULT NULL COMMENT 'Radius in miles if location_type = radius' AFTER location_type,
ADD COLUMN location_lat DECIMAL(10, 8) DEFAULT NULL COMMENT 'Latitude for radius targeting' AFTER location_radius_miles,
ADD COLUMN location_lng DECIMAL(11, 8) DEFAULT NULL COMMENT 'Longitude for radius targeting' AFTER location_lat,
ADD COLUMN location_criteria_ids TEXT DEFAULT NULL COMMENT 'Google Ads location criterion IDs (comma-separated)' AFTER location_lng,
ADD INDEX idx_target_location (target_location),
ADD INDEX idx_location_type (location_type);


-- ============================================================================
-- Location-Based Performance Tracking
-- ============================================================================

CREATE TABLE IF NOT EXISTS budget_group_location_performance (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- Budget group and period
    budget_group_id INT NOT NULL,
    period_month DATE NOT NULL,  -- First day of month

    -- Location breakdown
    location_name VARCHAR(255) NOT NULL COMMENT 'City, state, or geographic area name',
    location_criterion_id VARCHAR(50) DEFAULT NULL COMMENT 'Google Ads location criterion ID',

    -- Performance metrics
    spend_cents INT DEFAULT 0,
    impressions BIGINT DEFAULT 0,
    clicks INT DEFAULT 0,
    conversions DECIMAL(10,2) DEFAULT 0,
    calls INT DEFAULT 0,

    -- Calculated metrics
    ctr DECIMAL(5,4) DEFAULT 0 COMMENT 'Click-through rate',
    cpc_cents INT DEFAULT 0 COMMENT 'Cost per click in cents',
    cpl_cents INT DEFAULT 0 COMMENT 'Cost per lead in cents',
    conversion_rate DECIMAL(5,4) DEFAULT 0,

    -- Budget pacing
    daily_avg_spend_cents INT DEFAULT 0,
    target_daily_spend_cents INT DEFAULT 0,
    pacing_status ENUM('under', 'on_track', 'over', 'paused') DEFAULT 'on_track',

    -- Metadata
    last_updated DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- Indexes
    UNIQUE KEY unique_group_location_month (budget_group_id, location_name, period_month),
    INDEX idx_budget_group (budget_group_id),
    INDEX idx_period (period_month),
    INDEX idx_location (location_name),
    INDEX idx_pacing_status (pacing_status),

    -- Foreign keys
    FOREIGN KEY (budget_group_id) REFERENCES campaign_budget_groups(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ============================================================================
-- Location-Based Budget Rules
-- ============================================================================

CREATE TABLE IF NOT EXISTS budget_group_location_rules (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- Budget group
    budget_group_id INT NOT NULL,

    -- Location
    location_name VARCHAR(255) NOT NULL,
    location_criterion_id VARCHAR(50) DEFAULT NULL,

    -- Budget allocation
    monthly_budget_cents INT NOT NULL COMMENT 'Budget allocated to this location',
    priority INT DEFAULT 0 COMMENT 'Higher priority locations get budget first',

    -- Performance thresholds
    min_cpl_cents INT DEFAULT NULL COMMENT 'Pause if CPL exceeds this',
    max_cpl_cents INT DEFAULT NULL COMMENT 'Alert if CPL exceeds this',
    min_conversion_rate DECIMAL(5,4) DEFAULT NULL,
    target_roas DECIMAL(5,2) DEFAULT NULL,

    -- Auto-adjustments
    auto_pause_on_threshold BOOLEAN DEFAULT FALSE,
    auto_increase_on_performance BOOLEAN DEFAULT FALSE COMMENT 'Increase budget if performing well',
    increase_percentage DECIMAL(5,2) DEFAULT 10.00 COMMENT 'Budget increase % when triggered',

    -- Status
    status ENUM('active', 'paused', 'archived') DEFAULT 'active',

    -- Metadata
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- Indexes
    UNIQUE KEY unique_group_location (budget_group_id, location_name),
    INDEX idx_budget_group (budget_group_id),
    INDEX idx_location (location_name),
    INDEX idx_status (status),

    -- Foreign keys
    FOREIGN KEY (budget_group_id) REFERENCES campaign_budget_groups(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ============================================================================
-- Location-Based Alerts
-- ============================================================================

CREATE TABLE IF NOT EXISTS budget_group_location_alerts (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- Budget group and location
    budget_group_id INT NOT NULL,
    location_name VARCHAR(255) NOT NULL,

    -- Alert details
    alert_type ENUM('overspend', 'underspend', 'high_cpl', 'low_conversions', 'pacing_issue') NOT NULL,
    severity ENUM('low', 'medium', 'high', 'critical') DEFAULT 'medium',
    message TEXT NOT NULL,

    -- Alert data
    current_value DECIMAL(10,2) DEFAULT NULL,
    threshold_value DECIMAL(10,2) DEFAULT NULL,

    -- Status
    is_acknowledged BOOLEAN DEFAULT FALSE,
    acknowledged_at DATETIME DEFAULT NULL,
    acknowledged_by INT DEFAULT NULL,

    -- Auto-actions taken
    action_taken ENUM('none', 'paused_campaigns', 'reduced_budget', 'sent_notification') DEFAULT 'none',

    -- Metadata
    alert_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Indexes
    INDEX idx_budget_group (budget_group_id),
    INDEX idx_location (location_name),
    INDEX idx_alert_type (alert_type),
    INDEX idx_severity (severity),
    INDEX idx_acknowledged (is_acknowledged),
    INDEX idx_alert_date (alert_date),

    -- Foreign keys
    FOREIGN KEY (budget_group_id) REFERENCES campaign_budget_groups(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ============================================================================
-- Campaign Location Targeting Cache
-- ============================================================================
-- Cache Google Ads location targets for faster filtering

CREATE TABLE IF NOT EXISTS campaign_location_targets (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- Campaign
    campaign_id INT NOT NULL,
    account_id BIGINT NOT NULL,

    -- Location targeting
    location_criterion_id VARCHAR(50) NOT NULL COMMENT 'Google Ads location criterion ID',
    location_name VARCHAR(255) NOT NULL,
    location_type VARCHAR(50) DEFAULT NULL COMMENT 'City, State, ZIP, DMA, etc.',
    canonical_name VARCHAR(255) DEFAULT NULL COMMENT 'Full location name from Google',

    -- Target type
    target_type ENUM('included', 'excluded') DEFAULT 'included',

    -- Metadata
    last_synced DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Indexes
    INDEX idx_campaign (campaign_id),
    INDEX idx_account (account_id),
    INDEX idx_location_criterion (location_criterion_id),
    INDEX idx_location_name (location_name),
    INDEX idx_target_type (target_type),

    -- Foreign keys
    FOREIGN KEY (campaign_id) REFERENCES ads_campaigns(id) ON DELETE CASCADE,
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ============================================================================
-- Sample Data and Comments
-- ============================================================================

-- Example budget group with location targeting:
-- INSERT INTO campaign_budget_groups (account_id, name, description, target_location, location_type, monthly_budget_cents)
-- VALUES (1, 'Nashville Market', 'HVAC campaigns targeting Nashville metro area', 'Nashville, TN', 'dma', 1000000);

-- Example location rule:
-- INSERT INTO budget_group_location_rules (budget_group_id, location_name, monthly_budget_cents, min_cpl_cents, auto_pause_on_threshold)
-- VALUES (1, 'Nashville, TN', 1000000, 5000, TRUE);

COMMENT ON COLUMN campaign_budget_groups.target_location IS 'Primary geographic target for this budget group';
COMMENT ON COLUMN campaign_budget_groups.location_type IS 'Type of location targeting (city, state, zip, dma, radius, country)';
COMMENT ON COLUMN campaign_budget_groups.location_criteria_ids IS 'Comma-separated Google Ads location criterion IDs for auto-assignment';

COMMENT ON TABLE budget_group_location_performance IS 'Track performance metrics broken down by location within each budget group';
COMMENT ON TABLE budget_group_location_rules IS 'Define budget allocation and performance rules for specific locations';
COMMENT ON TABLE budget_group_location_alerts IS 'Location-specific alerts for budget groups (overspend, high CPL, etc.)';
COMMENT ON TABLE campaign_location_targets IS 'Cache of Google Ads location targeting for campaigns';
