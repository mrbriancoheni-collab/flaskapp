-- ============================================================================
-- Auto-Budget Adjustment, Capacity Tracking, ML, and Competitive Intelligence Tables
-- ============================================================================

-- Budget Change Log - Track all automatic and manual budget adjustments
CREATE TABLE IF NOT EXISTS budget_change_log (
    id INT AUTO_INCREMENT PRIMARY KEY,
    account_id INT NOT NULL,
    campaign_id INT NOT NULL,
    change_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    old_daily_budget_cents INT NOT NULL,
    new_daily_budget_cents INT NOT NULL,
    change_pct DECIMAL(10,2) NOT NULL,
    change_reason VARCHAR(255) NOT NULL,
    adjustment_type ENUM('auto', 'manual', 'agent', 'seasonal', 'weather', 'capacity', 'competitive') NOT NULL DEFAULT 'auto',
    triggered_by VARCHAR(100),  -- 'budget_guardian_agent', 'auto_adjustment_service', 'user_123', etc.
    metadata JSON,  -- Additional context (seasonality factor, weather multiplier, performance scores, etc.)
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_account_campaign (account_id, campaign_id),
    INDEX idx_change_date (change_date),
    INDEX idx_adjustment_type (adjustment_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- User Notifications - Notify users of budget changes, anomalies, and important events
CREATE TABLE IF NOT EXISTS user_notifications (
    id INT AUTO_INCREMENT PRIMARY KEY,
    account_id INT NOT NULL,
    user_id INT,  -- NULL = notify all account users
    notification_type ENUM('budget_change', 'anomaly', 'weather_alert', 'capacity_alert', 'competitive_alert', 'forecast_alert', 'system') NOT NULL,
    severity ENUM('info', 'low', 'medium', 'high', 'critical') NOT NULL DEFAULT 'info',
    title VARCHAR(255) NOT NULL,
    message TEXT NOT NULL,
    related_campaign_id INT,
    metadata JSON,
    is_read BOOLEAN DEFAULT FALSE,
    is_dismissed BOOLEAN DEFAULT FALSE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    read_at DATETIME,
    dismissed_at DATETIME,
    INDEX idx_account_user (account_id, user_id),
    INDEX idx_notification_type (notification_type),
    INDEX idx_severity (severity),
    INDEX idx_is_read (is_read),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- Capacity Tracking - Track daily tech capacity and utilization (no CRM required)
CREATE TABLE IF NOT EXISTS capacity_tracking (
    id INT AUTO_INCREMENT PRIMARY KEY,
    account_id INT NOT NULL,
    service_type VARCHAR(50) NOT NULL,  -- 'hvac_ac', 'hvac_heat', 'plumbing', 'electrical', 'roofing'
    target_date DATE NOT NULL,
    total_techs INT NOT NULL,
    slots_per_tech INT DEFAULT 4,
    total_slots INT NOT NULL,
    booked_slots INT DEFAULT 0,
    available_slots INT NOT NULL,
    capacity_utilization DECIMAL(5,2) NOT NULL,  -- 0-100%
    days_booked_out INT DEFAULT 0,  -- How many days ahead are you booked?
    budget_recommendation ENUM('increase_30', 'increase_20', 'increase_10', 'maintain', 'reduce_10', 'reduce_20', 'reduce_40') NOT NULL DEFAULT 'maintain',
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY unique_capacity (account_id, service_type, target_date),
    INDEX idx_account_service (account_id, service_type),
    INDEX idx_target_date (target_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- Capacity Bookings - Log individual bookings to track capacity
CREATE TABLE IF NOT EXISTS capacity_bookings (
    id INT AUTO_INCREMENT PRIMARY KEY,
    account_id INT NOT NULL,
    service_type VARCHAR(50) NOT NULL,
    booking_date DATE NOT NULL,
    booking_time TIME,
    customer_name VARCHAR(255),
    customer_phone VARCHAR(50),
    customer_email VARCHAR(255),
    service_address TEXT,
    source VARCHAR(50) DEFAULT 'google_ads',  -- 'google_ads', 'organic', 'referral', 'direct', 'lsa'
    campaign_id INT,
    job_type VARCHAR(100),  -- 'ac_repair', 'furnace_install', 'pipe_leak', etc.
    estimated_value_cents INT,
    status ENUM('scheduled', 'completed', 'cancelled', 'no_show') DEFAULT 'scheduled',
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_account_service (account_id, service_type),
    INDEX idx_booking_date (booking_date),
    INDEX idx_source (source),
    INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- Competitive Auction Insights - Store competitor data from Google Ads API
CREATE TABLE IF NOT EXISTS competitive_auction_insights (
    id INT AUTO_INCREMENT PRIMARY KEY,
    customer_id VARCHAR(50) NOT NULL,  -- Google Ads customer ID
    campaign_id VARCHAR(50) NOT NULL,  -- Google Ads campaign ID
    data_date DATE NOT NULL,
    competitor_domain VARCHAR(255) NOT NULL,
    impression_share DECIMAL(5,4),  -- 0-1 (e.g., 0.4532 = 45.32%)
    top_of_page_rate DECIMAL(5,4),  -- 0-1
    rank_lost_share DECIMAL(5,4),  -- 0-1 (impression share lost due to rank)
    overlap_rate DECIMAL(5,4),  -- 0-1 (how often competitor appears in same auctions)
    position_above_rate DECIMAL(5,4),  -- 0-1 (how often competitor outranks you)
    outranking_share DECIMAL(5,4),  -- 0-1 (how often you outrank competitor)
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY unique_insight (customer_id, campaign_id, data_date, competitor_domain),
    INDEX idx_customer_campaign (customer_id, campaign_id),
    INDEX idx_data_date (data_date),
    INDEX idx_competitor (competitor_domain)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ML Models - Store ML model metadata and performance
CREATE TABLE IF NOT EXISTS ml_models (
    id INT AUTO_INCREMENT PRIMARY KEY,
    account_id INT NOT NULL,
    model_name VARCHAR(100) NOT NULL,
    model_type VARCHAR(50) NOT NULL,  -- 'random_forest', 'xgboost', 'neural_network', 'linear_regression'
    target_metric VARCHAR(50) NOT NULL,  -- 'conversions', 'cpl', 'roas', 'demand'
    service_type VARCHAR(50),
    training_date DATETIME NOT NULL,
    training_samples INT NOT NULL,
    test_samples INT,
    feature_count INT NOT NULL,
    features_used JSON,  -- List of feature names used
    model_path VARCHAR(255),  -- Path to saved model file
    hyperparameters JSON,  -- Model configuration
    performance_metrics JSON,  -- {'mae': 12.5, 'rmse': 18.3, 'r2': 0.85, etc.}
    is_active BOOLEAN DEFAULT FALSE,
    version INT DEFAULT 1,
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_account_model (account_id, model_name),
    INDEX idx_model_type (model_type),
    INDEX idx_is_active (is_active),
    INDEX idx_training_date (training_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ML Predictions - Store predictions made by ML models
CREATE TABLE IF NOT EXISTS ml_predictions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    model_id INT NOT NULL,
    account_id INT NOT NULL,
    campaign_id INT,
    prediction_date DATE NOT NULL,
    prediction_type VARCHAR(50) NOT NULL,  -- 'daily_conversions', 'daily_cpl', 'monthly_demand', etc.
    predicted_value DECIMAL(10,2) NOT NULL,
    confidence_lower DECIMAL(10,2),  -- Lower bound of confidence interval
    confidence_upper DECIMAL(10,2),  -- Upper bound of confidence interval
    actual_value DECIMAL(10,2),  -- Filled in after actual data is available
    prediction_error DECIMAL(10,2),  -- actual - predicted
    features_snapshot JSON,  -- Feature values used for this prediction
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_model (model_id),
    INDEX idx_account_campaign (account_id, campaign_id),
    INDEX idx_prediction_date (prediction_date),
    FOREIGN KEY (model_id) REFERENCES ml_models(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- Auto Budget Adjustment Settings - Per-account configuration
CREATE TABLE IF NOT EXISTS auto_budget_settings (
    id INT AUTO_INCREMENT PRIMARY KEY,
    account_id INT NOT NULL UNIQUE,
    enabled BOOLEAN DEFAULT FALSE,
    total_monthly_budget_cents INT NOT NULL,
    min_daily_budget_cents INT DEFAULT 1000,  -- $10 minimum
    max_daily_budget_cents INT DEFAULT 100000,  -- $1000 maximum
    max_adjustment_pct DECIMAL(5,2) DEFAULT 50.00,  -- Don't change budget by more than 50% at once
    min_adjustment_pct DECIMAL(5,2) DEFAULT 5.00,  -- Only adjust if change is >5%
    enable_weather_adjustments BOOLEAN DEFAULT TRUE,
    enable_capacity_adjustments BOOLEAN DEFAULT TRUE,
    enable_competitive_adjustments BOOLEAN DEFAULT TRUE,
    enable_seasonality_adjustments BOOLEAN DEFAULT TRUE,
    adjustment_frequency VARCHAR(20) DEFAULT 'daily',  -- 'hourly', 'daily', 'weekly'
    notification_enabled BOOLEAN DEFAULT TRUE,
    notification_user_ids JSON,  -- List of user IDs to notify
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_account (account_id),
    INDEX idx_enabled (enabled)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- Competitive Alerts - Track significant competitive changes
CREATE TABLE IF NOT EXISTS competitive_alerts (
    id INT AUTO_INCREMENT PRIMARY KEY,
    account_id INT NOT NULL,
    campaign_id INT NOT NULL,
    competitor_domain VARCHAR(255) NOT NULL,
    alert_type ENUM('new_competitor', 'position_change', 'budget_increase', 'budget_decrease', 'threat_increase', 'threat_decrease') NOT NULL,
    alert_date DATE NOT NULL,
    severity ENUM('info', 'low', 'medium', 'high') DEFAULT 'medium',
    metric_changed VARCHAR(50),  -- 'position_above_rate', 'impression_share', etc.
    old_value DECIMAL(5,4),
    new_value DECIMAL(5,4),
    change_pct DECIMAL(10,2),
    recommendation TEXT,
    is_acknowledged BOOLEAN DEFAULT FALSE,
    acknowledged_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_account_campaign (account_id, campaign_id),
    INDEX idx_competitor (competitor_domain),
    INDEX idx_alert_date (alert_date),
    INDEX idx_is_acknowledged (is_acknowledged)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
