-- Migration: Add tables and columns for Google Ads forecasting features
-- Created: 2026-01-28

-- 1. Add missing columns to gads_stats_daily
ALTER TABLE `gads_stats_daily`
  ADD COLUMN IF NOT EXISTS `account_id` int(11) DEFAULT NULL AFTER `id`,
  ADD COLUMN IF NOT EXISTS `entity_name` varchar(255) DEFAULT NULL AFTER `entity_id`,
  ADD COLUMN IF NOT EXISTS `avg_position` double DEFAULT NULL AFTER `lost_is_rank`,
  ADD COLUMN IF NOT EXISTS `max_cpc_micros` bigint(20) UNSIGNED DEFAULT NULL AFTER `avg_position`;

-- Add index for account_id on gads_stats_daily
CREATE INDEX IF NOT EXISTS `idx_gads_stats_account` ON `gads_stats_daily` (`account_id`);
CREATE INDEX IF NOT EXISTS `idx_gads_stats_account_date` ON `gads_stats_daily` (`account_id`, `date`);

-- 2. Create keyword_quality_scores table for tracking QS changes over time
CREATE TABLE IF NOT EXISTS `keyword_quality_scores` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `account_id` int(11) NOT NULL,
  `keyword_id` bigint(20) UNSIGNED DEFAULT NULL,
  `keyword_text` varchar(255) DEFAULT NULL,
  `ad_group_id` bigint(20) UNSIGNED DEFAULT NULL,
  `campaign_id` bigint(20) UNSIGNED DEFAULT NULL,
  `date` date NOT NULL,
  `quality_score` tinyint(3) UNSIGNED DEFAULT NULL COMMENT '1-10 quality score',
  `expected_ctr` varchar(20) DEFAULT NULL COMMENT 'ABOVE_AVERAGE, AVERAGE, BELOW_AVERAGE',
  `ad_relevance` varchar(20) DEFAULT NULL,
  `landing_page_experience` varchar(20) DEFAULT NULL,
  `historical_quality_score` tinyint(3) UNSIGNED DEFAULT NULL,
  `historical_expected_ctr` varchar(20) DEFAULT NULL,
  `historical_ad_relevance` varchar(20) DEFAULT NULL,
  `historical_landing_page_experience` varchar(20) DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_kqs_account` (`account_id`),
  KEY `idx_kqs_keyword` (`keyword_id`),
  KEY `idx_kqs_date` (`date`),
  KEY `idx_kqs_account_date` (`account_id`, `date`),
  KEY `idx_kqs_quality_score` (`quality_score`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Historical quality score tracking for anomaly detection';

-- 3. Create budget_anomalies table for forecasting
CREATE TABLE IF NOT EXISTS `budget_anomalies` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `account_id` int(11) NOT NULL,
  `campaign_id` varchar(50) DEFAULT NULL,
  `budget_group_id` int(11) DEFAULT NULL,
  `detected_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `anomaly_type` varchar(50) NOT NULL COMMENT 'spend_spike, spend_drop, ctr_drop, cpc_spike, etc.',
  `severity` varchar(20) NOT NULL COMMENT 'info, warning, critical',
  `metric_name` varchar(50) NOT NULL COMMENT 'spend, ctr, cpc, conversions, etc.',
  `baseline_value` decimal(12,4) DEFAULT NULL,
  `actual_value` decimal(12,4) DEFAULT NULL,
  `deviation_pct` decimal(8,2) DEFAULT NULL,
  `z_score` decimal(6,3) DEFAULT NULL,
  `confidence_score` decimal(5,4) DEFAULT NULL,
  `possible_causes` text DEFAULT NULL COMMENT 'JSON array of probable causes',
  `affected_period_start` date DEFAULT NULL,
  `affected_period_end` date DEFAULT NULL,
  `alert_sent` tinyint(1) DEFAULT 0,
  `auto_action_taken` tinyint(1) DEFAULT 0,
  `requires_manual_review` tinyint(1) DEFAULT 1,
  `resolved` tinyint(1) DEFAULT 0,
  `resolved_at` datetime DEFAULT NULL,
  `resolution_notes` text DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_budget_anomalies_account` (`account_id`),
  KEY `idx_budget_anomalies_campaign` (`campaign_id`),
  KEY `idx_budget_anomalies_type` (`anomaly_type`),
  KEY `idx_budget_anomalies_severity` (`severity`),
  KEY `idx_budget_anomalies_resolved` (`resolved`),
  KEY `idx_budget_anomalies_date` (`detected_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Detected budget and performance anomalies';

