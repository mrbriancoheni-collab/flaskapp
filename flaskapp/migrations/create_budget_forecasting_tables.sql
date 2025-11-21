-- ============================================================================
-- Budget Forecasting & Historical Data - Phase 1
-- ============================================================================
-- Comprehensive historical tracking and forecasting for intelligent budget management

-- ============================================================================
-- Campaign Performance History - Daily snapshots for trend analysis
-- ============================================================================
CREATE TABLE IF NOT EXISTS campaign_performance_history (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- Campaign identification
    account_id INT NOT NULL,
    campaign_id INT NOT NULL,
    campaign_name VARCHAR(255) NOT NULL,

    -- Date tracking
    date DATE NOT NULL,
    day_of_week TINYINT NOT NULL,  -- 1=Monday, 7=Sunday
    week_of_month TINYINT NOT NULL,  -- 1-5
    month INT NOT NULL,  -- 1-12
    year INT NOT NULL,

    -- Performance metrics
    impressions INT DEFAULT 0,
    clicks INT DEFAULT 0,
    conversions DECIMAL(10,2) DEFAULT 0,
    cost_cents INT DEFAULT 0,
    revenue_cents INT DEFAULT 0,

    -- Calculated metrics
    ctr DECIMAL(5,4) DEFAULT 0,  -- Click-through rate
    cpl_cents INT DEFAULT 0,  -- Cost per lead
    conversion_rate DECIMAL(5,4) DEFAULT 0,
    roas DECIMAL(10,2) DEFAULT 0,  -- Return on ad spend

    -- Quality metrics
    avg_quality_score DECIMAL(3,1) DEFAULT 0,
    avg_position DECIMAL(4,2) DEFAULT 0,
    impression_share DECIMAL(5,4) DEFAULT 0,

    -- External factors
    weather_temp_high INT DEFAULT NULL,  -- Fahrenheit
    weather_temp_low INT DEFAULT NULL,
    weather_condition VARCHAR(50) DEFAULT NULL,  -- sunny, rain, snow, etc.
    was_holiday BOOLEAN DEFAULT FALSE,

    -- Metadata
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Indexes
    UNIQUE KEY unique_campaign_date (campaign_id, date),
    INDEX idx_account_date (account_id, date),
    INDEX idx_date (date),
    INDEX idx_month_year (month, year),
    INDEX idx_day_of_week (day_of_week),

    -- Foreign keys
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
    FOREIGN KEY (campaign_id) REFERENCES ads_campaigns(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ============================================================================
-- Service Seasonality Curves - Industry-specific seasonal patterns
-- ============================================================================
CREATE TABLE IF NOT EXISTS service_seasonality_curves (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- Service type
    service_type VARCHAR(50) NOT NULL,  -- hvac_ac, hvac_heat, plumbing, electrical, roofing, etc.
    service_category VARCHAR(50) NOT NULL,  -- emergency, maintenance, installation, repair

    -- Time period
    month INT NOT NULL,  -- 1-12
    week_of_month TINYINT DEFAULT NULL,  -- 1-5 (optional for more granular)

    -- Seasonality multipliers (1.0 = baseline)
    demand_multiplier DECIMAL(4,2) NOT NULL DEFAULT 1.0,  -- Expected demand vs baseline
    cpl_multiplier DECIMAL(4,2) NOT NULL DEFAULT 1.0,  -- Expected CPL vs baseline
    conversion_rate_multiplier DECIMAL(4,2) NOT NULL DEFAULT 1.0,

    -- Weather triggers
    trigger_temp_high INT DEFAULT NULL,  -- Demand spikes above this temp (AC)
    trigger_temp_low INT DEFAULT NULL,  -- Demand spikes below this temp (Heat)
    trigger_weather_condition VARCHAR(50) DEFAULT NULL,  -- storm, freeze, heatwave

    -- Notes and context
    notes TEXT DEFAULT NULL,

    -- Data source
    source VARCHAR(50) DEFAULT 'industry_standard',  -- industry_standard, historical_data, manual
    confidence_score DECIMAL(3,2) DEFAULT 0.8,  -- 0-1 confidence in this multiplier

    -- Metadata
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- Indexes
    UNIQUE KEY unique_service_month (service_type, service_category, month, week_of_month),
    INDEX idx_service_type (service_type),
    INDEX idx_month (month)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ============================================================================
-- Weather History - Historical weather data for correlation analysis
-- ============================================================================
CREATE TABLE IF NOT EXISTS weather_history (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- Location
    zip_code VARCHAR(10) NOT NULL,
    city VARCHAR(100) DEFAULT NULL,
    state VARCHAR(2) DEFAULT NULL,

    -- Date
    date DATE NOT NULL,

    -- Temperature (Fahrenheit)
    temp_high INT NOT NULL,
    temp_low INT NOT NULL,
    temp_avg INT NOT NULL,
    feels_like_high INT DEFAULT NULL,
    feels_like_low INT DEFAULT NULL,

    -- Precipitation
    precipitation_inches DECIMAL(4,2) DEFAULT 0,
    snow_inches DECIMAL(4,2) DEFAULT 0,
    humidity_pct TINYINT DEFAULT NULL,

    -- Conditions
    condition VARCHAR(50) NOT NULL,  -- sunny, cloudy, rain, snow, storm, etc.
    wind_speed_mph INT DEFAULT NULL,
    is_extreme_weather BOOLEAN DEFAULT FALSE,  -- heat wave, cold snap, severe storm

    -- Alerts
    weather_alerts JSON DEFAULT NULL,  -- [{type: 'heat_advisory', severity: 'warning'}]

    -- Metadata
    data_source VARCHAR(50) DEFAULT 'weather_api',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Indexes
    UNIQUE KEY unique_zip_date (zip_code, date),
    INDEX idx_date (date),
    INDEX idx_zip (zip_code),
    INDEX idx_extreme (is_extreme_weather, date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ============================================================================
-- Budget Forecasts - Projected spend and performance
-- ============================================================================
CREATE TABLE IF NOT EXISTS budget_forecasts (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- Forecast metadata
    account_id INT NOT NULL,
    forecast_type VARCHAR(50) NOT NULL,  -- monthly, weekly, seasonal, annual
    forecast_date DATE NOT NULL,  -- Date this forecast was generated

    -- Forecast period
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,

    -- Budget projections
    projected_spend_cents INT NOT NULL,
    projected_leads INT NOT NULL,
    projected_revenue_cents INT NOT NULL,
    projected_roas DECIMAL(10,2) NOT NULL,

    -- Confidence and variance
    confidence_score DECIMAL(3,2) NOT NULL,  -- 0-1
    variance_low_cents INT NOT NULL,  -- Lower bound (pessimistic)
    variance_high_cents INT NOT NULL,  -- Upper bound (optimistic)

    -- Factors considered
    uses_historical_data BOOLEAN DEFAULT TRUE,
    uses_seasonality BOOLEAN DEFAULT TRUE,
    uses_weather_forecast BOOLEAN DEFAULT FALSE,
    uses_capacity_constraints BOOLEAN DEFAULT FALSE,
    uses_ml_model BOOLEAN DEFAULT FALSE,

    -- Model details
    model_version VARCHAR(50) DEFAULT NULL,
    input_features JSON DEFAULT NULL,  -- Features used in forecast

    -- Actual vs Forecast (filled in after period ends)
    actual_spend_cents INT DEFAULT NULL,
    actual_leads INT DEFAULT NULL,
    actual_revenue_cents INT DEFAULT NULL,
    forecast_accuracy DECIMAL(5,4) DEFAULT NULL,  -- 0-1

    -- Metadata
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- Indexes
    INDEX idx_account_period (account_id, period_start, period_end),
    INDEX idx_forecast_date (forecast_date),
    INDEX idx_period_start (period_start),

    -- Foreign keys
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ============================================================================
-- Capacity Tracking - Tech availability and booking status
-- ============================================================================
CREATE TABLE IF NOT EXISTS capacity_tracking (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- Account and date
    account_id INT NOT NULL,
    date DATE NOT NULL,
    service_type VARCHAR(50) NOT NULL,  -- hvac, plumbing, electrical, roofing

    -- Capacity metrics
    total_techs_available INT NOT NULL DEFAULT 0,
    total_appointment_slots INT NOT NULL DEFAULT 0,
    booked_slots INT NOT NULL DEFAULT 0,
    completed_jobs INT NOT NULL DEFAULT 0,
    cancelled_jobs INT NOT NULL DEFAULT 0,

    -- Calculated metrics
    capacity_utilization DECIMAL(5,4) NOT NULL DEFAULT 0,  -- booked/total
    booking_rate DECIMAL(5,4) DEFAULT 0,  -- completed/(booked+cancelled)

    -- Forward booking
    days_booked_out INT DEFAULT 0,  -- How many days out are we fully booked?
    next_available_slot DATETIME DEFAULT NULL,

    -- Recommendations
    should_reduce_budget BOOLEAN DEFAULT FALSE,
    should_increase_budget BOOLEAN DEFAULT FALSE,
    recommended_budget_adjustment_pct DECIMAL(5,2) DEFAULT 0,

    -- Metadata
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- Indexes
    UNIQUE KEY unique_account_date_service (account_id, date, service_type),
    INDEX idx_date (date),
    INDEX idx_utilization (capacity_utilization),

    -- Foreign keys
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ============================================================================
-- Budget Anomalies - Detected anomalies and alerts
-- ============================================================================
CREATE TABLE IF NOT EXISTS budget_anomalies (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- Anomaly identification
    account_id INT NOT NULL,
    campaign_id INT DEFAULT NULL,
    budget_group_id INT DEFAULT NULL,

    -- Detection metadata
    detected_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    anomaly_type VARCHAR(50) NOT NULL,  -- cpl_spike, conversion_drop, spend_surge, etc.
    severity VARCHAR(20) NOT NULL,  -- low, medium, high, critical

    -- Anomaly details
    metric_name VARCHAR(50) NOT NULL,  -- cpl, conversion_rate, daily_spend, etc.
    baseline_value DECIMAL(10,2) NOT NULL,
    actual_value DECIMAL(10,2) NOT NULL,
    deviation_pct DECIMAL(5,2) NOT NULL,  -- % difference from baseline

    -- Statistical measures
    z_score DECIMAL(5,2) DEFAULT NULL,  -- Standard deviations from mean
    confidence_score DECIMAL(3,2) NOT NULL,  -- 0-1

    -- Context
    possible_causes JSON DEFAULT NULL,  -- [{cause: 'weather_event', likelihood: 0.8}]
    affected_period_start DATE NOT NULL,
    affected_period_end DATE DEFAULT NULL,

    -- Actions taken
    alert_sent BOOLEAN DEFAULT FALSE,
    alert_sent_at DATETIME DEFAULT NULL,
    auto_action_taken VARCHAR(100) DEFAULT NULL,  -- paused_campaign, reduced_budget, etc.
    requires_manual_review BOOLEAN DEFAULT TRUE,

    -- Resolution
    resolved BOOLEAN DEFAULT FALSE,
    resolved_at DATETIME DEFAULT NULL,
    resolution_notes TEXT DEFAULT NULL,

    -- Metadata
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Indexes
    INDEX idx_account_detected (account_id, detected_at),
    INDEX idx_severity (severity, resolved),
    INDEX idx_anomaly_type (anomaly_type),
    INDEX idx_campaign (campaign_id),

    -- Foreign keys
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
    FOREIGN KEY (campaign_id) REFERENCES ads_campaigns(id) ON DELETE SET NULL,
    FOREIGN KEY (budget_group_id) REFERENCES campaign_budget_groups(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ============================================================================
-- Seed Data: Service Seasonality Curves (Industry Standards for Home Services)
-- ============================================================================

-- HVAC - Air Conditioning
INSERT INTO service_seasonality_curves (service_type, service_category, month, demand_multiplier, cpl_multiplier, conversion_rate_multiplier, trigger_temp_high, notes) VALUES
('hvac_ac', 'emergency', 5, 1.3, 1.2, 1.1, 85, 'May: AC season begins, demand increasing'),
('hvac_ac', 'emergency', 6, 2.0, 1.5, 1.2, 90, 'June: Peak AC demand starts, heat waves'),
('hvac_ac', 'emergency', 7, 2.5, 1.8, 1.3, 95, 'July: Peak AC emergency season'),
('hvac_ac', 'emergency', 8, 2.3, 1.7, 1.2, 95, 'August: Still peak AC season'),
('hvac_ac', 'emergency', 9, 1.4, 1.3, 1.1, 85, 'September: AC demand declining'),
('hvac_ac', 'maintenance', 4, 1.5, 0.9, 1.2, NULL, 'April: Pre-season AC tune-ups'),
('hvac_ac', 'maintenance', 5, 1.3, 0.9, 1.1, NULL, 'May: Spring maintenance season'),
('hvac_ac', 'installation', 3, 1.2, 0.9, 1.0, NULL, 'March: Pre-season AC installations'),
('hvac_ac', 'installation', 4, 1.4, 1.0, 1.1, NULL, 'April: AC installation peak');

-- HVAC - Heating
INSERT INTO service_seasonality_curves (service_type, service_category, month, demand_multiplier, cpl_multiplier, conversion_rate_multiplier, trigger_temp_low, notes) VALUES
('hvac_heat', 'emergency', 11, 1.5, 1.3, 1.2, 40, 'November: Heating season begins'),
('hvac_heat', 'emergency', 12, 2.2, 1.6, 1.3, 32, 'December: Peak heating emergency season'),
('hvac_heat', 'emergency', 1, 2.5, 1.8, 1.4, 20, 'January: Peak heating demand, cold snaps'),
('hvac_heat', 'emergency', 2, 2.3, 1.7, 1.3, 25, 'February: Still peak heating season'),
('hvac_heat', 'emergency', 3, 1.4, 1.2, 1.1, 35, 'March: Heating demand declining'),
('hvac_heat', 'maintenance', 9, 1.4, 0.9, 1.2, NULL, 'September: Pre-winter furnace tune-ups'),
('hvac_heat', 'maintenance', 10, 1.6, 0.9, 1.3, NULL, 'October: Peak fall maintenance'),
('hvac_heat', 'installation', 9, 1.2, 0.9, 1.1, NULL, 'September: Pre-winter installations'),
('hvac_heat', 'installation', 10, 1.3, 1.0, 1.1, NULL, 'October: Furnace replacement peak');

-- Plumbing
INSERT INTO service_seasonality_curves (service_type, service_category, month, demand_multiplier, cpl_multiplier, conversion_rate_multiplier, notes) VALUES
('plumbing', 'emergency', 11, 1.2, 1.1, 1.0, 'November: Thanksgiving drain issues'),
('plumbing', 'emergency', 12, 1.5, 1.3, 1.1, 'December: Holiday plumbing issues, frozen pipes start'),
('plumbing', 'emergency', 1, 1.8, 1.4, 1.2, 'January: Peak frozen pipe season'),
('plumbing', 'emergency', 2, 1.6, 1.3, 1.1, 'February: Continued freeze issues'),
('plumbing', 'repair', 3, 1.2, 1.0, 1.1, 'March: Spring plumbing repairs'),
('plumbing', 'repair', 4, 1.3, 1.0, 1.1, 'April: Spring repair season'),
('plumbing', 'installation', 5, 1.2, 1.0, 1.0, 'May: Water heater replacements'),
('plumbing', 'installation', 6, 1.1, 1.0, 1.0, 'June: Summer plumbing upgrades');

-- Electrical
INSERT INTO service_seasonality_curves (service_type, service_category, month, demand_multiplier, cpl_multiplier, conversion_rate_multiplier, notes) VALUES
('electrical', 'emergency', 6, 1.3, 1.1, 1.1, 'June: AC circuit breaker trips increase'),
('electrical', 'emergency', 7, 1.4, 1.2, 1.1, 'July: Peak electrical emergency (AC overload)'),
('electrical', 'emergency', 8, 1.3, 1.1, 1.1, 'August: Continued AC-related electrical issues'),
('electrical', 'repair', 4, 1.1, 1.0, 1.0, 'April: Spring electrical repairs'),
('electrical', 'repair', 5, 1.2, 1.0, 1.0, 'May: Outdoor lighting repairs'),
('electrical', 'installation', 11, 1.4, 1.1, 1.2, 'November: Holiday lighting installation'),
('electrical', 'installation', 12, 1.2, 1.1, 1.1, 'December: Last-minute holiday lights');

-- Roofing
INSERT INTO service_seasonality_curves (service_type, service_category, month, demand_multiplier, cpl_multiplier, conversion_rate_multiplier, notes) VALUES
('roofing', 'repair', 4, 1.4, 1.1, 1.2, 'April: Spring storm damage'),
('roofing', 'repair', 5, 1.5, 1.2, 1.2, 'May: Peak spring roofing'),
('roofing', 'repair', 6, 1.3, 1.1, 1.1, 'June: Summer roofing season'),
('roofing', 'repair', 9, 1.3, 1.1, 1.1, 'September: Hurricane season repairs'),
('roofing', 'installation', 5, 1.6, 1.2, 1.3, 'May: Peak roofing installation'),
('roofing', 'installation', 6, 1.5, 1.1, 1.2, 'June: Summer reroof season'),
('roofing', 'installation', 7, 1.4, 1.1, 1.2, 'July: Continued roofing season'),
('roofing', 'installation', 8, 1.3, 1.1, 1.1, 'August: Late summer projects');


-- ============================================================================
-- Comments
-- ============================================================================

COMMENT ON TABLE campaign_performance_history IS 'Daily performance snapshots for trend analysis and forecasting';
COMMENT ON TABLE service_seasonality_curves IS 'Industry-specific seasonal demand patterns and multipliers';
COMMENT ON TABLE weather_history IS 'Historical weather data for correlation with performance';
COMMENT ON TABLE budget_forecasts IS 'Budget and performance projections with confidence intervals';
COMMENT ON TABLE capacity_tracking IS 'Tech availability and booking capacity for budget pacing';
COMMENT ON TABLE budget_anomalies IS 'Detected anomalies in budget performance with alerts';
