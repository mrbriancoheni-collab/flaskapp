-- Migration 016: Add Budget Intelligence Tables
-- Creates tables for: Auto-Budget Adjustment, Capacity Tracking, ML Training, Competitive Intelligence
-- Run this SQL in your MySQL database

-- ============================================
-- 1. AUTO-BUDGET ADJUSTMENT TABLES
-- ============================================

-- Auto-budget settings per account
CREATE TABLE IF NOT EXISTS auto_budget_settings (
    id INT AUTO_INCREMENT PRIMARY KEY,
    account_id INT NOT NULL,
    customer_id VARCHAR(50) NOT NULL,
    enabled BOOLEAN DEFAULT FALSE,
    monthly_budget_target DECIMAL(10, 2) NOT NULL,
    min_daily_budget DECIMAL(10, 2) DEFAULT 10.00,
    max_daily_budget DECIMAL(10, 2) DEFAULT 1000.00,
    adjustment_frequency ENUM('hourly', 'daily', 'weekly') DEFAULT 'daily',
    performance_weight DECIMAL(3, 2) DEFAULT 0.70 COMMENT 'Weight for performance-based distribution',
    seasonality_weight DECIMAL(3, 2) DEFAULT 0.20 COMMENT 'Weight for seasonality adjustments',
    capacity_weight DECIMAL(3, 2) DEFAULT 0.10 COMMENT 'Weight for capacity constraints',
    send_notifications BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY unique_account (account_id, customer_id),
    INDEX idx_account (account_id),
    INDEX idx_customer (customer_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Budget change audit trail
CREATE TABLE IF NOT EXISTS budget_change_log (
    id INT AUTO_INCREMENT PRIMARY KEY,
    account_id INT NOT NULL,
    customer_id VARCHAR(50) NOT NULL,
    campaign_id VARCHAR(50) NOT NULL,
    campaign_name VARCHAR(255),
    change_type ENUM('increase', 'decrease', 'redistribute', 'pause', 'resume') NOT NULL,
    old_budget DECIMAL(10, 2),
    new_budget DECIMAL(10, 2),
    change_amount DECIMAL(10, 2),
    change_pct DECIMAL(5, 2),
    reason VARCHAR(500) COMMENT 'Why the adjustment was made',
    triggered_by ENUM('auto', 'manual', 'agent', 'capacity', 'seasonality', 'competitive') DEFAULT 'auto',
    agent_id VARCHAR(100) COMMENT 'Which agent made the decision',
    confidence_score DECIMAL(3, 2) COMMENT 'Agent confidence 0-1',
    projected_monthly_spend DECIMAL(10, 2),
    actual_monthly_spend DECIMAL(10, 2),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_account (account_id),
    INDEX idx_customer (customer_id),
    INDEX idx_campaign (campaign_id),
    INDEX idx_created_at (created_at),
    INDEX idx_triggered_by (triggered_by)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- User notifications for budget changes
CREATE TABLE IF NOT EXISTS user_notifications (
    id INT AUTO_INCREMENT PRIMARY KEY,
    account_id INT NOT NULL,
    user_id INT,
    notification_type ENUM('budget_change', 'capacity_alert', 'competitive_threat', 'ml_prediction', 'anomaly') NOT NULL,
    severity ENUM('info', 'warning', 'critical') DEFAULT 'info',
    title VARCHAR(255) NOT NULL,
    message TEXT NOT NULL,
    action_url VARCHAR(500) COMMENT 'Link to take action',
    is_read BOOLEAN DEFAULT FALSE,
    is_dismissed BOOLEAN DEFAULT FALSE,
    related_entity_type VARCHAR(50) COMMENT 'campaign, keyword, ad_group',
    related_entity_id VARCHAR(50),
    metadata JSON COMMENT 'Additional structured data',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    read_at TIMESTAMP NULL,
    dismissed_at TIMESTAMP NULL,
    INDEX idx_account_user (account_id, user_id),
    INDEX idx_type (notification_type),
    INDEX idx_is_read (is_read),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================
-- 2. CAPACITY TRACKING TABLES
-- ============================================

-- Daily capacity tracking (no CRM needed!)
CREATE TABLE IF NOT EXISTS capacity_tracking (
    id INT AUTO_INCREMENT PRIMARY KEY,
    account_id INT NOT NULL,
    tracking_date DATE NOT NULL,
    total_capacity INT NOT NULL COMMENT 'Total appointment slots available',
    booked_slots INT DEFAULT 0 COMMENT 'Number of slots filled',
    available_slots INT DEFAULT 0 COMMENT 'Remaining slots',
    utilization_pct DECIMAL(5, 2) DEFAULT 0 COMMENT 'Booked / Total * 100',
    num_technicians INT COMMENT 'Number of techs working',
    slots_per_tech INT COMMENT 'Appointments per tech',
    budget_recommendation ENUM('increase', 'maintain', 'decrease', 'pause') DEFAULT 'maintain',
    recommended_budget_change_pct DECIMAL(5, 2) DEFAULT 0,
    notes TEXT COMMENT 'Manual notes about capacity',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY unique_account_date (account_id, tracking_date),
    INDEX idx_account (account_id),
    INDEX idx_tracking_date (tracking_date),
    INDEX idx_utilization (utilization_pct)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Individual booking log
CREATE TABLE IF NOT EXISTS capacity_bookings (
    id INT AUTO_INCREMENT PRIMARY KEY,
    capacity_tracking_id INT NOT NULL,
    account_id INT NOT NULL,
    booking_date DATE NOT NULL,
    booking_time TIME NOT NULL,
    customer_name VARCHAR(255),
    service_type VARCHAR(100),
    lead_source ENUM('google_ads', 'organic', 'facebook_ads', 'direct', 'referral', 'other') DEFAULT 'other',
    campaign_id VARCHAR(50) COMMENT 'If from Google Ads',
    technician_assigned VARCHAR(100),
    status ENUM('scheduled', 'completed', 'cancelled', 'no_show') DEFAULT 'scheduled',
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (capacity_tracking_id) REFERENCES capacity_tracking(id) ON DELETE CASCADE,
    INDEX idx_capacity_tracking (capacity_tracking_id),
    INDEX idx_account (account_id),
    INDEX idx_booking_date (booking_date),
    INDEX idx_lead_source (lead_source),
    INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================
-- 3. ML TRAINING & PREDICTION TABLES
-- ============================================

-- ML model metadata
CREATE TABLE IF NOT EXISTS ml_models (
    id INT AUTO_INCREMENT PRIMARY KEY,
    account_id INT NOT NULL,
    model_name VARCHAR(100) NOT NULL COMMENT 'demand_forecaster, cpl_predictor, conversion_predictor',
    model_version VARCHAR(50) NOT NULL,
    model_type VARCHAR(50) COMMENT 'random_forest, xgboost, neural_net',
    training_date TIMESTAMP NOT NULL,
    training_samples INT COMMENT 'Number of records used for training',
    features_used JSON COMMENT 'List of features',
    hyperparameters JSON COMMENT 'Model configuration',
    accuracy_score DECIMAL(5, 4) COMMENT 'Overall accuracy',
    mae DECIMAL(10, 4) COMMENT 'Mean Absolute Error',
    rmse DECIMAL(10, 4) COMMENT 'Root Mean Squared Error',
    r2_score DECIMAL(5, 4) COMMENT 'R-squared for regression',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_account (account_id),
    INDEX idx_model_name (model_name),
    INDEX idx_is_active (is_active),
    UNIQUE KEY unique_model_version (account_id, model_name, model_version)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ML predictions log
CREATE TABLE IF NOT EXISTS ml_predictions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    ml_model_id INT NOT NULL,
    account_id INT NOT NULL,
    prediction_date DATE NOT NULL,
    prediction_type ENUM('demand', 'cpl', 'conversions', 'roas') NOT NULL,
    campaign_id VARCHAR(50),
    predicted_value DECIMAL(10, 4) NOT NULL,
    confidence_interval_lower DECIMAL(10, 4),
    confidence_interval_upper DECIMAL(10, 4),
    confidence_score DECIMAL(3, 2) COMMENT '0-1 confidence',
    actual_value DECIMAL(10, 4) COMMENT 'Filled in after the date passes',
    prediction_error DECIMAL(10, 4) COMMENT 'predicted - actual',
    features_snapshot JSON COMMENT 'Feature values used for prediction',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    actual_recorded_at TIMESTAMP NULL,
    FOREIGN KEY (ml_model_id) REFERENCES ml_models(id) ON DELETE CASCADE,
    INDEX idx_model (ml_model_id),
    INDEX idx_account (account_id),
    INDEX idx_prediction_date (prediction_date),
    INDEX idx_prediction_type (prediction_type),
    INDEX idx_campaign (campaign_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================
-- 4. COMPETITIVE INTELLIGENCE TABLES
-- ============================================

-- Competitive auction insights from Google Ads API
CREATE TABLE IF NOT EXISTS competitive_auction_insights (
    id INT AUTO_INCREMENT PRIMARY KEY,
    account_id INT NOT NULL,
    customer_id VARCHAR(50) NOT NULL,
    campaign_id VARCHAR(50),
    report_date DATE NOT NULL,
    competitor_domain VARCHAR(255) NOT NULL,
    impression_share DECIMAL(5, 2) COMMENT 'What % of auctions competitor appears',
    overlap_rate DECIMAL(5, 2) COMMENT 'How often you compete directly',
    position_above_rate DECIMAL(5, 2) COMMENT 'How often they outrank you',
    outranking_share DECIMAL(5, 2) COMMENT 'How often you outrank them',
    top_of_page_rate DECIMAL(5, 2) COMMENT 'Their top position %',
    absolute_top_of_page_rate DECIMAL(5, 2) COMMENT 'Their #1 position %',
    estimated_daily_budget DECIMAL(10, 2) COMMENT 'Estimated from impression share',
    threat_level ENUM('low', 'medium', 'high', 'critical') DEFAULT 'medium',
    budget_recommendation VARCHAR(500),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_account (account_id),
    INDEX idx_customer (customer_id),
    INDEX idx_campaign (campaign_id),
    INDEX idx_report_date (report_date),
    INDEX idx_competitor (competitor_domain),
    INDEX idx_threat_level (threat_level),
    UNIQUE KEY unique_competitor_report (account_id, customer_id, campaign_id, report_date, competitor_domain)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Competitive alerts (significant changes)
CREATE TABLE IF NOT EXISTS competitive_alerts (
    id INT AUTO_INCREMENT PRIMARY KEY,
    account_id INT NOT NULL,
    customer_id VARCHAR(50) NOT NULL,
    campaign_id VARCHAR(50),
    competitor_domain VARCHAR(255) NOT NULL,
    alert_type ENUM('new_competitor', 'increased_aggression', 'decreased_presence', 'budget_spike', 'lost_position') NOT NULL,
    severity ENUM('info', 'warning', 'critical') DEFAULT 'warning',
    metric_name VARCHAR(100) COMMENT 'impression_share, position_above_rate, etc',
    old_value DECIMAL(10, 4),
    new_value DECIMAL(10, 4),
    change_pct DECIMAL(5, 2),
    description TEXT,
    recommended_action VARCHAR(500),
    is_addressed BOOLEAN DEFAULT FALSE,
    addressed_at TIMESTAMP NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_account (account_id),
    INDEX idx_customer (customer_id),
    INDEX idx_alert_type (alert_type),
    INDEX idx_severity (severity),
    INDEX idx_is_addressed (is_addressed),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================
-- GRANT PERMISSIONS (adjust username as needed)
-- ============================================

-- GRANT ALL PRIVILEGES ON your_database.* TO 'your_user'@'localhost';
-- FLUSH PRIVILEGES;

-- ============================================
-- VERIFICATION QUERIES
-- ============================================

-- Run these to verify tables were created:
-- SHOW TABLES LIKE '%auto_budget%';
-- SHOW TABLES LIKE '%capacity%';
-- SHOW TABLES LIKE '%ml_%';
-- SHOW TABLES LIKE '%competitive%';

-- Check table structures:
-- DESCRIBE auto_budget_settings;
-- DESCRIBE budget_change_log;
-- DESCRIBE user_notifications;
-- DESCRIBE capacity_tracking;
-- DESCRIBE capacity_bookings;
-- DESCRIBE ml_models;
-- DESCRIBE ml_predictions;
-- DESCRIBE competitive_auction_insights;
-- DESCRIBE competitive_alerts;