-- 4. Create campaign_performance_history table
CREATE TABLE IF NOT EXISTS `campaign_performance_history` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `account_id` int(11) NOT NULL,
  `campaign_id` varchar(50) NOT NULL,
  `campaign_name` varchar(255) DEFAULT NULL,
  `date` date NOT NULL,
  `day_of_week` tinyint(1) DEFAULT NULL COMMENT '0=Sunday, 6=Saturday',
  `week_of_month` tinyint(1) DEFAULT NULL,
  `month` tinyint(2) DEFAULT NULL,
  `year` smallint(4) DEFAULT NULL,
  `impressions` bigint(20) DEFAULT 0,
  `clicks` bigint(20) DEFAULT 0,
  `conversions` decimal(10,2) DEFAULT 0,
  `cost_cents` int(11) DEFAULT 0,
  `revenue_cents` int(11) DEFAULT 0,
  `ctr` decimal(8,4) DEFAULT NULL,
  `cpl_cents` int(11) DEFAULT NULL COMMENT 'Cost per lead in cents',
  `conversion_rate` decimal(8,4) DEFAULT NULL,
  `roas` decimal(10,4) DEFAULT NULL,
  `avg_quality_score` decimal(4,2) DEFAULT NULL,
  `avg_position` decimal(4,2) DEFAULT NULL,
  `impression_share` decimal(5,4) DEFAULT NULL COMMENT '0.0-1.0',
  `lost_is_budget` decimal(5,4) DEFAULT NULL,
  `lost_is_rank` decimal(5,4) DEFAULT NULL,
  `weather_temp_high` int(3) DEFAULT NULL,
  `weather_temp_low` int(3) DEFAULT NULL,
  `weather_condition` varchar(50) DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_campaign_date` (`account_id`, `campaign_id`, `date`),
  KEY `idx_cph_account` (`account_id`),
  KEY `idx_cph_campaign` (`campaign_id`),
  KEY `idx_cph_date` (`date`),
  KEY `idx_cph_month_year` (`year`, `month`),
  KEY `idx_cph_impression_share` (`impression_share`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Historical campaign performance for forecasting and trend analysis';

-- 5. Create ads_anomalies table for anomaly detection results
CREATE TABLE IF NOT EXISTS `ads_anomalies` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `account_id` int(11) NOT NULL,
  `entity_type` varchar(32) NOT NULL COMMENT 'campaign, ad_group, keyword',
  `entity_id` varchar(64) NOT NULL,
  `entity_name` varchar(255) DEFAULT NULL,
  `metric_name` varchar(50) NOT NULL COMMENT 'ctr, cpc, cvr, cost, avg_position',
  `anomaly_type` varchar(20) NOT NULL COMMENT 'spike, drop',
  `expected_value` decimal(12,4) DEFAULT NULL,
  `actual_value` decimal(12,4) DEFAULT NULL,
  `deviation_pct` decimal(8,2) DEFAULT NULL,
  `severity` varchar(20) NOT NULL COMMENT 'info, warning, critical',
  `confidence_score` decimal(5,4) DEFAULT NULL,
  `probable_causes` text DEFAULT NULL COMMENT 'JSON array',
  `recommended_actions` text DEFAULT NULL COMMENT 'JSON array',
  `occurred_at` date DEFAULT NULL,
  `acknowledged` tinyint(1) DEFAULT 0,
  `acknowledged_at` datetime DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_ads_anomalies_account` (`account_id`),
  KEY `idx_ads_anomalies_entity` (`entity_type`, `entity_id`),
  KEY `idx_ads_anomalies_metric` (`metric_name`),
  KEY `idx_ads_anomalies_severity` (`severity`),
  KEY `idx_ads_anomalies_date` (`occurred_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Detected performance anomalies from anomaly detection service';

-- 6. Create ads_seasonal_forecasts table
CREATE TABLE IF NOT EXISTS `ads_seasonal_forecasts` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `account_id` int(11) NOT NULL,
  `forecast_for_date` date NOT NULL,
  `forecast_for_month` tinyint(2) DEFAULT NULL,
  `forecast_for_week` tinyint(2) DEFAULT NULL,
  `category` varchar(50) DEFAULT NULL COMMENT 'HVAC, Plumbing, Roofing, etc.',
  `historical_avg` int(11) DEFAULT NULL,
  `predicted_search_volume` int(11) DEFAULT NULL,
  `predicted_cpc` decimal(8,2) DEFAULT NULL,
  `predicted_conversion_rate` decimal(6,4) DEFAULT NULL,
  `predicted_leads` int(11) DEFAULT NULL,
  `confidence_score` decimal(5,2) DEFAULT NULL,
  `influencing_factors` text DEFAULT NULL COMMENT 'JSON array',
  `recommended_budget` decimal(10,2) DEFAULT NULL,
  `recommended_budget_change_pct` decimal(6,2) DEFAULT NULL,
  `recommended_actions` text DEFAULT NULL COMMENT 'JSON array',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_account_date_category` (`account_id`, `forecast_for_date`, `category`),
  KEY `idx_asf_account` (`account_id`),
  KEY `idx_asf_date` (`forecast_for_date`),
  KEY `idx_asf_category` (`category`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Seasonal demand forecasts for budget planning';

-- 7. Add account_id to search_terms table if missing
ALTER TABLE `search_terms`
  ADD COLUMN IF NOT EXISTS `account_id` int(11) DEFAULT NULL AFTER `id`;

CREATE INDEX IF NOT EXISTS `idx_search_terms_account` ON `search_terms` (`account_id`);
CREATE INDEX IF NOT EXISTS `idx_search_terms_account_date` ON `search_terms` (`account_id`, `date`);
