-- Migration 021: Advanced Google Ads Intelligence Features
-- Adds tables for conversion scoring, intent classification, competitive tracking,
-- self-healing campaigns, experiments, anomaly detection, and forecasting

-- =====================================================
-- CONVERSION PROBABILITY & SCORING
-- =====================================================

CREATE TABLE IF NOT EXISTS ads_conversion_scores (
    id INT AUTO_INCREMENT PRIMARY KEY,
    account_id INT NOT NULL,

    -- Click/session identifiers
    click_id VARCHAR(255) NULL,
    session_id VARCHAR(255) NULL,
    gclid VARCHAR(255) NULL,

    -- Context
    keyword_id INT NULL,
    ad_id INT NULL,
    campaign_id INT NULL,
    search_query TEXT NULL,

    -- Scoring
    probability_score DECIMAL(5,4) NOT NULL, -- 0.0000 to 1.0000
    quality_indicators JSON NULL, -- signals used for scoring

    -- User context
    device VARCHAR(20) NULL,
    location VARCHAR(100) NULL,
    time_of_day TIME NULL,
    day_of_week TINYINT NULL,

    -- Outcomes
    converted BOOLEAN NULL,
    conversion_value DECIMAL(10,2) NULL,
    conversion_time DATETIME NULL,

    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_account_created (account_id, created_at),
    INDEX idx_click_id (click_id),
    INDEX idx_session_id (session_id),
    INDEX idx_probability (probability_score),
    INDEX idx_converted (converted)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =====================================================
-- SEARCH QUERY INTENT CLASSIFICATION
-- =====================================================

CREATE TABLE IF NOT EXISTS ads_query_intent_classification (
    id INT AUTO_INCREMENT PRIMARY KEY,
    account_id INT NOT NULL,

    search_query TEXT NOT NULL,
    query_normalized VARCHAR(500) NULL, -- normalized for grouping

    -- Intent classification
    intent_type ENUM(
        'emergency',
        'research',
        'price_shopping',
        'local',
        'brand',
        'competitor',
        'informational',
        'transactional',
        'navigational'
    ) NOT NULL,
    confidence_score DECIMAL(5,4) NOT NULL,

    -- Intent signals
    signals JSON NULL, -- keywords, patterns detected

    -- Recommended actions
    recommended_bid_adjustment DECIMAL(6,2) NULL, -- percentage
    recommended_ad_extensions JSON NULL,
    recommended_landing_page VARCHAR(500) NULL,

    -- Performance tracking
    impressions INT DEFAULT 0,
    clicks INT DEFAULT 0,
    conversions INT DEFAULT 0,
    cost DECIMAL(10,2) DEFAULT 0,

    -- Metadata
    first_seen DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    classification_updated_at DATETIME NULL,

    INDEX idx_account_query (account_id, query_normalized),
    INDEX idx_intent_type (intent_type),
    INDEX idx_confidence (confidence_score),
    INDEX idx_last_seen (last_seen)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =====================================================
-- SMART BUDGET PACING
-- =====================================================

CREATE TABLE IF NOT EXISTS ads_budget_pacing_rules (
    id INT AUTO_INCREMENT PRIMARY KEY,
    account_id INT NOT NULL,
    campaign_id INT NULL, -- NULL = account-wide default

    rule_name VARCHAR(200) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    -- Time-based pacing
    hour_start TINYINT NOT NULL, -- 0-23
    hour_end TINYINT NOT NULL,
    budget_allocation_pct DECIMAL(5,2) NOT NULL, -- percentage of daily budget

    -- Day of week (1=Monday, 7=Sunday)
    days_of_week JSON NULL, -- [1,2,3,4,5] for weekdays

    -- Performance-based adjustments
    min_performance_score DECIMAL(5,2) NULL, -- pause if below
    max_cpa DECIMAL(10,2) NULL,

    -- Metadata
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    INDEX idx_account_campaign (account_id, campaign_id),
    INDEX idx_active (is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS ads_budget_pacing_history (
    id INT AUTO_INCREMENT PRIMARY KEY,
    account_id INT NOT NULL,
    campaign_id INT NULL,

    date DATE NOT NULL,
    hour TINYINT NOT NULL,

    budget_allocated DECIMAL(10,2) NOT NULL,
    budget_spent DECIMAL(10,2) NOT NULL,
    impressions INT DEFAULT 0,
    clicks INT DEFAULT 0,
    conversions INT DEFAULT 0,

    pacing_score DECIMAL(5,2) NULL, -- how well did we pace

    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE KEY uq_campaign_date_hour (campaign_id, date, hour),
    INDEX idx_account_date (account_id, date),
    INDEX idx_pacing_score (pacing_score)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =====================================================
-- NEGATIVE KEYWORD MINING
-- =====================================================

CREATE TABLE IF NOT EXISTS ads_negative_keyword_suggestions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    account_id INT NOT NULL,
    campaign_id INT NULL,
    ad_group_id INT NULL,

    search_query TEXT NOT NULL,
    query_normalized VARCHAR(500) NULL,

    -- Why it's negative
    negative_reason ENUM(
        'irrelevant_intent',
        'job_search',
        'diy_intent',
        'student_homework',
        'free_cheap',
        'competitor_brand',
        'wrong_location',
        'other'
    ) NOT NULL,
    confidence_score DECIMAL(5,2) NOT NULL,

    -- NLP analysis
    detected_patterns JSON NULL,
    semantic_cluster VARCHAR(255) NULL,

    -- Impact data
    wasted_spend DECIMAL(10,2) DEFAULT 0,
    impressions INT DEFAULT 0,
    clicks INT DEFAULT 0,
    conversions INT DEFAULT 0,

    -- Recommendation
    suggested_match_type ENUM('BROAD', 'PHRASE', 'EXACT') NOT NULL DEFAULT 'PHRASE',
    suggested_level ENUM('ACCOUNT', 'CAMPAIGN', 'AD_GROUP') NOT NULL,

    -- Status
    status ENUM('pending', 'approved', 'rejected', 'applied') NOT NULL DEFAULT 'pending',
    reviewed_by_user_id INT NULL,
    reviewed_at DATETIME NULL,
    applied_at DATETIME NULL,

    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_account_status (account_id, status),
    INDEX idx_campaign (campaign_id),
    INDEX idx_confidence (confidence_score),
    INDEX idx_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =====================================================
-- QUALITY SCORE PREDICTION
-- =====================================================

CREATE TABLE IF NOT EXISTS ads_quality_score_predictions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    account_id INT NOT NULL,

    -- What we're predicting for
    keyword_id INT NULL,
    ad_id INT NULL,

    keyword_text VARCHAR(500) NULL,
    ad_headline TEXT NULL,
    landing_page_url VARCHAR(2048) NULL,

    -- Predictions
    predicted_quality_score DECIMAL(3,1) NOT NULL, -- 1.0 to 10.0
    predicted_ctr_score ENUM('Below Average', 'Average', 'Above Average') NULL,
    predicted_ad_relevance ENUM('Below Average', 'Average', 'Above Average') NULL,
    predicted_landing_page_exp ENUM('Below Average', 'Average', 'Above Average') NULL,

    -- Confidence & factors
    confidence_score DECIMAL(5,2) NOT NULL,
    improvement_factors JSON NULL,

    -- Actual vs predicted (after launch)
    actual_quality_score TINYINT NULL,
    actual_ctr DECIMAL(5,2) NULL,
    prediction_accuracy DECIMAL(5,2) NULL,

    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    measured_at DATETIME NULL,

    INDEX idx_account_created (account_id, created_at),
    INDEX idx_keyword (keyword_id),
    INDEX idx_predicted_qs (predicted_quality_score)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =====================================================
-- COMPETITIVE INTELLIGENCE
-- =====================================================

CREATE TABLE IF NOT EXISTS ads_auction_insights_history (
    id INT AUTO_INCREMENT PRIMARY KEY,
    account_id INT NOT NULL,
    campaign_id INT NULL,

    date DATE NOT NULL,

    -- Competitor domain
    competitor_domain VARCHAR(255) NOT NULL,

    -- Metrics
    impression_share DECIMAL(5,2) NULL,
    overlap_rate DECIMAL(5,2) NULL,
    position_above_rate DECIMAL(5,2) NULL,
    top_of_page_rate DECIMAL(5,2) NULL,
    absolute_top_of_page_rate DECIMAL(5,2) NULL,
    outranking_share DECIMAL(5,2) NULL,

    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE KEY uq_account_campaign_date_competitor (account_id, campaign_id, date, competitor_domain),
    INDEX idx_date (date),
    INDEX idx_competitor (competitor_domain)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS ads_competitor_ad_copy_tracking (
    id INT AUTO_INCREMENT PRIMARY KEY,
    account_id INT NOT NULL,

    competitor_domain VARCHAR(255) NOT NULL,
    keyword_tracked VARCHAR(500) NOT NULL,

    -- Ad copy
    headline TEXT NULL,
    description TEXT NULL,
    display_url VARCHAR(500) NULL,
    ad_extensions JSON NULL,

    -- When seen
    first_seen DATETIME NOT NULL,
    last_seen DATETIME NOT NULL,
    times_seen INT DEFAULT 1,

    -- Analysis
    unique_value_props JSON NULL, -- extracted USPs
    promotional_offers TEXT NULL,
    call_to_action VARCHAR(255) NULL,

    -- Status
    is_active BOOLEAN DEFAULT TRUE,

    INDEX idx_account_competitor (account_id, competitor_domain),
    INDEX idx_keyword (keyword_tracked),
    INDEX idx_last_seen (last_seen)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS ads_competitive_keyword_gaps (
    id INT AUTO_INCREMENT PRIMARY KEY,
    account_id INT NOT NULL,

    keyword_text VARCHAR(500) NOT NULL,
    competitor_domains JSON NOT NULL, -- which competitors rank for this

    -- Estimates
    estimated_monthly_searches INT NULL,
    estimated_cpc DECIMAL(10,2) NULL,
    estimated_competition ENUM('LOW', 'MEDIUM', 'HIGH') NULL,

    -- Opportunity score
    opportunity_score DECIMAL(5,2) NULL, -- 0-100
    relevance_score DECIMAL(5,2) NULL,

    -- Status
    status ENUM('identified', 'under_review', 'added', 'rejected') NOT NULL DEFAULT 'identified',
    added_to_campaign_id INT NULL,

    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    INDEX idx_account_status (account_id, status),
    INDEX idx_opportunity (opportunity_score),
    INDEX idx_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =====================================================
-- SELF-HEALING CAMPAIGNS
-- =====================================================

CREATE TABLE IF NOT EXISTS ads_self_healing_rules (
    id INT AUTO_INCREMENT PRIMARY KEY,
    account_id INT NOT NULL,

    rule_name VARCHAR(200) NOT NULL,
    rule_type ENUM(
        'pause_low_ctr',
        'increase_bid_low_position',
        'decrease_bid_high_cpa',
        'add_exact_from_broad',
        'pause_high_spend_no_conversion',
        'auto_negative_keywords',
        'budget_redistribution'
    ) NOT NULL,

    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    requires_approval BOOLEAN NOT NULL DEFAULT FALSE,

    -- Trigger conditions (JSON)
    conditions JSON NOT NULL,
    -- Example: {"ctr_below": 0.01, "min_impressions": 100}

    -- Actions to take (JSON)
    actions JSON NOT NULL,
    -- Example: {"action": "pause", "notify": true}

    -- Scope
    apply_to_campaigns JSON NULL, -- campaign IDs, NULL = all
    apply_to_ad_groups JSON NULL,

    -- Limits
    max_actions_per_day INT DEFAULT 10,

    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    INDEX idx_account_active (account_id, is_active),
    INDEX idx_rule_type (rule_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS ads_self_healing_actions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    account_id INT NOT NULL,
    rule_id INT NOT NULL,

    -- What was affected
    entity_type ENUM('campaign', 'ad_group', 'keyword', 'ad') NOT NULL,
    entity_id INT NOT NULL,
    entity_name VARCHAR(500) NULL,

    -- Action taken
    action_type VARCHAR(100) NOT NULL,
    action_details JSON NULL,

    -- Trigger data
    trigger_metrics JSON NULL,

    -- Status
    status ENUM('pending_approval', 'approved', 'rejected', 'applied', 'failed') NOT NULL DEFAULT 'applied',
    approved_by_user_id INT NULL,
    approved_at DATETIME NULL,

    -- Results
    result_message TEXT NULL,
    error_message TEXT NULL,

    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_account_created (account_id, created_at),
    INDEX idx_rule (rule_id),
    INDEX idx_status (status),
    INDEX idx_entity (entity_type, entity_id),

    FOREIGN KEY (rule_id) REFERENCES ads_self_healing_rules(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =====================================================
-- BUDGET REALLOCATION ENGINE
-- =====================================================

CREATE TABLE IF NOT EXISTS ads_budget_reallocation_history (
    id INT AUTO_INCREMENT PRIMARY KEY,
    account_id INT NOT NULL,

    date DATE NOT NULL,

    -- Source campaign (money taken from)
    from_campaign_id INT NOT NULL,
    from_campaign_name VARCHAR(255) NULL,
    from_previous_budget DECIMAL(10,2) NOT NULL,

    -- Destination campaign (money added to)
    to_campaign_id INT NOT NULL,
    to_campaign_name VARCHAR(255) NULL,
    to_previous_budget DECIMAL(10,2) NOT NULL,

    -- Amount moved
    amount_reallocated DECIMAL(10,2) NOT NULL,

    -- Why
    reallocation_reason TEXT NULL,
    performance_metrics JSON NULL,

    -- Results (measured after N days)
    improvement_metrics JSON NULL,
    roi_improvement DECIMAL(5,2) NULL,

    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_account_date (account_id, date),
    INDEX idx_from_campaign (from_campaign_id),
    INDEX idx_to_campaign (to_campaign_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =====================================================
-- EXPERIMENT FRAMEWORK
-- =====================================================

CREATE TABLE IF NOT EXISTS ads_experiments (
    id INT AUTO_INCREMENT PRIMARY KEY,
    account_id INT NOT NULL,

    experiment_name VARCHAR(255) NOT NULL,
    experiment_type ENUM(
        'bidding_strategy',
        'match_type',
        'ad_copy',
        'landing_page',
        'audience',
        'dayparting',
        'device_targeting'
    ) NOT NULL,

    hypothesis TEXT NULL,

    -- Test configuration
    control_config JSON NOT NULL,
    variant_config JSON NOT NULL,

    -- Traffic split
    traffic_split_pct DECIMAL(5,2) NOT NULL DEFAULT 50.00, -- % to variant

    -- Campaigns involved
    control_campaign_ids JSON NULL,
    variant_campaign_ids JSON NULL,

    -- Success metrics
    primary_metric VARCHAR(100) NOT NULL, -- 'cpa', 'roas', 'ctr', 'cvr'
    minimum_improvement_pct DECIMAL(5,2) NOT NULL DEFAULT 10.00,
    minimum_sample_size INT NOT NULL DEFAULT 100,

    -- Status
    status ENUM('draft', 'running', 'completed', 'stopped', 'winner_applied') NOT NULL DEFAULT 'draft',

    -- Results
    control_metrics JSON NULL,
    variant_metrics JSON NULL,
    statistical_significance DECIMAL(5,4) NULL, -- p-value
    winner VARCHAR(20) NULL, -- 'control', 'variant', 'inconclusive'

    -- Dates
    start_date DATE NULL,
    end_date DATE NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at DATETIME NULL,

    INDEX idx_account_status (account_id, status),
    INDEX idx_type (experiment_type),
    INDEX idx_dates (start_date, end_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =====================================================
-- ANOMALY DETECTION
-- =====================================================

CREATE TABLE IF NOT EXISTS ads_anomalies (
    id INT AUTO_INCREMENT PRIMARY KEY,
    account_id INT NOT NULL,

    -- What entity has the anomaly
    entity_type ENUM('account', 'campaign', 'ad_group', 'keyword', 'ad') NOT NULL,
    entity_id INT NULL,
    entity_name VARCHAR(500) NULL,

    -- Anomaly details
    metric_name VARCHAR(100) NOT NULL, -- 'ctr', 'cpc', 'conversions', etc
    anomaly_type ENUM('spike', 'drop', 'trend_change', 'outlier') NOT NULL,

    -- Values
    expected_value DECIMAL(12,2) NULL,
    actual_value DECIMAL(12,2) NOT NULL,
    deviation_pct DECIMAL(6,2) NULL,

    -- Severity
    severity ENUM('critical', 'warning', 'info') NOT NULL,
    confidence_score DECIMAL(5,4) NOT NULL,

    -- Root cause analysis
    probable_causes JSON NULL,
    -- Example: [{"cause": "Position decreased from 2.1 to 3.8", "confidence": 0.85}]

    recommended_actions JSON NULL,

    -- Status
    status ENUM('new', 'acknowledged', 'investigating', 'resolved', 'false_positive') NOT NULL DEFAULT 'new',
    acknowledged_by_user_id INT NULL,
    acknowledged_at DATETIME NULL,
    resolution_notes TEXT NULL,

    -- Dates
    detected_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    occurred_at DATETIME NULL, -- when the anomaly actually happened
    resolved_at DATETIME NULL,

    INDEX idx_account_status (account_id, status),
    INDEX idx_severity (severity),
    INDEX idx_detected (detected_at),
    INDEX idx_entity (entity_type, entity_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =====================================================
-- VOICE SEARCH OPTIMIZATION
-- =====================================================

CREATE TABLE IF NOT EXISTS ads_voice_search_queries (
    id INT AUTO_INCREMENT PRIMARY KEY,
    account_id INT NOT NULL,

    search_query TEXT NOT NULL,
    query_normalized VARCHAR(500) NULL,

    -- Voice search indicators
    is_question BOOLEAN DEFAULT FALSE,
    is_long_tail BOOLEAN DEFAULT FALSE, -- 5+ words
    has_local_intent BOOLEAN DEFAULT FALSE,
    has_action_intent BOOLEAN DEFAULT FALSE, -- "near me", "open now"

    -- Question type
    question_type ENUM('who', 'what', 'where', 'when', 'why', 'how', 'none') NULL,

    -- Performance
    impressions INT DEFAULT 0,
    clicks INT DEFAULT 0,
    conversions INT DEFAULT 0,

    -- Optimization recommendations
    suggested_keywords JSON NULL,
    suggested_ad_copy JSON NULL,

    first_seen DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_account (account_id),
    INDEX idx_question (is_question),
    INDEX idx_local (has_local_intent),
    INDEX idx_last_seen (last_seen)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =====================================================
-- SEASONAL FORECASTING
-- =====================================================

CREATE TABLE IF NOT EXISTS ads_seasonal_forecasts (
    id INT AUTO_INCREMENT PRIMARY KEY,
    account_id INT NOT NULL,
    campaign_id INT NULL,

    -- Forecast period
    forecast_for_date DATE NOT NULL,
    forecast_for_month TINYINT NULL, -- 1-12
    forecast_for_week TINYINT NULL, -- 1-53

    -- Service/keyword category
    category VARCHAR(255) NULL, -- 'HVAC', 'Plumbing', 'Roofing', etc
    keyword_group VARCHAR(255) NULL,

    -- Historical baseline
    historical_avg DECIMAL(12,2) NULL,
    historical_stddev DECIMAL(12,2) NULL,

    -- Forecast
    predicted_search_volume INT NULL,
    predicted_cpc DECIMAL(10,2) NULL,
    predicted_conversion_rate DECIMAL(5,4) NULL,
    predicted_leads INT NULL,

    -- Confidence & factors
    confidence_score DECIMAL(5,2) NOT NULL,
    influencing_factors JSON NULL,
    -- Example: [{"factor": "Temperature forecast >95F", "impact": "+40%"}]

    -- Recommendations
    recommended_budget DECIMAL(10,2) NULL,
    recommended_budget_change_pct DECIMAL(6,2) NULL,
    recommended_actions JSON NULL,

    -- Accuracy tracking
    actual_volume INT NULL,
    actual_cpc DECIMAL(10,2) NULL,
    forecast_accuracy DECIMAL(5,2) NULL,

    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    measured_at DATETIME NULL,

    UNIQUE KEY uq_account_campaign_date (account_id, campaign_id, forecast_for_date),
    INDEX idx_forecast_date (forecast_for_date),
    INDEX idx_category (category),
    INDEX idx_confidence (confidence_score)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =====================================================
-- WHAT-IF SCENARIO ANALYSIS
-- =====================================================

CREATE TABLE IF NOT EXISTS ads_what_if_scenarios (
    id INT AUTO_INCREMENT PRIMARY KEY,
    account_id INT NOT NULL,
    created_by_user_id INT NULL,

    scenario_name VARCHAR(255) NOT NULL,
    scenario_type ENUM(
        'budget_change',
        'bid_adjustment',
        'keyword_changes',
        'geo_changes',
        'schedule_changes'
    ) NOT NULL,

    -- Current state
    baseline_metrics JSON NOT NULL,

    -- Proposed changes
    changes JSON NOT NULL,
    -- Example: {"budget_increase_pct": 30, "from": 1000, "to": 1300}

    -- Predictions
    predicted_metrics JSON NOT NULL,
    prediction_confidence DECIMAL(5,2) NULL,

    -- Analysis
    expected_roi_change DECIMAL(6,2) NULL,
    expected_lead_change INT NULL,
    expected_cpa_change DECIMAL(6,2) NULL,

    risk_assessment ENUM('low', 'medium', 'high') NULL,

    -- Status
    status ENUM('draft', 'analyzed', 'applied', 'archived') NOT NULL DEFAULT 'draft',
    applied_at DATETIME NULL,

    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_account_type (account_id, scenario_type),
    INDEX idx_status (status),
    INDEX idx_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =====================================================
-- IMPRESSION SHARE FORECASTING
-- =====================================================

CREATE TABLE IF NOT EXISTS ads_impression_share_forecasts (
    id INT AUTO_INCREMENT PRIMARY KEY,
    account_id INT NOT NULL,
    campaign_id INT NOT NULL,

    -- Current state
    current_budget DECIMAL(10,2) NOT NULL,
    current_impression_share DECIMAL(5,2) NULL,
    current_lost_is_budget DECIMAL(5,2) NULL,
    current_lost_is_rank DECIMAL(5,2) NULL,

    -- Forecast scenarios (different budget levels)
    forecast_scenarios JSON NOT NULL,
    -- Example: [
    --   {"budget_increase": 500, "predicted_is": 0.72, "predicted_conversions": 23, "predicted_cpa": 48},
    --   {"budget_increase": 1000, "predicted_is": 0.85, "predicted_conversions": 41, "predicted_cpa": 52}
    -- ]

    -- Optimal recommendation
    recommended_budget DECIMAL(10,2) NULL,
    recommended_budget_reason TEXT NULL,

    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_account_campaign (account_id, campaign_id),
    INDEX idx_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
