-- =============================================================
-- create_all_tables.sql
-- Auto-generated from SQLAlchemy models.
-- Safe to run on an existing database (CREATE TABLE IF NOT EXISTS).
-- Indexes use IF NOT EXISTS to avoid duplicate-key errors on re-run.
-- =============================================================

SET NAMES utf8mb4;
SET foreign_key_checks = 0;

-- Table: account_zipcodes
CREATE TABLE IF NOT EXISTS account_zipcodes (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	zipcode VARCHAR(16) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS `ix_account_zipcodes_account_id` ON `account_zipcodes` (`account_id`);

-- Table: accounts
CREATE TABLE IF NOT EXISTS accounts (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	name VARCHAR(150) NOT NULL, 
	status VARCHAR(32) NOT NULL DEFAULT 'active', 
	plan VARCHAR(50), 
	created_at DATETIME NOT NULL DEFAULT (now()), 
	updated_at DATETIME NOT NULL DEFAULT (now()), 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS `ix_accounts_plan` ON `accounts` (`plan`);

-- Table: ad_spend
CREATE TABLE IF NOT EXISTS ad_spend (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	source VARCHAR(64) NOT NULL, 
	spend_date DATE NOT NULL, 
	amount NUMERIC(12, 2) NOT NULL, 
	meta JSON, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS `ix_ad_spend_account_id` ON `ad_spend` (`account_id`);
CREATE INDEX IF NOT EXISTS `ix_ad_spend_spend_date` ON `ad_spend` (`spend_date`);

-- Table: ad_templates
CREATE TABLE IF NOT EXISTS ad_templates (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	name VARCHAR(255) NOT NULL, 
	description TEXT, 
	industry VARCHAR(100) NOT NULL, 
	category VARCHAR(100), 
	headline_template VARCHAR(255) NOT NULL, 
	copy_template TEXT NOT NULL, 
	cta_template VARCHAR(100) NOT NULL, 
	image_style VARCHAR(100), 
	image_prompt_template TEXT, 
	platforms VARCHAR(255) NOT NULL, 
	times_used INTEGER, 
	avg_ctr FLOAT, 
	is_active BOOL, 
	is_featured BOOL, 
	created_at DATETIME NOT NULL DEFAULT (now()), 
	updated_at DATETIME NOT NULL DEFAULT (now()), 
	PRIMARY KEY (id)
);

-- Table: ads_account_goals
CREATE TABLE IF NOT EXISTS ads_account_goals (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	target_monthly_leads INTEGER, 
	target_cpa_cents INTEGER, 
	customer_lifetime_value_cents INTEGER, 
	monthly_budget_cents INTEGER, 
	business_type VARCHAR(64), 
	onboarding_completed BOOL NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_ads_account_goal UNIQUE (account_id)
);

CREATE INDEX IF NOT EXISTS `ix_ads_account_goals_account_id` ON `ads_account_goals` (`account_id`);

-- Table: ads_campaigns
CREATE TABLE IF NOT EXISTS ads_campaigns (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	account_id INTEGER, 
	name VARCHAR(200) NOT NULL, 
	objective VARCHAR(50), 
	status VARCHAR(20) NOT NULL, 
	daily_budget_cents INTEGER NOT NULL, 
	period_budget_cents BIGINT, 
	period_budget_start DATE, 
	period_budget_end DATE, 
	network VARCHAR(40), 
	campaign_type VARCHAR(32), 
	language VARCHAR(10), 
	geo_targets TEXT, 
	start_date DATE, 
	end_date DATE, 
	bid_strategy VARCHAR(32), 
	target_cpa_micros BIGINT, 
	target_roas FLOAT, 
	attribution_ratio FLOAT NOT NULL, 
	google_customer_id VARCHAR(32), 
	google_campaign_id VARCHAR(64), 
	budget_group_id INTEGER, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS `ix_ads_campaigns_google_campaign_id` ON `ads_campaigns` (`google_campaign_id`);
CREATE INDEX IF NOT EXISTS `ix_ads_campaigns_google_customer_id` ON `ads_campaigns` (`google_customer_id`);
CREATE INDEX IF NOT EXISTS `ix_ads_campaigns_budget_group_id` ON `ads_campaigns` (`budget_group_id`);
CREATE INDEX IF NOT EXISTS `ix_ads_campaigns_account_id` ON `ads_campaigns` (`account_id`);

-- Table: aggregator_accounts
CREATE TABLE IF NOT EXISTS aggregator_accounts (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	platform VARCHAR(64) NOT NULL, 
	api_key VARCHAR(512), 
	webhook_secret VARCHAR(255), 
	account_external_id VARCHAR(255), 
	is_active BOOL NOT NULL, 
	monthly_budget_cents INTEGER, 
	cost_per_lead_cents INTEGER, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_aggregator_account_platform UNIQUE (account_id, platform)
);

CREATE INDEX IF NOT EXISTS `ix_aggregator_accounts_account_id` ON `aggregator_accounts` (`account_id`);

-- Table: ai_action_rules
CREATE TABLE IF NOT EXISTS ai_action_rules (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	rule_name VARCHAR(255) NOT NULL, 
	action_type VARCHAR(64) NOT NULL, 
	conditions JSON NOT NULL, 
	auto_execute BOOL NOT NULL, 
	min_confidence FLOAT NOT NULL, 
	enabled BOOL NOT NULL, 
	max_actions_per_day INTEGER NOT NULL, 
	max_actions_per_campaign INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS `ix_ai_action_rules_account_id` ON `ai_action_rules` (`account_id`);
CREATE INDEX IF NOT EXISTS `ix_ai_action_rules_enabled` ON `ai_action_rules` (`enabled`);

-- Table: ai_actions
CREATE TABLE IF NOT EXISTS ai_actions (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	action_type ENUM('negative_keyword_added','negative_keyword_removed','bid_adjusted','budget_reallocated','keyword_paused','keyword_enabled','ad_paused','ad_enabled','campaign_paused','campaign_enabled','search_term_blocked','quality_score_fix','custom') NOT NULL, 
	title VARCHAR(255) NOT NULL, 
	description TEXT NOT NULL, 
	campaign_id VARCHAR(64), 
	campaign_name VARCHAR(255), 
	ad_group_id VARCHAR(64), 
	ad_group_name VARCHAR(255), 
	keyword_id VARCHAR(64), 
	ad_id VARCHAR(64), 
	before_value JSON, 
	after_value JSON, 
	estimated_monthly_savings FLOAT, 
	estimated_monthly_value FLOAT, 
	confidence_score FLOAT, 
	reasoning TEXT, 
	data_used JSON, 
	status VARCHAR(20) NOT NULL, 
	executed_at DATETIME, 
	executed_by VARCHAR(64), 
	execution_error TEXT, 
	can_undo BOOL NOT NULL, 
	undone_at DATETIME, 
	undone_by INTEGER, 
	undo_reason VARCHAR(255), 
	approval_token VARCHAR(64), 
	approval_sent_at DATETIME, 
	approved_at DATETIME, 
	rejected_at DATETIME, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE UNIQUE INDEX IF NOT EXISTS `ix_ai_actions_approval_token` ON `ai_actions` (`approval_token`);
CREATE INDEX IF NOT EXISTS `ix_ai_actions_action_type` ON `ai_actions` (`action_type`);
CREATE INDEX IF NOT EXISTS `ix_ai_actions_created_at` ON `ai_actions` (`created_at`);
CREATE INDEX IF NOT EXISTS `ix_ai_actions_status` ON `ai_actions` (`status`);
CREATE INDEX IF NOT EXISTS `ix_ai_actions_account_id` ON `ai_actions` (`account_id`);
CREATE INDEX IF NOT EXISTS `ix_ai_actions_campaign_id` ON `ai_actions` (`campaign_id`);

-- Table: ai_prompts
CREATE TABLE IF NOT EXISTS ai_prompts (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	prompt_key VARCHAR(100) NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	description TEXT, 
	system_message TEXT NOT NULL, 
	prompt_template TEXT NOT NULL, 
	model VARCHAR(50) NOT NULL, 
	temperature FLOAT NOT NULL, 
	max_tokens INTEGER NOT NULL, 
	is_active BOOL NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE UNIQUE INDEX IF NOT EXISTS `ix_ai_prompts_prompt_key` ON `ai_prompts` (`prompt_key`);

-- Table: applied_optimizations
CREATE TABLE IF NOT EXISTS applied_optimizations (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	user_id INTEGER, 
	customer_id VARCHAR(64), 
	campaign_id VARCHAR(128), 
	optimization_type VARCHAR(64) NOT NULL, 
	optimization_title VARCHAR(512), 
	optimization_data JSON, 
	status VARCHAR(32), 
	error_message TEXT, 
	resource_name VARCHAR(512), 
	api_response JSON, 
	applied_at DATETIME, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS `ix_applied_optimizations_account_id` ON `applied_optimizations` (`account_id`);
CREATE INDEX IF NOT EXISTS `ix_applied_optimizations_status` ON `applied_optimizations` (`status`);
CREATE INDEX IF NOT EXISTS `ix_applied_optimizations_optimization_type` ON `applied_optimizations` (`optimization_type`);
CREATE INDEX IF NOT EXISTS `ix_applied_optimizations_customer_id` ON `applied_optimizations` (`customer_id`);

-- Table: automation_runs
CREATE TABLE IF NOT EXISTS automation_runs (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	job_id VARCHAR(36), 
	trigger_type VARCHAR(20), 
	status VARCHAR(20), 
	started_at DATETIME NOT NULL, 
	completed_at DATETIME, 
	duration_minutes INTEGER, 
	campaigns_processed INTEGER, 
	leads_scraped INTEGER, 
	leads_enriched INTEGER, 
	emails_sent INTEGER, 
	error_count INTEGER, 
	error_message TEXT, 
	PRIMARY KEY (id)
);

CREATE UNIQUE INDEX IF NOT EXISTS `ix_automation_runs_job_id` ON `automation_runs` (`job_id`);

-- Table: business_profiles
CREATE TABLE IF NOT EXISTS business_profiles (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	business_name VARCHAR(255) NOT NULL, 
	industry VARCHAR(128), 
	phone VARCHAR(64), 
	website VARCHAR(255), 
	years_in_business VARCHAR(16), 
	service_area VARCHAR(512), 
	employee_count VARCHAR(16), 
	avg_job_ticket INTEGER, 
	services JSON, 
	top_services JSON, 
	price_position ENUM('budget','competitive','premium'), 
	ideal_customers JSON, 
	urgency ENUM('emergency','scheduled','both'), 
	tone ENUM('friendly','professional','direct'), 
	lead_channels JSON, 
	main_challenges JSON, 
	why_choose_us TEXT, 
	current_promo VARCHAR(255), 
	hours VARCHAR(255), 
	primary_goal ENUM('fill_schedule','steady_recurring','brand_awareness','upsell_high_value'), 
	ads_budget ENUM('starter','growth','aggressive'), 
	edge_statement TEXT, 
	competitors TEXT, 
	approvals_via_email BOOL, 
	status ENUM('draft','complete') NOT NULL, 
	completed_at DATETIME, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS `ix_business_profiles_user_id` ON `business_profiles` (`user_id`);
CREATE INDEX IF NOT EXISTS `ix_business_profiles_account_id` ON `business_profiles` (`account_id`);

-- Table: call_tracking_numbers
CREATE TABLE IF NOT EXISTS call_tracking_numbers (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	phone_number VARCHAR(32) NOT NULL, 
	label VARCHAR(255), 
	campaign_id VARCHAR(64), 
	campaign_name VARCHAR(255), 
	is_active BOOL NOT NULL, 
	qualified_duration_secs INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS `ix_call_tracking_numbers_account_id` ON `call_tracking_numbers` (`account_id`);

-- Table: campaign_automation_config
CREATE TABLE IF NOT EXISTS campaign_automation_config (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	enabled BOOL, 
	run_time VARCHAR(5), 
	run_days JSON, 
	daily_email_limit INTEGER, 
	skip_weekends BOOL, 
	next_run_at DATETIME, 
	last_run_at DATETIME, 
	created_at DATETIME DEFAULT (now()), 
	updated_at DATETIME DEFAULT (now()), 
	PRIMARY KEY (id)
);

-- Table: campaign_selections
CREATE TABLE IF NOT EXISTS campaign_selections (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	slug VARCHAR(100) NOT NULL, 
	title VARCHAR(255), 
	notes TEXT, 
	ai_ideas JSON, 
	status VARCHAR(32), 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS `ix_campaign_selections_account_id` ON `campaign_selections` (`account_id`);
CREATE INDEX IF NOT EXISTS `ix_campaign_selections_user_id` ON `campaign_selections` (`user_id`);

-- Table: completed_manual_tasks
CREATE TABLE IF NOT EXISTS completed_manual_tasks (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	user_id INTEGER, 
	customer_id VARCHAR(64), 
	task_id VARCHAR(128) NOT NULL, 
	task_title VARCHAR(512), 
	completed_at DATETIME NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS `ix_completed_manual_tasks_account_id` ON `completed_manual_tasks` (`account_id`);
CREATE INDEX IF NOT EXISTS `ix_completed_manual_tasks_customer_id` ON `completed_manual_tasks` (`customer_id`);

-- Table: contact_groups
CREATE TABLE IF NOT EXISTS contact_groups (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	name VARCHAR(100) NOT NULL, 
	description TEXT, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE UNIQUE INDEX IF NOT EXISTS `ix_contact_groups_name` ON `contact_groups` (`name`);

-- Table: conversion_actions
CREATE TABLE IF NOT EXISTS conversion_actions (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	google_conversion_id VARCHAR(64), 
	name VARCHAR(255) NOT NULL, 
	category VARCHAR(64), 
	type VARCHAR(64), 
	status VARCHAR(32), 
	counting_type VARCHAR(32), 
	value_settings_default FLOAT, 
	value_settings_currency VARCHAR(8), 
	include_in_conversions BOOL, 
	click_through_window_days INTEGER, 
	view_through_window_days INTEGER, 
	conversions_30d FLOAT, 
	conversion_value_30d FLOAT, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_conversion_action UNIQUE (account_id, google_conversion_id)
);

CREATE INDEX IF NOT EXISTS `ix_conversion_actions_google_conversion_id` ON `conversion_actions` (`google_conversion_id`);
CREATE INDEX IF NOT EXISTS `ix_conversion_actions_account_id` ON `conversion_actions` (`account_id`);

-- Table: crm_connections
CREATE TABLE IF NOT EXISTS crm_connections (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	provider VARCHAR(64) NOT NULL, 
	is_active BOOL NOT NULL, 
	tenant_id VARCHAR(128), 
	credentials_json JSON, 
	last_sync_at DATETIME, 
	last_sync_status VARCHAR(32), 
	last_sync_error TEXT, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS `ix_crm_connections_account_id` ON `crm_connections` (`account_id`);

-- Table: customer_impact
CREATE TABLE IF NOT EXISTS customer_impact (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	account_id BIGINT NOT NULL, 
	baseline_start_date DATE, 
	baseline_end_date DATE, 
	baseline_monthly_spend FLOAT, 
	baseline_monthly_leads FLOAT, 
	baseline_cost_per_lead FLOAT, 
	current_monthly_spend FLOAT, 
	current_monthly_leads FLOAT, 
	current_cost_per_lead FLOAT, 
	total_savings FLOAT NOT NULL, 
	total_additional_leads FLOAT NOT NULL, 
	monthly_savings FLOAT, 
	monthly_additional_leads FLOAT, 
	last_calculated_at DATETIME, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE UNIQUE INDEX IF NOT EXISTS `ix_customer_impact_account_id` ON `customer_impact` (`account_id`);

-- Table: email_gclid_map
CREATE TABLE IF NOT EXISTS email_gclid_map (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	email VARCHAR(255) NOT NULL, 
	gclid VARCHAR(255) NOT NULL, 
	utm_source VARCHAR(128), 
	utm_medium VARCHAR(128), 
	utm_campaign VARCHAR(255), 
	keyword VARCHAR(255), 
	landing_page VARCHAR(1024), 
	created_at DATETIME NOT NULL, 
	expires_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_email_gclid UNIQUE (account_id, email)
);

CREATE INDEX IF NOT EXISTS `ix_email_gclid_map_email` ON `email_gclid_map` (`email`);
CREATE INDEX IF NOT EXISTS `ix_email_gclid_map_account_id` ON `email_gclid_map` (`account_id`);
CREATE INDEX IF NOT EXISTS `ix_email_gclid_account_email` ON `email_gclid_map` (`account_id`, `email`);

-- Table: email_queue
CREATE TABLE IF NOT EXISTS email_queue (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	to_email VARCHAR(255) NOT NULL, 
	subject VARCHAR(255) NOT NULL, 
	html_body TEXT NOT NULL, 
	text_body TEXT, 
	use_bulk_credentials BOOL, 
	status VARCHAR(32), 
	attempts INTEGER, 
	max_attempts INTEGER, 
	error_message TEXT, 
	created_at DATETIME NOT NULL, 
	sent_at DATETIME, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS `ix_email_queue_status` ON `email_queue` (`status`);
CREATE INDEX IF NOT EXISTS `idx_email_queue_status_created` ON `email_queue` (`status`, `created_at`);

-- Table: fb_accounts
CREATE TABLE IF NOT EXISTS fb_accounts (
	id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
	account_id INTEGER, 
	fb_user_id VARCHAR(64), 
	email VARCHAR(255), 
	access_token VARCHAR(1024), 
	token_expiry DATETIME, 
	page_id VARCHAR(64), 
	page_name VARCHAR(255), 
	page_access_token VARCHAR(1024), 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS `ix_fb_accounts_email` ON `fb_accounts` (`email`);
CREATE INDEX IF NOT EXISTS `ix_fb_accounts_page_id` ON `fb_accounts` (`page_id`);
CREATE INDEX IF NOT EXISTS `ix_fb_accounts_account_id` ON `fb_accounts` (`account_id`);
CREATE INDEX IF NOT EXISTS `ix_fb_accounts_fb_user_id` ON `fb_accounts` (`fb_user_id`);

-- Table: fb_leads
CREATE TABLE IF NOT EXISTS fb_leads (
	id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
	account_id INTEGER, 
	external_id VARCHAR(128) NOT NULL, 
	page_id VARCHAR(64), 
	form_name VARCHAR(255), 
	name VARCHAR(255), 
	email VARCHAR(255), 
	phone VARCHAR(64), 
	created_time DATETIME, 
	raw JSON, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_fb_lead_ext UNIQUE (account_id, external_id)
);

CREATE INDEX IF NOT EXISTS `ix_fb_leads_external_id` ON `fb_leads` (`external_id`);
CREATE INDEX IF NOT EXISTS `ix_fb_leads_account_id` ON `fb_leads` (`account_id`);
CREATE INDEX IF NOT EXISTS `ix_fb_leads_page_id` ON `fb_leads` (`page_id`);

-- Table: fb_profiles
CREATE TABLE IF NOT EXISTS fb_profiles (
	id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
	account_id INTEGER, 
	page_id VARCHAR(64) NOT NULL, 
	page_name VARCHAR(255), 
	about TEXT, 
	description TEXT, 
	website VARCHAR(512), 
	phone VARCHAR(64), 
	hours JSON, 
	raw JSON, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_fb_profile_page UNIQUE (account_id, page_id)
);

CREATE INDEX IF NOT EXISTS `ix_fb_profiles_account_id` ON `fb_profiles` (`account_id`);
CREATE INDEX IF NOT EXISTS `ix_fb_profiles_page_id` ON `fb_profiles` (`page_id`);

-- Table: ga4_audit_reports
CREATE TABLE IF NOT EXISTS ga4_audit_reports (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	account_id INTEGER, 
	property_id VARCHAR(64) NOT NULL, 
	property_name VARCHAR(255), 
	overall_score FLOAT, 
	overall_grade VARCHAR(5), 
	audit_json TEXT, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS `ix_ga4_audit_reports_account_id` ON `ga4_audit_reports` (`account_id`);

-- Table: ga_stats
CREATE TABLE IF NOT EXISTS ga_stats (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	users_28d INTEGER, 
	sessions_28d INTEGER, 
	fetched_at DATETIME, 
	PRIMARY KEY (id)
);

-- Table: gads_campaign_mix_snapshots
CREATE TABLE IF NOT EXISTS gads_campaign_mix_snapshots (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	week_start DATE NOT NULL, 
	campaign_type VARCHAR(32) NOT NULL, 
	campaign_count INTEGER NOT NULL, 
	spend NUMERIC(12, 4) NOT NULL, 
	spend_pct NUMERIC(5, 2) NOT NULL, 
	conversions NUMERIC(10, 2) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_mix UNIQUE (account_id, week_start, campaign_type)
);

CREATE INDEX IF NOT EXISTS `ix_gads_campaign_mix_snapshots_account_id` ON `gads_campaign_mix_snapshots` (`account_id`);

-- Table: gads_hourly_stats
CREATE TABLE IF NOT EXISTS gads_hourly_stats (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	account_id INTEGER, 
	entity_type VARCHAR(32) NOT NULL, 
	entity_id BIGINT NOT NULL, 
	google_entity_id BIGINT, 
	date DATE NOT NULL, 
	hour INTEGER NOT NULL, 
	impressions BIGINT NOT NULL, 
	clicks BIGINT NOT NULL, 
	cost_micros BIGINT NOT NULL, 
	conversions FLOAT NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_gads_hourly UNIQUE (account_id, entity_type, google_entity_id, date, hour)
);

CREATE INDEX IF NOT EXISTS `ix_gads_hourly_stats_account_id` ON `gads_hourly_stats` (`account_id`);
CREATE INDEX IF NOT EXISTS `ix_gads_hourly_entity_date` ON `gads_hourly_stats` (`entity_type`, `entity_id`, `date`);
CREATE INDEX IF NOT EXISTS `ix_gads_hourly_stats_date` ON `gads_hourly_stats` (`date`);

-- Table: gads_stats_daily
CREATE TABLE IF NOT EXISTS gads_stats_daily (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	account_id INTEGER, 
	entity_type VARCHAR(32) NOT NULL, 
	entity_id BIGINT NOT NULL, 
	google_entity_id BIGINT, 
	date DATE NOT NULL, 
	impressions BIGINT NOT NULL, 
	clicks BIGINT NOT NULL, 
	cost_micros BIGINT NOT NULL, 
	conversions FLOAT NOT NULL, 
	conversion_value FLOAT NOT NULL, 
	avg_cpc FLOAT, 
	search_impr_share FLOAT, 
	lost_is_budget FLOAT, 
	lost_is_rank FLOAT, 
	quality_score INTEGER, 
	landing_page_exp VARCHAR(32), 
	ad_relevance VARCHAR(32), 
	expected_ctr VARCHAR(32), 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_gads_stats_daily UNIQUE (account_id, entity_type, google_entity_id, date)
);

CREATE INDEX IF NOT EXISTS `ix_gads_stats_daily_account_id` ON `gads_stats_daily` (`account_id`);
CREATE INDEX IF NOT EXISTS `ix_stats_entity_date` ON `gads_stats_daily` (`entity_type`, `entity_id`, `date`);
CREATE INDEX IF NOT EXISTS `ix_gads_stats_daily_google_entity_id` ON `gads_stats_daily` (`google_entity_id`);
CREATE INDEX IF NOT EXISTS `ix_stats_account_date` ON `gads_stats_daily` (`account_id`, `date`);
CREATE INDEX IF NOT EXISTS `ix_gads_stats_daily_date` ON `gads_stats_daily` (`date`);
CREATE INDEX IF NOT EXISTS `ix_gads_stats_daily_entity_type` ON `gads_stats_daily` (`entity_type`);
CREATE INDEX IF NOT EXISTS `ix_gads_stats_daily_entity_id` ON `gads_stats_daily` (`entity_id`);

-- Table: geo_points
CREATE TABLE IF NOT EXISTS geo_points (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	source VARCHAR(64), 
	name VARCHAR(255), 
	email VARCHAR(255), 
	phone VARCHAR(64), 
	address VARCHAR(255), 
	city VARCHAR(128), 
	state VARCHAR(32), 
	zip VARCHAR(16), 
	lat FLOAT, 
	lng FLOAT, 
	occurred_at DATETIME, 
	raw JSON, 
	created_at DATETIME NOT NULL DEFAULT (now()), 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS `ix_geo_points_source` ON `geo_points` (`source`);
CREATE INDEX IF NOT EXISTS `ix_geo_points_zip` ON `geo_points` (`zip`);
CREATE INDEX IF NOT EXISTS `ix_geo_points_lng` ON `geo_points` (`lng`);
CREATE INDEX IF NOT EXISTS `ix_geo_points_account_id` ON `geo_points` (`account_id`);
CREATE INDEX IF NOT EXISTS `ix_geo_points_lat` ON `geo_points` (`lat`);

-- Table: glsa_accounts
CREATE TABLE IF NOT EXISTS glsa_accounts (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	account_id INTEGER, 
	google_user_id VARCHAR(128), 
	email VARCHAR(255), 
	access_token TEXT, 
	refresh_token TEXT, 
	token_expiry DATETIME, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS `ix_glsa_accounts_google_user_id` ON `glsa_accounts` (`google_user_id`);
CREATE INDEX IF NOT EXISTS `ix_glsa_accounts_email` ON `glsa_accounts` (`email`);
CREATE INDEX IF NOT EXISTS `ix_glsa_accounts_account_id` ON `glsa_accounts` (`account_id`);

-- Table: google_ads_ai_analysis_tracker
CREATE TABLE IF NOT EXISTS google_ads_ai_analysis_tracker (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	google_ads_customer_id VARCHAR(20) NOT NULL, 
	last_analysis_at DATETIME, 
	analysis_count_current_month INTEGER NOT NULL DEFAULT '0', 
	analysis_count_total INTEGER NOT NULL DEFAULT '0', 
	current_month_year VARCHAR(7), 
	created_at DATETIME NOT NULL DEFAULT (now()), 
	updated_at DATETIME NOT NULL DEFAULT (now()), 
	PRIMARY KEY (id)
);

CREATE UNIQUE INDEX IF NOT EXISTS `ix_google_ads_ai_analysis_tracker_google_ads_customer_id` ON `google_ads_ai_analysis_tracker` (`google_ads_customer_id`);

-- Table: google_ads_auth
CREATE TABLE IF NOT EXISTS google_ads_auth (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	manager_customer_id VARCHAR(32), 
	customer_id VARCHAR(32) NOT NULL, 
	refresh_token TEXT NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS `ix_google_ads_auth_account_id` ON `google_ads_auth` (`account_id`);
CREATE INDEX IF NOT EXISTS `ix_google_ads_auth_user_id` ON `google_ads_auth` (`user_id`);

-- Table: google_oauth_tokens
CREATE TABLE IF NOT EXISTS google_oauth_tokens (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	account_id INTEGER, 
	product VARCHAR(10) NOT NULL, 
	credentials_json LONGTEXT NOT NULL, 
	ga_property_id VARCHAR(64), 
	ga_property_name VARCHAR(255), 
	gsc_site VARCHAR(255), 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS `ix_google_oauth_tokens_account_id` ON `google_oauth_tokens` (`account_id`);

-- Table: google_tokens
CREATE TABLE IF NOT EXISTS google_tokens (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	user_id INTEGER, 
	access_token TEXT, 
	refresh_token TEXT, 
	expiry DATETIME, 
	scopes TEXT, 
	created_at DATETIME, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS `ix_google_tokens_user_id` ON `google_tokens` (`user_id`);

-- Table: gsc_stats
CREATE TABLE IF NOT EXISTS gsc_stats (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	clicks_28d INTEGER, 
	impr_28d INTEGER, 
	fetched_at DATETIME, 
	PRIMARY KEY (id)
);

-- Table: labels
CREATE TABLE IF NOT EXISTS labels (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	name VARCHAR(128) NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (name)
);

-- Table: lead_campaigns
CREATE TABLE IF NOT EXISTS lead_campaigns (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	name VARCHAR(200) NOT NULL, 
	industry_service VARCHAR(200) NOT NULL, 
	location VARCHAR(200) NOT NULL, 
	scrape_ads BOOL, 
	scrape_maps BOOL, 
	scrape_lsa BOOL, 
	scrape_organic BOOL, 
	max_organic_results INTEGER, 
	daily_email_limit INTEGER, 
	sequence_delay_days INTEGER, 
	status ENUM('draft','scraping','ready','sending','paused','completed') NOT NULL, 
	leads_scraped INTEGER, 
	leads_enriched INTEGER, 
	emails_sent INTEGER, 
	emails_opened INTEGER, 
	emails_replied INTEGER, 
	created_at DATETIME NOT NULL DEFAULT (now()), 
	updated_at DATETIME NOT NULL DEFAULT (now()), 
	scraping_started_at DATETIME, 
	scraping_completed_at DATETIME, 
	sending_started_at DATETIME, 
	is_core BOOL, 
	last_automation_run DATETIME, 
	PRIMARY KEY (id)
);

-- Table: lead_ingest
CREATE TABLE IF NOT EXISTS lead_ingest (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	source VARCHAR(64) NOT NULL, 
	external_id VARCHAR(128), 
	name VARCHAR(255), 
	phone VARCHAR(64), 
	email VARCHAR(255), 
	city VARCHAR(255), 
	service_type VARCHAR(128), 
	lead_cost NUMERIC(10, 2), 
	status VARCHAR(32) NOT NULL, 
	job_notes TEXT, 
	contacted_at DATETIME, 
	booked_at DATETIME, 
	completed_at DATETIME, 
	occurred_at DATETIME, 
	raw JSON, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS `ix_lead_ingest_external_id` ON `lead_ingest` (`external_id`);
CREATE INDEX IF NOT EXISTS `ix_lead_ingest_phone` ON `lead_ingest` (`phone`);
CREATE INDEX IF NOT EXISTS `ix_lead_ingest_email` ON `lead_ingest` (`email`);
CREATE INDEX IF NOT EXISTS `ix_lead_ingest_account_id` ON `lead_ingest` (`account_id`);
CREATE INDEX IF NOT EXISTS `ix_lead_ingest_occurred_at` ON `lead_ingest` (`occurred_at`);

-- Table: lead_intake_configs
CREATE TABLE IF NOT EXISTS lead_intake_configs (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	networx_webhook_secret VARCHAR(128), 
	networx_default_lead_cost NUMERIC(10, 2), 
	elocal_tracking_number VARCHAR(32), 
	elocal_default_lead_cost NUMERIC(10, 2), 
	missed_call_sms_body TEXT, 
	review_request_sms_template TEXT, 
	review_request_email_subject VARCHAR(255), 
	review_link_google VARCHAR(512), 
	review_link_yelp VARCHAR(512), 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE UNIQUE INDEX IF NOT EXISTS `ix_lead_intake_configs_account_id` ON `lead_intake_configs` (`account_id`);

-- Table: location_groups
CREATE TABLE IF NOT EXISTS location_groups (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	name VARCHAR(120) NOT NULL, 
	primary_account_id INTEGER NOT NULL, 
	join_token VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (join_token)
);

-- Table: marketing_budgets
CREATE TABLE IF NOT EXISTS marketing_budgets (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	period_year INTEGER NOT NULL, 
	period_month INTEGER NOT NULL, 
	total_budget_cents INTEGER NOT NULL, 
	notes TEXT, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_marketing_budget_period UNIQUE (account_id, period_year, period_month)
);

CREATE INDEX IF NOT EXISTS `ix_marketing_budgets_account_id` ON `marketing_budgets` (`account_id`);

-- Table: marketing_channels
CREATE TABLE IF NOT EXISTS marketing_channels (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	channel_type VARCHAR(64) NOT NULL, 
	is_active BOOL NOT NULL, 
	monthly_budget_cents INTEGER, 
	notes TEXT, 
	tracking_phone VARCHAR(32), 
	promo_code VARCHAR(64), 
	vendor_name VARCHAR(255), 
	start_date DATE, 
	end_date DATE, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_marketing_channel_account_name UNIQUE (account_id, name)
);

CREATE INDEX IF NOT EXISTS `ix_marketing_channels_account_id` ON `marketing_channels` (`account_id`);

-- Table: marketing_strategies
CREATE TABLE IF NOT EXISTS marketing_strategies (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	account_id INTEGER, 
	name VARCHAR(255) NOT NULL, 
	business_name VARCHAR(255), 
	website VARCHAR(255), 
	industry VARCHAR(255), 
	locations JSON, 
	pov_ids JSON, 
	target_audience JSON, 
	personas JSON, 
	goals JSON, 
	positioning TEXT, 
	messaging JSON, 
	brand_voice TEXT, 
	competitors JSON, 
	primary_keywords JSON, 
	extra_keywords JSON, 
	channels JSON, 
	content_plan JSON, 
	offers JSON, 
	constraints JSON, 
	tools JSON, 
	budget_cents INTEGER, 
	timeline JSON, 
	kpis JSON, 
	strategy_html TEXT, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS `ix_marketing_strategies_account_id` ON `marketing_strategies` (`account_id`);

-- Table: nps_surveys
CREATE TABLE IF NOT EXISTS nps_surveys (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	token VARCHAR(64) NOT NULL, 
	customer_name VARCHAR(255), 
	customer_email VARCHAR(255), 
	customer_phone VARCHAR(32), 
	job_type VARCHAR(128), 
	score INTEGER, 
	review_link_google VARCHAR(512), 
	status VARCHAR(32) NOT NULL, 
	created_at DATETIME NOT NULL, 
	sent_at DATETIME, 
	responded_at DATETIME, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS `ix_nps_surveys_account_id` ON `nps_surveys` (`account_id`);
CREATE UNIQUE INDEX IF NOT EXISTS `ix_nps_surveys_token` ON `nps_surveys` (`token`);

-- Table: offline_conversion_imports
CREATE TABLE IF NOT EXISTS offline_conversion_imports (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	source VARCHAR(32) NOT NULL, 
	external_id VARCHAR(255), 
	gclid VARCHAR(255), 
	conversion_name VARCHAR(255) NOT NULL, 
	conversion_time DATETIME, 
	conversion_value FLOAT, 
	currency_code VARCHAR(8) NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	google_response_json TEXT, 
	error_message TEXT, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS `ix_offline_conversion_imports_gclid` ON `offline_conversion_imports` (`gclid`);
CREATE INDEX IF NOT EXISTS `ix_offline_conversion_imports_account_id` ON `offline_conversion_imports` (`account_id`);
CREATE INDEX IF NOT EXISTS `ix_offline_conv_account_status` ON `offline_conversion_imports` (`account_id`, `status`);

-- Table: optimizer_recommendations
CREATE TABLE IF NOT EXISTS optimizer_recommendations (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	account_id BIGINT, 
	scope_type VARCHAR(32) NOT NULL, 
	scope_id BIGINT NOT NULL, 
	category VARCHAR(64) NOT NULL, 
	title VARCHAR(255) NOT NULL, 
	details TEXT NOT NULL, 
	expected_impact VARCHAR(255), 
	severity INTEGER NOT NULL, 
	suggested_action_json TEXT NOT NULL, 
	created_at DATETIME NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS `ix_optimizer_recommendations_account_id` ON `optimizer_recommendations` (`account_id`);
CREATE INDEX IF NOT EXISTS `ix_opt_scope` ON `optimizer_recommendations` (`scope_type`, `scope_id`);
CREATE INDEX IF NOT EXISTS `ix_optimizer_recommendations_scope_id` ON `optimizer_recommendations` (`scope_id`);

-- Table: payments
CREATE TABLE IF NOT EXISTS payments (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	user_id VARCHAR(64) NOT NULL, 
	stripe_customer_id VARCHAR(64) NOT NULL, 
	invoice_id VARCHAR(64), 
	payment_intent_id VARCHAR(64), 
	amount INTEGER, 
	currency VARCHAR(8), 
	status VARCHAR(32), 
	created_at DATETIME, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS `ix_payments_stripe_customer_id` ON `payments` (`stripe_customer_id`);
CREATE INDEX IF NOT EXISTS `idx_payments_user_status` ON `payments` (`user_id`, `status`);
CREATE INDEX IF NOT EXISTS `ix_payments_invoice_id` ON `payments` (`invoice_id`);
CREATE INDEX IF NOT EXISTS `ix_payments_user_id` ON `payments` (`user_id`);
CREATE INDEX IF NOT EXISTS `ix_payments_payment_intent_id` ON `payments` (`payment_intent_id`);

-- Table: performance_metrics
CREATE TABLE IF NOT EXISTS performance_metrics (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	account_id BIGINT NOT NULL, 
	source_type VARCHAR(32) NOT NULL, 
	source_id VARCHAR(255), 
	date DATE NOT NULL, 
	timeframe VARCHAR(16) NOT NULL, 
	entity_type VARCHAR(32), 
	entity_id VARCHAR(255), 
	entity_name VARCHAR(255), 
	metrics_json TEXT NOT NULL, 
	impressions BIGINT, 
	clicks BIGINT, 
	spend FLOAT, 
	conversions FLOAT, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_perf_metrics UNIQUE (account_id, source_type, source_id, entity_type, entity_id, date, timeframe)
);

CREATE INDEX IF NOT EXISTS `ix_performance_metrics_entity_type` ON `performance_metrics` (`entity_type`);
CREATE INDEX IF NOT EXISTS `ix_performance_metrics_source_type` ON `performance_metrics` (`source_type`);
CREATE INDEX IF NOT EXISTS `ix_perf_account_source_date` ON `performance_metrics` (`account_id`, `source_type`, `date`);
CREATE INDEX IF NOT EXISTS `ix_performance_metrics_entity_id` ON `performance_metrics` (`entity_id`);
CREATE INDEX IF NOT EXISTS `ix_perf_source_entity_date` ON `performance_metrics` (`source_type`, `entity_type`, `date`);
CREATE INDEX IF NOT EXISTS `ix_performance_metrics_source_id` ON `performance_metrics` (`source_id`);
CREATE INDEX IF NOT EXISTS `ix_performance_metrics_account_id` ON `performance_metrics` (`account_id`);
CREATE INDEX IF NOT EXISTS `ix_performance_metrics_date` ON `performance_metrics` (`date`);

-- Table: performance_snapshots
CREATE TABLE IF NOT EXISTS performance_snapshots (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	customer_id VARCHAR(32) NOT NULL, 
	as_of_date DATETIME NOT NULL, 
	metrics JSON NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS `ix_performance_snapshots_account_id` ON `performance_snapshots` (`account_id`);
CREATE INDEX IF NOT EXISTS `ix_performance_snapshots_user_id` ON `performance_snapshots` (`user_id`);

-- Table: phone_gclid_map
CREATE TABLE IF NOT EXISTS phone_gclid_map (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	phone_e164 VARCHAR(20) NOT NULL, 
	gclid VARCHAR(255) NOT NULL, 
	utm_source VARCHAR(128), 
	utm_medium VARCHAR(128), 
	utm_campaign VARCHAR(255), 
	keyword VARCHAR(255), 
	created_at DATETIME NOT NULL, 
	expires_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_phone_gclid UNIQUE (account_id, phone_e164)
);

CREATE INDEX IF NOT EXISTS `ix_phone_gclid_map_account_id` ON `phone_gclid_map` (`account_id`);
CREATE INDEX IF NOT EXISTS `ix_phone_gclid_account_phone` ON `phone_gclid_map` (`account_id`, `phone_e164`);
CREATE INDEX IF NOT EXISTS `ix_phone_gclid_map_phone_e164` ON `phone_gclid_map` (`phone_e164`);

-- Table: plans
CREATE TABLE IF NOT EXISTS plans (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	code VARCHAR(50) NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	price_month_cents INTEGER, 
	price_year_cents INTEGER, 
	stripe_price_monthly_id VARCHAR(120), 
	stripe_price_yearly_id VARCHAR(120), 
	active BOOL NOT NULL DEFAULT '1', 
	created_at DATETIME NOT NULL DEFAULT (now()), 
	updated_at DATETIME NOT NULL DEFAULT (now()), 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS `ix_plans_stripe_price_monthly_id` ON `plans` (`stripe_price_monthly_id`);
CREATE INDEX IF NOT EXISTS `ix_plans_stripe_price_yearly_id` ON `plans` (`stripe_price_yearly_id`);
CREATE UNIQUE INDEX IF NOT EXISTS `ix_plans_code` ON `plans` (`code`);

-- Table: pov_autosaves
CREATE TABLE IF NOT EXISTS pov_autosaves (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	user_id INTEGER, 
	site_id INTEGER, 
	scope ENUM('global','site','service') NOT NULL, 
	service_key VARCHAR(191), 
	draft_key VARCHAR(191) NOT NULL, 
	data_json TEXT NOT NULL, 
	is_submitted BOOL NOT NULL, 
	created_at DATETIME, 
	updated_at DATETIME, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_autosave UNIQUE (account_id, draft_key)
);

-- Table: reactivation_sends
CREATE TABLE IF NOT EXISTS reactivation_sends (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	customer_email VARCHAR(255), 
	customer_phone VARCHAR(32), 
	customer_name VARCHAR(255), 
	sent_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS `ix_reactivation_sends_account_id` ON `reactivation_sends` (`account_id`);
CREATE INDEX IF NOT EXISTS `ix_reactivation_sends_customer_email` ON `reactivation_sends` (`customer_email`);
CREATE INDEX IF NOT EXISTS `idx_react_acct_email` ON `reactivation_sends` (`account_id`, `customer_email`);

-- Table: referral_requests
CREATE TABLE IF NOT EXISTS referral_requests (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	channel VARCHAR(16) NOT NULL, 
	recipient VARCHAR(255) NOT NULL, 
	customer_name VARCHAR(255), 
	job_type VARCHAR(128), 
	status VARCHAR(32) NOT NULL, 
	created_at DATETIME NOT NULL, 
	sent_at DATETIME, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS `ix_referral_requests_account_id` ON `referral_requests` (`account_id`);

-- Table: review_requests
CREATE TABLE IF NOT EXISTS review_requests (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	channel VARCHAR(16) NOT NULL, 
	recipient VARCHAR(255) NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	customer_name VARCHAR(255), 
	job_type VARCHAR(128), 
	review_link_google VARCHAR(512), 
	review_link_yelp VARCHAR(512), 
	payload JSON, 
	created_at DATETIME NOT NULL, 
	sent_at DATETIME, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS `ix_review_requests_account_id` ON `review_requests` (`account_id`);

-- Table: seo_alerts
CREATE TABLE IF NOT EXISTS seo_alerts (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	site_id INTEGER, 
	account_id INTEGER, 
	site_url VARCHAR(512), 
	alert_type VARCHAR(64) NOT NULL, 
	severity VARCHAR(16) NOT NULL, 
	message TEXT NOT NULL, 
	detail JSON, 
	is_read BOOL NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

-- Table: seo_health_snapshots
CREATE TABLE IF NOT EXISTS seo_health_snapshots (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	site_id INTEGER, 
	account_id INTEGER, 
	site_url VARCHAR(512) NOT NULL, 
	health_score INTEGER, 
	sitemap_ok BOOL, 
	robots_ok BOOL, 
	homepage_status INTEGER, 
	broken_links_count INTEGER, 
	gsc_clicks INTEGER, 
	gsc_impressions INTEGER, 
	gsc_avg_position FLOAT, 
	data JSON, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

-- Table: seo_keyword_positions
CREATE TABLE IF NOT EXISTS seo_keyword_positions (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	site_url VARCHAR(512) NOT NULL, 
	keyword VARCHAR(512) NOT NULL, 
	page VARCHAR(2048), 
	position NUMERIC(7, 2), 
	impressions INTEGER, 
	clicks INTEGER, 
	ctr NUMERIC(6, 4), 
	date_start DATE, 
	date_end DATE NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_seo_kw_pos UNIQUE (account_id, site_url, keyword, page, date_end)
);

CREATE INDEX IF NOT EXISTS `ix_skp_account_date` ON `seo_keyword_positions` (`account_id`, `date_end`);
CREATE INDEX IF NOT EXISTS `ix_skp_account_kw` ON `seo_keyword_positions` (`account_id`, `keyword`);

-- Table: seo_scan_results
CREATE TABLE IF NOT EXISTS seo_scan_results (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	site_id INTEGER, 
	scan_type VARCHAR(64) NOT NULL, 
	url VARCHAR(2048), 
	score INTEGER, 
	pass_count INTEGER, 
	warn_count INTEGER, 
	fail_count INTEGER, 
	issue_count INTEGER, 
	item_count INTEGER, 
	data JSON, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS `ix_ssr_url_type` ON `seo_scan_results` (`url`, `scan_type`);
CREATE INDEX IF NOT EXISTS `ix_ssr_site_type` ON `seo_scan_results` (`site_id`, `scan_type`);
CREATE INDEX IF NOT EXISTS `ix_ssr_account_type_created` ON `seo_scan_results` (`account_id`, `scan_type`, `created_at`);

-- Table: service_pricing
CREATE TABLE IF NOT EXISTS service_pricing (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	tier_name VARCHAR(64) NOT NULL, 
	min_monthly_spend INTEGER NOT NULL, 
	max_monthly_spend INTEGER, 
	base_price INTEGER NOT NULL, 
	percentage_of_savings FLOAT, 
	description TEXT, 
	is_active BOOL, 
	created_at DATETIME, 
	updated_at DATETIME, 
	PRIMARY KEY (id)
);

-- Table: shared_negative_lists
CREATE TABLE IF NOT EXISTS shared_negative_lists (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	name VARCHAR(255) NOT NULL, 
	description TEXT, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (name)
);

-- Table: skimmer_auth
CREATE TABLE IF NOT EXISTS skimmer_auth (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	api_key_encrypted TEXT, 
	webhook_secret VARCHAR(128), 
	last_synced_at DATETIME, 
	sync_enabled BOOL NOT NULL, 
	review_requests_enabled BOOL NOT NULL, 
	review_request_delay_hours INTEGER NOT NULL, 
	review_request_template TEXT, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE UNIQUE INDEX IF NOT EXISTS `ix_skimmer_auth_account_id` ON `skimmer_auth` (`account_id`);

-- Table: skimmer_jobs
CREATE TABLE IF NOT EXISTS skimmer_jobs (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	skimmer_job_id VARCHAR(128) NOT NULL, 
	skimmer_customer_id VARCHAR(128), 
	customer_name VARCHAR(255), 
	customer_email VARCHAR(255), 
	customer_phone VARCHAR(30), 
	customer_phone_e164 VARCHAR(20), 
	service_address VARCHAR(512), 
	service_type VARCHAR(128), 
	status VARCHAR(32) NOT NULL, 
	completed_at DATETIME, 
	invoice_total_cents INTEGER, 
	matched_gclid VARCHAR(255), 
	offline_conv_pushed_at DATETIME, 
	offline_conv_status VARCHAR(16), 
	review_sent_at DATETIME, 
	raw_json TEXT, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_skimmer_job UNIQUE (account_id, skimmer_job_id)
);

CREATE INDEX IF NOT EXISTS `ix_skimmer_jobs_customer_phone_e164` ON `skimmer_jobs` (`customer_phone_e164`);
CREATE INDEX IF NOT EXISTS `ix_skimmer_jobs_account_id` ON `skimmer_jobs` (`account_id`);
CREATE INDEX IF NOT EXISTS `ix_skimmer_jobs_skimmer_job_id` ON `skimmer_jobs` (`skimmer_job_id`);

-- Table: snapshots
CREATE TABLE IF NOT EXISTS snapshots (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	name VARCHAR(255) NOT NULL, 
	entity_type VARCHAR(32) NOT NULL, 
	entity_id BIGINT NOT NULL, 
	payload_json TEXT NOT NULL, 
	created_by BIGINT, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

-- Table: stripe_customers
CREATE TABLE IF NOT EXISTS stripe_customers (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	user_id VARCHAR(64) NOT NULL, 
	stripe_customer_id VARCHAR(64) NOT NULL, 
	first_payment_at DATETIME, 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	UNIQUE (stripe_customer_id)
);

CREATE INDEX IF NOT EXISTS `ix_stripe_customers_user_id` ON `stripe_customers` (`user_id`);

-- Table: stripe_webhook_events
CREATE TABLE IF NOT EXISTS stripe_webhook_events (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	event_id VARCHAR(64) NOT NULL, 
	event_type VARCHAR(64) NOT NULL, 
	processed_at DATETIME NOT NULL, 
	status VARCHAR(32), 
	error_message TEXT, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS `ix_stripe_webhook_events_event_type` ON `stripe_webhook_events` (`event_type`);
CREATE UNIQUE INDEX IF NOT EXISTS `ix_stripe_webhook_events_event_id` ON `stripe_webhook_events` (`event_id`);

-- Table: subscriptions
CREATE TABLE IF NOT EXISTS subscriptions (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	user_id VARCHAR(64) NOT NULL, 
	stripe_customer_id VARCHAR(64) NOT NULL, 
	stripe_subscription_id VARCHAR(64) NOT NULL, 
	price_id VARCHAR(64), 
	status VARCHAR(32), 
	current_period_end DATETIME, 
	cancel_at_period_end BOOL, 
	created_at DATETIME, 
	updated_at DATETIME, 
	PRIMARY KEY (id), 
	UNIQUE (stripe_subscription_id)
);

CREATE INDEX IF NOT EXISTS `idx_subscriptions_user_status` ON `subscriptions` (`user_id`, `status`);
CREATE INDEX IF NOT EXISTS `ix_subscriptions_user_id` ON `subscriptions` (`user_id`);
CREATE INDEX IF NOT EXISTS `ix_subscriptions_status` ON `subscriptions` (`status`);
CREATE INDEX IF NOT EXISTS `ix_subscriptions_stripe_customer_id` ON `subscriptions` (`stripe_customer_id`);

-- Table: tutorial_popups
CREATE TABLE IF NOT EXISTS tutorial_popups (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	title VARCHAR(200), 
	content TEXT, 
	page_path VARCHAR(500) NOT NULL, 
	page_element VARCHAR(500), 
	position_x INTEGER, 
	position_y INTEGER, 
	icon VARCHAR(100), 
	theme VARCHAR(50), 
	width_px INTEGER, 
	sequence_order INTEGER, 
	show_once BOOL, 
	is_active BOOL, 
	created_at DATETIME NOT NULL DEFAULT (now()), 
	updated_at DATETIME NOT NULL DEFAULT (now()), 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS `ix_tutorial_popups_sequence_order` ON `tutorial_popups` (`sequence_order`);
CREATE INDEX IF NOT EXISTS `ix_tutorial_popups_page_path` ON `tutorial_popups` (`page_path`);
CREATE INDEX IF NOT EXISTS `ix_tutorial_popups_is_active` ON `tutorial_popups` (`is_active`);

-- Table: wp_sites
CREATE TABLE IF NOT EXISTS wp_sites (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	account_id INTEGER, 
	base_url VARCHAR(255) NOT NULL, 
	username VARCHAR(190) NOT NULL, 
	app_password VARCHAR(255) NOT NULL, 
	default_category VARCHAR(191), 
	default_tag VARCHAR(191), 
	autopilot_enabled BOOL NOT NULL, 
	autopilot_daily_new INTEGER NOT NULL, 
	autopilot_daily_refresh INTEGER NOT NULL, 
	autopilot_require_approval BOOL NOT NULL, 
	brand_voice TEXT, 
	brand_avoid TEXT, 
	content_language VARCHAR(10), 
	created_at DATETIME, 
	updated_at DATETIME, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS `ix_wp_sites_account_id` ON `wp_sites` (`account_id`);

-- Table: yelp_accounts
CREATE TABLE IF NOT EXISTS yelp_accounts (
	id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
	account_id BIGINT UNSIGNED, 
	yelp_user_id VARCHAR(191), 
	email VARCHAR(191), 
	access_token TEXT, 
	refresh_token TEXT, 
	token_expiry DATETIME, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS `ix_yelp_accounts_account_id` ON `yelp_accounts` (`account_id`);
CREATE INDEX IF NOT EXISTS `ix_yelp_accounts_yelp_user_id` ON `yelp_accounts` (`yelp_user_id`);

-- Table: yelp_leads
CREATE TABLE IF NOT EXISTS yelp_leads (
	id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
	account_id BIGINT UNSIGNED, 
	external_id VARCHAR(191) NOT NULL, 
	name VARCHAR(191), 
	phone VARCHAR(64), 
	message TEXT, 
	city VARCHAR(191), 
	lead_ts DATETIME, 
	raw JSON, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS `ix_yelp_leads_external_id` ON `yelp_leads` (`external_id`);
CREATE INDEX IF NOT EXISTS `ix_yelp_leads_account_id` ON `yelp_leads` (`account_id`);

-- Table: yelp_profiles
CREATE TABLE IF NOT EXISTS yelp_profiles (
	id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
	account_id BIGINT UNSIGNED, 
	profile_id VARCHAR(191) NOT NULL, 
	business_name VARCHAR(191), 
	description TEXT, 
	categories JSON, 
	service_areas JSON, 
	phone VARCHAR(64), 
	website VARCHAR(255), 
	hours JSON, 
	raw JSON, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS `ix_yelp_profiles_profile_id` ON `yelp_profiles` (`profile_id`);
CREATE INDEX IF NOT EXISTS `ix_yelp_profiles_account_id` ON `yelp_profiles` (`account_id`);

-- Table: ad_groups
CREATE TABLE IF NOT EXISTS ad_groups (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	campaign_id INTEGER NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	max_cpc_cents INTEGER, 
	google_ad_group_id VARCHAR(64), 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(campaign_id) REFERENCES ads_campaigns (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS `ix_ad_groups_google_ad_group_id` ON `ad_groups` (`google_ad_group_id`);
CREATE INDEX IF NOT EXISTS `ix_ad_groups_campaign_id` ON `ad_groups` (`campaign_id`);

-- Table: aggregator_leads
CREATE TABLE IF NOT EXISTS aggregator_leads (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	aggregator_account_id INTEGER NOT NULL, 
	platform VARCHAR(64) NOT NULL, 
	external_lead_id VARCHAR(255), 
	name VARCHAR(255), 
	phone VARCHAR(64), 
	email VARCHAR(255), 
	service_requested VARCHAR(512), 
	city VARCHAR(255), 
	zip_code VARCHAR(20), 
	lead_cost_cents INTEGER, 
	status VARCHAR(32) NOT NULL, 
	dispute_reason TEXT, 
	booked_revenue_cents INTEGER, 
	occurred_at DATETIME, 
	raw_data JSON, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_aggregator_lead_external UNIQUE (account_id, platform, external_lead_id), 
	FOREIGN KEY(aggregator_account_id) REFERENCES aggregator_accounts (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS `ix_aggregator_leads_aggregator_account_id` ON `aggregator_leads` (`aggregator_account_id`);
CREATE INDEX IF NOT EXISTS `ix_aggregator_leads_platform` ON `aggregator_leads` (`platform`);
CREATE INDEX IF NOT EXISTS `ix_aggregator_leads_account_id` ON `aggregator_leads` (`account_id`);
CREATE INDEX IF NOT EXISTS `ix_aggregator_leads_external_lead_id` ON `aggregator_leads` (`external_lead_id`);

-- Table: auction_insights
CREATE TABLE IF NOT EXISTS auction_insights (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	campaign_id INTEGER, 
	date DATE NOT NULL, 
	domain VARCHAR(255) NOT NULL, 
	impression_share FLOAT, 
	overlap_rate FLOAT, 
	position_above_rate FLOAT, 
	top_of_page_rate FLOAT, 
	abs_top_of_page_rate FLOAT, 
	outranking_share FLOAT, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_auction_insight UNIQUE (account_id, campaign_id, date, domain), 
	FOREIGN KEY(campaign_id) REFERENCES ads_campaigns (id)
);

CREATE INDEX IF NOT EXISTS `ix_auction_insights_account_id` ON `auction_insights` (`account_id`);
CREATE INDEX IF NOT EXISTS `ix_auction_insights_campaign_id` ON `auction_insights` (`campaign_id`);
CREATE INDEX IF NOT EXISTS `ix_auction_insights_date` ON `auction_insights` (`date`);

-- Table: call_events
CREATE TABLE IF NOT EXISTS call_events (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	call_sid VARCHAR(64) NOT NULL, 
	parent_call_sid VARCHAR(64), 
	from_number VARCHAR(32), 
	to_number VARCHAR(32), 
	tracking_number_id INTEGER, 
	campaign_id VARCHAR(64), 
	campaign_name VARCHAR(255), 
	call_status VARCHAR(32), 
	call_duration INTEGER, 
	is_qualified_lead BOOL NOT NULL, 
	caller_city VARCHAR(64), 
	caller_state VARCHAR(32), 
	caller_zip VARCHAR(16), 
	call_started_at DATETIME, 
	call_ended_at DATETIME, 
	created_at DATETIME NOT NULL, 
	raw_payload JSON, 
	PRIMARY KEY (id), 
	UNIQUE (call_sid), 
	FOREIGN KEY(tracking_number_id) REFERENCES call_tracking_numbers (id)
);

CREATE INDEX IF NOT EXISTS `ix_call_events_call_started_at` ON `call_events` (`call_started_at`);
CREATE INDEX IF NOT EXISTS `ix_call_events_account_id` ON `call_events` (`account_id`);
CREATE INDEX IF NOT EXISTS `ix_call_events_campaign_id` ON `call_events` (`campaign_id`);
CREATE INDEX IF NOT EXISTS `ix_call_events_tracking_number_id` ON `call_events` (`tracking_number_id`);
CREATE INDEX IF NOT EXISTS `ix_call_events_created_at` ON `call_events` (`created_at`);

-- Table: campaign_drafts
CREATE TABLE IF NOT EXISTS campaign_drafts (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	profile_id INTEGER NOT NULL, 
	draft_json JSON NOT NULL, 
	status ENUM('draft','approved','uploaded') NOT NULL DEFAULT 'draft', 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(profile_id) REFERENCES business_profiles (id)
);

CREATE INDEX IF NOT EXISTS `ix_campaign_drafts_account_id` ON `campaign_drafts` (`account_id`);
CREATE INDEX IF NOT EXISTS `ix_campaign_drafts_user_id` ON `campaign_drafts` (`user_id`);
CREATE INDEX IF NOT EXISTS `ix_campaign_drafts_profile_id` ON `campaign_drafts` (`profile_id`);

-- Table: channel_lead_entries
CREATE TABLE IF NOT EXISTS channel_lead_entries (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	channel_id INTEGER NOT NULL, 
	period_month INTEGER NOT NULL, 
	period_year INTEGER NOT NULL, 
	lead_count INTEGER NOT NULL, 
	booked_count INTEGER NOT NULL, 
	revenue_cents INTEGER NOT NULL, 
	notes TEXT, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_channel_lead_period UNIQUE (channel_id, period_year, period_month), 
	FOREIGN KEY(channel_id) REFERENCES marketing_channels (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS `ix_channel_lead_entries_account_id` ON `channel_lead_entries` (`account_id`);
CREATE INDEX IF NOT EXISTS `ix_channel_lead_entries_channel_id` ON `channel_lead_entries` (`channel_id`);

-- Table: channel_spend_entries
CREATE TABLE IF NOT EXISTS channel_spend_entries (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	channel_id INTEGER NOT NULL, 
	period_month INTEGER NOT NULL, 
	period_year INTEGER NOT NULL, 
	amount_cents INTEGER NOT NULL, 
	notes TEXT, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_channel_spend_period UNIQUE (channel_id, period_year, period_month), 
	FOREIGN KEY(channel_id) REFERENCES marketing_channels (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS `ix_channel_spend_entries_channel_id` ON `channel_spend_entries` (`channel_id`);
CREATE INDEX IF NOT EXISTS `ix_channel_spend_entries_account_id` ON `channel_spend_entries` (`account_id`);

-- Table: crm_estimates
CREATE TABLE IF NOT EXISTS crm_estimates (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	crm_connection_id INTEGER, 
	external_estimate_id VARCHAR(128), 
	customer_name VARCHAR(255), 
	customer_email VARCHAR(255), 
	customer_phone VARCHAR(32), 
	job_type VARCHAR(255), 
	amount_cents INTEGER, 
	status VARCHAR(32) NOT NULL, 
	sent_at DATETIME, 
	viewed_at DATETIME, 
	responded_at DATETIME, 
	expires_at DATETIME, 
	follow_up_1_sent_at DATETIME, 
	follow_up_2_sent_at DATETIME, 
	source_provider VARCHAR(64), 
	raw_data JSON, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_crm_estimate UNIQUE (crm_connection_id, external_estimate_id), 
	FOREIGN KEY(crm_connection_id) REFERENCES crm_connections (id)
);

CREATE INDEX IF NOT EXISTS `ix_crm_estimates_status` ON `crm_estimates` (`status`);
CREATE INDEX IF NOT EXISTS `ix_crm_estimates_account_id` ON `crm_estimates` (`account_id`);
CREATE INDEX IF NOT EXISTS `ix_crm_estimates_crm_connection_id` ON `crm_estimates` (`crm_connection_id`);

-- Table: crm_jobs
CREATE TABLE IF NOT EXISTS crm_jobs (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	crm_connection_id INTEGER NOT NULL, 
	external_job_id VARCHAR(128) NOT NULL, 
	external_customer_id VARCHAR(128), 
	job_type VARCHAR(255), 
	job_status VARCHAR(64), 
	revenue_cents INTEGER, 
	job_date DATE, 
	appointment_at DATETIME, 
	appointment_reminder_sent_at DATETIME, 
	invoiced_at DATETIME, 
	lead_source VARCHAR(128), 
	call_event_id INTEGER, 
	campaign_id VARCHAR(64), 
	campaign_name VARCHAR(255), 
	created_at DATETIME NOT NULL, 
	synced_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_crm_job UNIQUE (crm_connection_id, external_job_id), 
	FOREIGN KEY(crm_connection_id) REFERENCES crm_connections (id)
);

CREATE INDEX IF NOT EXISTS `ix_crm_jobs_crm_connection_id` ON `crm_jobs` (`crm_connection_id`);
CREATE INDEX IF NOT EXISTS `ix_crm_jobs_job_date` ON `crm_jobs` (`job_date`);
CREATE INDEX IF NOT EXISTS `ix_crm_jobs_campaign_id` ON `crm_jobs` (`campaign_id`);
CREATE INDEX IF NOT EXISTS `ix_crm_jobs_account_id` ON `crm_jobs` (`account_id`);
CREATE INDEX IF NOT EXISTS `ix_crm_jobs_call_event_id` ON `crm_jobs` (`call_event_id`);

-- Table: daypart_bid_adjustments
CREATE TABLE IF NOT EXISTS daypart_bid_adjustments (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	campaign_id INTEGER NOT NULL, 
	google_campaign_id VARCHAR(64), 
	day_of_week INTEGER NOT NULL, 
	hour INTEGER NOT NULL, 
	bid_modifier FLOAT NOT NULL, 
	data_source VARCHAR(16) NOT NULL, 
	applied_at DATETIME, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_daypart_adj UNIQUE (campaign_id, day_of_week, hour), 
	FOREIGN KEY(campaign_id) REFERENCES ads_campaigns (id)
);

CREATE INDEX IF NOT EXISTS `ix_daypart_bid_adjustments_campaign_id` ON `daypart_bid_adjustments` (`campaign_id`);
CREATE INDEX IF NOT EXISTS `ix_daypart_bid_adjustments_account_id` ON `daypart_bid_adjustments` (`account_id`);

-- Table: email_sequences
CREATE TABLE IF NOT EXISTS email_sequences (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	campaign_id INTEGER, 
	step_number INTEGER NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	subject VARCHAR(500) NOT NULL, 
	body_html TEXT NOT NULL, 
	body_text TEXT, 
	delay_days INTEGER, 
	is_active BOOL, 
	sent_count INTEGER, 
	opened_count INTEGER, 
	replied_count INTEGER, 
	created_at DATETIME NOT NULL DEFAULT (now()), 
	updated_at DATETIME NOT NULL DEFAULT (now()), 
	PRIMARY KEY (id), 
	FOREIGN KEY(campaign_id) REFERENCES lead_campaigns (id)
);

CREATE INDEX IF NOT EXISTS `ix_email_sequences_campaign_id` ON `email_sequences` (`campaign_id`);

-- Table: email_unsubscribes
CREATE TABLE IF NOT EXISTS email_unsubscribes (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	email VARCHAR(255) NOT NULL, 
	unsubscribed_from_campaign_id INTEGER, 
	reason VARCHAR(500), 
	created_at DATETIME NOT NULL DEFAULT (now()), 
	PRIMARY KEY (id), 
	FOREIGN KEY(unsubscribed_from_campaign_id) REFERENCES lead_campaigns (id)
);

CREATE UNIQUE INDEX IF NOT EXISTS `ix_email_unsubscribes_email` ON `email_unsubscribes` (`email`);

-- Table: fb_ads
CREATE TABLE IF NOT EXISTS fb_ads (
	id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	fb_ad_id VARCHAR(64) NOT NULL, 
	fb_adset_id VARCHAR(64), 
	fb_campaign_id VARCHAR(64), 
	name VARCHAR(255), 
	status VARCHAR(32), 
	synced_at DATETIME, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_fb_ad UNIQUE (account_id, fb_ad_id), 
	FOREIGN KEY(account_id) REFERENCES accounts (id)
);

CREATE INDEX IF NOT EXISTS `ix_fb_ads_fb_adset_id` ON `fb_ads` (`fb_adset_id`);
CREATE INDEX IF NOT EXISTS `ix_fb_ads_fb_campaign_id` ON `fb_ads` (`fb_campaign_id`);
CREATE INDEX IF NOT EXISTS `ix_fb_ads_account_id` ON `fb_ads` (`account_id`);
CREATE INDEX IF NOT EXISTS `ix_fb_ads_fb_ad_id` ON `fb_ads` (`fb_ad_id`);

-- Table: fb_adsets
CREATE TABLE IF NOT EXISTS fb_adsets (
	id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	fb_adset_id VARCHAR(64) NOT NULL, 
	fb_campaign_id VARCHAR(64), 
	name VARCHAR(255), 
	status VARCHAR(32), 
	daily_budget BIGINT, 
	bid_amount BIGINT, 
	synced_at DATETIME, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_fb_adset UNIQUE (account_id, fb_adset_id), 
	FOREIGN KEY(account_id) REFERENCES accounts (id)
);

CREATE INDEX IF NOT EXISTS `ix_fb_adsets_account_id` ON `fb_adsets` (`account_id`);
CREATE INDEX IF NOT EXISTS `ix_fb_adsets_fb_adset_id` ON `fb_adsets` (`fb_adset_id`);
CREATE INDEX IF NOT EXISTS `ix_fb_adsets_fb_campaign_id` ON `fb_adsets` (`fb_campaign_id`);

-- Table: fb_campaigns
CREATE TABLE IF NOT EXISTS fb_campaigns (
	id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	fb_campaign_id VARCHAR(64) NOT NULL, 
	name VARCHAR(255), 
	status VARCHAR(32), 
	objective VARCHAR(64), 
	daily_budget BIGINT, 
	lifetime_budget BIGINT, 
	start_time DATETIME, 
	stop_time DATETIME, 
	synced_at DATETIME, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_fb_campaign UNIQUE (account_id, fb_campaign_id), 
	FOREIGN KEY(account_id) REFERENCES accounts (id)
);

CREATE INDEX IF NOT EXISTS `ix_fb_campaigns_account_id` ON `fb_campaigns` (`account_id`);
CREATE INDEX IF NOT EXISTS `ix_fb_campaigns_fb_campaign_id` ON `fb_campaigns` (`fb_campaign_id`);

-- Table: fb_daily_insights
CREATE TABLE IF NOT EXISTS fb_daily_insights (
	id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	fb_campaign_id VARCHAR(64), 
	date DATE NOT NULL, 
	spend NUMERIC(12, 2), 
	impressions INTEGER, 
	clicks INTEGER, 
	conversions INTEGER, 
	leads INTEGER, 
	cpm NUMERIC(10, 4), 
	cpc NUMERIC(10, 4), 
	ctr NUMERIC(8, 4), 
	PRIMARY KEY (id), 
	CONSTRAINT uq_fb_daily_insight UNIQUE (account_id, fb_campaign_id, date), 
	FOREIGN KEY(account_id) REFERENCES accounts (id)
);

CREATE INDEX IF NOT EXISTS `ix_fb_daily_insights_fb_campaign_id` ON `fb_daily_insights` (`fb_campaign_id`);
CREATE INDEX IF NOT EXISTS `ix_fb_daily_insights_date` ON `fb_daily_insights` (`date`);
CREATE INDEX IF NOT EXISTS `ix_fb_daily_insights_account_id` ON `fb_daily_insights` (`account_id`);

-- Table: glsa_leads
CREATE TABLE IF NOT EXISTS glsa_leads (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	account_id INTEGER, 
	glsa_account_id BIGINT NOT NULL, 
	lead_id VARCHAR(128), 
	name VARCHAR(255), 
	phone VARCHAR(32), 
	email VARCHAR(255), 
	job_type VARCHAR(128), 
	city VARCHAR(128), 
	lead_ts DATETIME, 
	recording_url TEXT, 
	notes JSON, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_glsa_leads_provider UNIQUE (glsa_account_id, lead_id), 
	FOREIGN KEY(glsa_account_id) REFERENCES glsa_accounts (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS `ix_glsa_leads_glsa_account_id` ON `glsa_leads` (`glsa_account_id`);
CREATE INDEX IF NOT EXISTS `ix_glsa_leads_job_type` ON `glsa_leads` (`job_type`);
CREATE INDEX IF NOT EXISTS `ix_glsa_leads_account_id` ON `glsa_leads` (`account_id`);

-- Table: glsa_profiles
CREATE TABLE IF NOT EXISTS glsa_profiles (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	account_id INTEGER, 
	glsa_account_id BIGINT NOT NULL, 
	business_name VARCHAR(255), 
	phone VARCHAR(32), 
	email VARCHAR(255), 
	website VARCHAR(255), 
	categories JSON, 
	service_areas JSON, 
	description TEXT, 
	hours JSON, 
	license_number VARCHAR(128), 
	verification_status VARCHAR(64), 
	rating FLOAT, 
	review_count INTEGER, 
	suggestions JSON, 
	last_synced_at DATETIME, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(glsa_account_id) REFERENCES glsa_accounts (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS `ix_glsa_profiles_business_name` ON `glsa_profiles` (`business_name`);
CREATE INDEX IF NOT EXISTS `ix_glsa_profiles_account_id` ON `glsa_profiles` (`account_id`);
CREATE INDEX IF NOT EXISTS `ix_glsa_profiles_glsa_account_id` ON `glsa_profiles` (`glsa_account_id`);

-- Table: keyword_overlaps
CREATE TABLE IF NOT EXISTS keyword_overlaps (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	group_id INTEGER NOT NULL, 
	account_id_a INTEGER NOT NULL, 
	campaign_id_a VARCHAR(64), 
	adgroup_id_a VARCHAR(64), 
	account_id_b INTEGER NOT NULL, 
	campaign_id_b VARCHAR(64), 
	adgroup_id_b VARCHAR(64), 
	keyword_text VARCHAR(255) NOT NULL, 
	match_type VARCHAR(20), 
	detected_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_overlap_group_accounts_kw_match UNIQUE (group_id, account_id_a, account_id_b, keyword_text, match_type), 
	FOREIGN KEY(group_id) REFERENCES location_groups (id)
);

-- Table: label_map
CREATE TABLE IF NOT EXISTS label_map (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	label_id BIGINT NOT NULL, 
	entity_type VARCHAR(32) NOT NULL, 
	entity_id BIGINT NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_label_entity UNIQUE (label_id, entity_type, entity_id), 
	FOREIGN KEY(label_id) REFERENCES labels (id) ON DELETE CASCADE
);

-- Table: lead_attributions
CREATE TABLE IF NOT EXISTS lead_attributions (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	channel_id INTEGER, 
	channel_type VARCHAR(64), 
	channel_name VARCHAR(255), 
	lead_ingest_id INTEGER, 
	aggregator_lead_id INTEGER, 
	call_event_id INTEGER, 
	phone VARCHAR(64), 
	email VARCHAR(255), 
	st_job_id INTEGER, 
	job_status VARCHAR(50), 
	revenue_cents INTEGER, 
	lead_cost_cents INTEGER, 
	lead_occurred_at DATETIME, 
	job_completed_at DATETIME, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(channel_id) REFERENCES marketing_channels (id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS `ix_lead_attributions_account_id` ON `lead_attributions` (`account_id`);
CREATE INDEX IF NOT EXISTS `idx_lead_attr_account_occurred_at` ON `lead_attributions` (`account_id`, `lead_occurred_at`);
CREATE INDEX IF NOT EXISTS `ix_lead_attributions_phone` ON `lead_attributions` (`phone`);
CREATE INDEX IF NOT EXISTS `idx_lead_attr_account_channel_type` ON `lead_attributions` (`account_id`, `channel_type`);
CREATE INDEX IF NOT EXISTS `ix_lead_attributions_channel_id` ON `lead_attributions` (`channel_id`);

-- Table: linkedin_campaigns
CREATE TABLE IF NOT EXISTS linkedin_campaigns (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	account_id BIGINT NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	description TEXT, 
	start_date DATE NOT NULL, 
	end_date DATE, 
	posts_per_week INTEGER NOT NULL DEFAULT '3', 
	category_rotation VARCHAR(20) DEFAULT 'round_robin', 
	status VARCHAR(20) NOT NULL DEFAULT 'active', 
	posts_generated INTEGER NOT NULL DEFAULT '0', 
	last_generation_date DATE, 
	created_at DATETIME NOT NULL DEFAULT (now()), 
	updated_at DATETIME NOT NULL DEFAULT (now()), 
	PRIMARY KEY (id), 
	FOREIGN KEY(account_id) REFERENCES accounts (id)
);

CREATE INDEX IF NOT EXISTS `ix_linkedin_campaigns_account_id` ON `linkedin_campaigns` (`account_id`);

-- Table: linkedin_categories
CREATE TABLE IF NOT EXISTS linkedin_categories (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	account_id BIGINT NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	description TEXT, 
	pov_statement TEXT NOT NULL, 
	unique_expertise TEXT, 
	post_frequency VARCHAR(20) DEFAULT 'weekly', 
	priority INTEGER DEFAULT '1', 
	is_active BOOL NOT NULL DEFAULT 'true', 
	posts_generated INTEGER NOT NULL DEFAULT '0', 
	last_post_date DATE, 
	created_at DATETIME NOT NULL DEFAULT (now()), 
	updated_at DATETIME NOT NULL DEFAULT (now()), 
	PRIMARY KEY (id), 
	FOREIGN KEY(account_id) REFERENCES accounts (id)
);

CREATE INDEX IF NOT EXISTS `ix_linkedin_categories_account_id` ON `linkedin_categories` (`account_id`);

-- Table: linkedin_scheduled_posts
CREATE TABLE IF NOT EXISTS linkedin_scheduled_posts (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	account_id BIGINT NOT NULL, 
	post_text TEXT NOT NULL, 
	scheduled_date DATE NOT NULL, 
	scheduled_time VARCHAR(5) DEFAULT '09:00', 
	expertise TEXT, 
	industry VARCHAR(100), 
	topic TEXT, 
	tone VARCHAR(50), 
	status VARCHAR(20) NOT NULL DEFAULT 'scheduled', 
	posted_at DATETIME, 
	error_message TEXT, 
	created_at DATETIME NOT NULL DEFAULT (now()), 
	updated_at DATETIME NOT NULL DEFAULT (now()), 
	PRIMARY KEY (id), 
	FOREIGN KEY(account_id) REFERENCES accounts (id)
);

CREATE INDEX IF NOT EXISTS `ix_linkedin_scheduled_posts_scheduled_date` ON `linkedin_scheduled_posts` (`scheduled_date`);
CREATE INDEX IF NOT EXISTS `ix_linkedin_scheduled_posts_status` ON `linkedin_scheduled_posts` (`status`);
CREATE INDEX IF NOT EXISTS `ix_linkedin_scheduled_posts_account_id` ON `linkedin_scheduled_posts` (`account_id`);

-- Table: location_group_members
CREATE TABLE IF NOT EXISTS location_group_members (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	group_id INTEGER NOT NULL, 
	account_id INTEGER NOT NULL, 
	location_label VARCHAR(120), 
	joined_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_lgm_group_account UNIQUE (group_id, account_id), 
	FOREIGN KEY(group_id) REFERENCES location_groups (id)
);

-- Table: optimizer_actions
CREATE TABLE IF NOT EXISTS optimizer_actions (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	recommendation_id BIGINT NOT NULL, 
	applied_by BIGINT, 
	applied_at DATETIME, 
	change_set_json TEXT NOT NULL, 
	result_json TEXT, 
	status VARCHAR(16) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(recommendation_id) REFERENCES optimizer_recommendations (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS `ix_optimizer_actions_recommendation_id` ON `optimizer_actions` (`recommendation_id`);

-- Table: pov_profiles
CREATE TABLE IF NOT EXISTS pov_profiles (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	user_id INTEGER, 
	site_id INTEGER, 
	scope ENUM('global','site','service') NOT NULL, 
	name VARCHAR(191) NOT NULL, 
	slug VARCHAR(191) NOT NULL, 
	industry VARCHAR(191), 
	service_key VARCHAR(191), 
	pov_text TEXT NOT NULL, 
	brand_voice VARCHAR(255), 
	tone VARCHAR(40), 
	customer_needs TEXT, 
	expertise_bullets TEXT, 
	answers_json TEXT, 
	source VARCHAR(40), 
	is_default BOOL NOT NULL, 
	is_archived BOOL NOT NULL, 
	created_at DATETIME, 
	updated_at DATETIME, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_account_slug UNIQUE (account_id, slug), 
	FOREIGN KEY(site_id) REFERENCES wp_sites (id)
);

-- Table: servicetitan_capacity
CREATE TABLE IF NOT EXISTS servicetitan_capacity (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	capacity_date DATE NOT NULL, 
	st_business_unit_id BIGINT, 
	business_unit_name VARCHAR(255), 
	total_slots INTEGER NOT NULL, 
	booked_slots INTEGER NOT NULL, 
	available_slots INTEGER NOT NULL, 
	utilization_percent NUMERIC(5, 2), 
	total_technicians INTEGER NOT NULL, 
	available_technicians INTEGER NOT NULL, 
	scheduled_revenue NUMERIC(12, 2), 
	capacity_score NUMERIC(5, 2), 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_st_capacity_per_day UNIQUE (account_id, capacity_date, st_business_unit_id), 
	FOREIGN KEY(account_id) REFERENCES accounts (id)
);

CREATE INDEX IF NOT EXISTS `ix_servicetitan_capacity_account_id` ON `servicetitan_capacity` (`account_id`);
CREATE INDEX IF NOT EXISTS `idx_st_capacity_account` ON `servicetitan_capacity` (`account_id`);
CREATE INDEX IF NOT EXISTS `ix_servicetitan_capacity_capacity_date` ON `servicetitan_capacity` (`capacity_date`);
CREATE INDEX IF NOT EXISTS `idx_st_capacity_date` ON `servicetitan_capacity` (`capacity_date`);

-- Table: servicetitan_customers
CREATE TABLE IF NOT EXISTS servicetitan_customers (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	st_customer_id BIGINT NOT NULL, 
	name VARCHAR(255), 
	first_name VARCHAR(100), 
	last_name VARCHAR(100), 
	email VARCHAR(255), 
	phone VARCHAR(50), 
	address VARCHAR(255), 
	city VARCHAR(100), 
	state VARCHAR(50), 
	zip_code VARCHAR(20), 
	customer_type VARCHAR(50), 
	lifetime_value NUMERIC(12, 2), 
	job_count INTEGER NOT NULL, 
	st_data JSON, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	st_created_at DATETIME, 
	st_modified_at DATETIME, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_st_customer_per_account UNIQUE (account_id, st_customer_id), 
	FOREIGN KEY(account_id) REFERENCES accounts (id)
);

CREATE INDEX IF NOT EXISTS `idx_st_customers_account` ON `servicetitan_customers` (`account_id`);
CREATE INDEX IF NOT EXISTS `idx_st_customers_st_id` ON `servicetitan_customers` (`st_customer_id`);
CREATE INDEX IF NOT EXISTS `ix_servicetitan_customers_account_id` ON `servicetitan_customers` (`account_id`);
CREATE INDEX IF NOT EXISTS `ix_servicetitan_customers_st_customer_id` ON `servicetitan_customers` (`st_customer_id`);
CREATE INDEX IF NOT EXISTS `ix_servicetitan_customers_email` ON `servicetitan_customers` (`email`);

-- Table: servicetitan_job_types
CREATE TABLE IF NOT EXISTS servicetitan_job_types (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	st_job_type_id BIGINT NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	description TEXT, 
	avg_revenue NUMERIC(12, 2), 
	total_jobs INTEGER NOT NULL, 
	total_revenue NUMERIC(12, 2), 
	st_data JSON, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_st_job_type_per_account UNIQUE (account_id, st_job_type_id), 
	FOREIGN KEY(account_id) REFERENCES accounts (id)
);

CREATE INDEX IF NOT EXISTS `ix_servicetitan_job_types_account_id` ON `servicetitan_job_types` (`account_id`);
CREATE INDEX IF NOT EXISTS `idx_st_job_types_account` ON `servicetitan_job_types` (`account_id`);
CREATE INDEX IF NOT EXISTS `ix_servicetitan_job_types_st_job_type_id` ON `servicetitan_job_types` (`st_job_type_id`);

-- Table: servicetitan_jobs
CREATE TABLE IF NOT EXISTS servicetitan_jobs (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	st_job_id BIGINT NOT NULL, 
	st_customer_id BIGINT, 
	st_job_type_id BIGINT, 
	st_business_unit_id BIGINT, 
	job_number VARCHAR(50), 
	job_status VARCHAR(50), 
	job_type_name VARCHAR(255), 
	total_amount NUMERIC(12, 2), 
	outstanding_balance NUMERIC(12, 2), 
	invoice_amount NUMERIC(12, 2), 
	scheduled_date DATETIME, 
	completed_date DATETIME, 
	start_date DATETIME, 
	lead_source VARCHAR(255), 
	campaign_name VARCHAR(255), 
	st_data JSON, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	st_created_at DATETIME, 
	st_modified_at DATETIME, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_st_job_per_account UNIQUE (account_id, st_job_id), 
	FOREIGN KEY(account_id) REFERENCES accounts (id)
);

CREATE INDEX IF NOT EXISTS `ix_servicetitan_jobs_job_number` ON `servicetitan_jobs` (`job_number`);
CREATE INDEX IF NOT EXISTS `idx_st_jobs_status` ON `servicetitan_jobs` (`job_status`);
CREATE INDEX IF NOT EXISTS `idx_st_jobs_customer` ON `servicetitan_jobs` (`st_customer_id`);
CREATE INDEX IF NOT EXISTS `idx_st_jobs_scheduled` ON `servicetitan_jobs` (`scheduled_date`);
CREATE INDEX IF NOT EXISTS `ix_servicetitan_jobs_scheduled_date` ON `servicetitan_jobs` (`scheduled_date`);
CREATE INDEX IF NOT EXISTS `idx_st_jobs_lead_source` ON `servicetitan_jobs` (`lead_source`);
CREATE INDEX IF NOT EXISTS `ix_servicetitan_jobs_st_customer_id` ON `servicetitan_jobs` (`st_customer_id`);
CREATE INDEX IF NOT EXISTS `idx_st_jobs_st_id` ON `servicetitan_jobs` (`st_job_id`);
CREATE INDEX IF NOT EXISTS `ix_servicetitan_jobs_job_status` ON `servicetitan_jobs` (`job_status`);
CREATE INDEX IF NOT EXISTS `ix_servicetitan_jobs_completed_date` ON `servicetitan_jobs` (`completed_date`);
CREATE INDEX IF NOT EXISTS `idx_st_jobs_account` ON `servicetitan_jobs` (`account_id`);
CREATE INDEX IF NOT EXISTS `ix_servicetitan_jobs_account_id` ON `servicetitan_jobs` (`account_id`);
CREATE INDEX IF NOT EXISTS `ix_servicetitan_jobs_st_job_id` ON `servicetitan_jobs` (`st_job_id`);
CREATE INDEX IF NOT EXISTS `ix_servicetitan_jobs_lead_source` ON `servicetitan_jobs` (`lead_source`);
CREATE INDEX IF NOT EXISTS `ix_servicetitan_jobs_st_job_type_id` ON `servicetitan_jobs` (`st_job_type_id`);

-- Table: servicetitan_sync_logs
CREATE TABLE IF NOT EXISTS servicetitan_sync_logs (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	sync_type VARCHAR(50) NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	started_at DATETIME NOT NULL, 
	completed_at DATETIME, 
	duration_seconds INTEGER, 
	records_fetched INTEGER, 
	records_created INTEGER, 
	records_updated INTEGER, 
	records_failed INTEGER, 
	error_message TEXT, 
	error_details JSON, 
	api_calls_made INTEGER, 
	PRIMARY KEY (id), 
	FOREIGN KEY(account_id) REFERENCES accounts (id)
);

CREATE INDEX IF NOT EXISTS `ix_servicetitan_sync_logs_account_id` ON `servicetitan_sync_logs` (`account_id`);
CREATE INDEX IF NOT EXISTS `ix_servicetitan_sync_logs_status` ON `servicetitan_sync_logs` (`status`);
CREATE INDEX IF NOT EXISTS `idx_st_sync_logs_account` ON `servicetitan_sync_logs` (`account_id`);
CREATE INDEX IF NOT EXISTS `ix_servicetitan_sync_logs_started_at` ON `servicetitan_sync_logs` (`started_at`);
CREATE INDEX IF NOT EXISTS `idx_st_sync_logs_type` ON `servicetitan_sync_logs` (`sync_type`);
CREATE INDEX IF NOT EXISTS `idx_st_sync_logs_started` ON `servicetitan_sync_logs` (`started_at`);
CREATE INDEX IF NOT EXISTS `ix_servicetitan_sync_logs_sync_type` ON `servicetitan_sync_logs` (`sync_type`);

-- Table: servicetitan_technicians
CREATE TABLE IF NOT EXISTS servicetitan_technicians (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	st_technician_id BIGINT NOT NULL, 
	st_business_unit_id BIGINT, 
	name VARCHAR(255), 
	email VARCHAR(255), 
	phone VARCHAR(50), 
	is_active BOOL NOT NULL, 
	st_data JSON, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_st_technician_per_account UNIQUE (account_id, st_technician_id), 
	FOREIGN KEY(account_id) REFERENCES accounts (id)
);

CREATE INDEX IF NOT EXISTS `ix_servicetitan_technicians_account_id` ON `servicetitan_technicians` (`account_id`);
CREATE INDEX IF NOT EXISTS `idx_st_technicians_account` ON `servicetitan_technicians` (`account_id`);
CREATE INDEX IF NOT EXISTS `ix_servicetitan_technicians_st_technician_id` ON `servicetitan_technicians` (`st_technician_id`);

-- Table: shared_negative_items
CREATE TABLE IF NOT EXISTS shared_negative_items (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	list_id BIGINT NOT NULL, 
	text VARCHAR(255) NOT NULL, 
	match_type VARCHAR(16) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_list_kw UNIQUE (list_id, text, match_type), 
	FOREIGN KEY(list_id) REFERENCES shared_negative_lists (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS `ix_shared_negative_items_list_id` ON `shared_negative_items` (`list_id`);

-- Table: shared_negative_map
CREATE TABLE IF NOT EXISTS shared_negative_map (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	list_id BIGINT NOT NULL, 
	campaign_id INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_list_campaign UNIQUE (list_id, campaign_id), 
	FOREIGN KEY(list_id) REFERENCES shared_negative_lists (id) ON DELETE CASCADE, 
	FOREIGN KEY(campaign_id) REFERENCES ads_campaigns (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS `ix_shared_negative_map_campaign_id` ON `shared_negative_map` (`campaign_id`);
CREATE INDEX IF NOT EXISTS `ix_shared_negative_map_list_id` ON `shared_negative_map` (`list_id`);

-- Table: social_calendar_posts
CREATE TABLE IF NOT EXISTS social_calendar_posts (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	account_id BIGINT NOT NULL, 
	platform VARCHAR(20) NOT NULL, 
	scheduled_date DATE NOT NULL, 
	scheduled_time VARCHAR(5) DEFAULT '09:00', 
	post_type VARCHAR(50), 
	copy_text TEXT, 
	title VARCHAR(200), 
	link VARCHAR(500), 
	campaign VARCHAR(200), 
	creative_url VARCHAR(500), 
	post_owner VARCHAR(100), 
	status VARCHAR(20) NOT NULL DEFAULT 'pending', 
	engagement_rate FLOAT, 
	created_at DATETIME NOT NULL DEFAULT (now()), 
	updated_at DATETIME NOT NULL DEFAULT (now()), 
	PRIMARY KEY (id), 
	FOREIGN KEY(account_id) REFERENCES accounts (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS `ix_social_calendar_posts_platform` ON `social_calendar_posts` (`platform`);
CREATE INDEX IF NOT EXISTS `ix_social_calendar_posts_account_id` ON `social_calendar_posts` (`account_id`);
CREATE INDEX IF NOT EXISTS `ix_social_calendar_posts_scheduled_date` ON `social_calendar_posts` (`scheduled_date`);

-- Table: suggestions
CREATE TABLE IF NOT EXISTS suggestions (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	snapshot_id INTEGER NOT NULL, 
	suggestion_json JSON NOT NULL, 
	accepted BOOL NOT NULL DEFAULT '0', 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(snapshot_id) REFERENCES performance_snapshots (id)
);

CREATE INDEX IF NOT EXISTS `ix_suggestions_user_id` ON `suggestions` (`user_id`);
CREATE INDEX IF NOT EXISTS `ix_suggestions_snapshot_id` ON `suggestions` (`snapshot_id`);
CREATE INDEX IF NOT EXISTS `ix_suggestions_account_id` ON `suggestions` (`account_id`);

-- Table: users
CREATE TABLE IF NOT EXISTS users (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	email VARCHAR(255) NOT NULL, 
	password_hash VARCHAR(255) NOT NULL, 
	`role` VARCHAR(32) NOT NULL DEFAULT 'member', 
	email_verified BOOL NOT NULL DEFAULT '0', 
	email_verified_at DATETIME, 
	phone_number VARCHAR(20), 
	sms_opt_in BOOL NOT NULL DEFAULT '0', 
	phone_verified BOOL NOT NULL DEFAULT '0', 
	phone_verified_at DATETIME, 
	created_at DATETIME NOT NULL DEFAULT (now()), 
	updated_at DATETIME NOT NULL DEFAULT (now()), 
	PRIMARY KEY (id), 
	FOREIGN KEY(account_id) REFERENCES accounts (id)
);

CREATE INDEX IF NOT EXISTS `ix_users_role` ON `users` (`role`);
CREATE UNIQUE INDEX IF NOT EXISTS `ix_users_email` ON `users` (`email`);
CREATE INDEX IF NOT EXISTS `ix_users_account_id` ON `users` (`account_id`);

-- Table: wp_jobs
CREATE TABLE IF NOT EXISTS wp_jobs (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	site_id INTEGER NOT NULL, 
	kind VARCHAR(32) NOT NULL, 
	payload JSON NOT NULL, 
	run_at DATETIME, 
	status VARCHAR(32) NOT NULL, 
	last_error TEXT, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(site_id) REFERENCES wp_sites (id)
);

-- Table: wp_keyword_rank_snapshots
CREATE TABLE IF NOT EXISTS wp_keyword_rank_snapshots (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	wp_site_id INTEGER, 
	url VARCHAR(512) NOT NULL, 
	keyword VARCHAR(255) NOT NULL, 
	position NUMERIC(6, 2), 
	impressions INTEGER, 
	clicks INTEGER, 
	ctr NUMERIC(6, 4), 
	snapshot_date DATE NOT NULL, 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_kw_snapshot UNIQUE (account_id, url, keyword, snapshot_date), 
	FOREIGN KEY(account_id) REFERENCES accounts (id)
);

CREATE INDEX IF NOT EXISTS `ix_wp_keyword_rank_snapshots_account_id` ON `wp_keyword_rank_snapshots` (`account_id`);

-- Table: ad_creatives
CREATE TABLE IF NOT EXISTS ad_creatives (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	user_id INTEGER, 
	account_id INTEGER, 
	name VARCHAR(255) NOT NULL, 
	platform ENUM('facebook','instagram','linkedin','twitter','google','multi') NOT NULL, 
	image_url VARCHAR(1000), 
	image_prompt TEXT, 
	image_storage_key VARCHAR(500), 
	headline VARCHAR(255), 
	primary_text TEXT, 
	description VARCHAR(500), 
	call_to_action VARCHAR(100), 
	generation_method ENUM('ai_website','ai_manual','manual','template') NOT NULL, 
	source_url VARCHAR(1000), 
	template_id INTEGER, 
	image_model VARCHAR(100), 
	copy_model VARCHAR(100), 
	industry VARCHAR(100), 
	target_audience VARCHAR(255), 
	ad_objective VARCHAR(100), 
	used_in_campaign BOOL, 
	impressions INTEGER, 
	clicks INTEGER, 
	conversions INTEGER, 
	status ENUM('draft','approved','published','archived') NOT NULL, 
	extra_data JSON, 
	created_at DATETIME NOT NULL DEFAULT (now()), 
	updated_at DATETIME NOT NULL DEFAULT (now()), 
	published_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id), 
	FOREIGN KEY(account_id) REFERENCES accounts (id)
);

CREATE INDEX IF NOT EXISTS `ix_ad_creatives_account_id` ON `ad_creatives` (`account_id`);
CREATE INDEX IF NOT EXISTS `ix_ad_creatives_user_id` ON `ad_creatives` (`user_id`);

-- Table: admin_audit_logs
CREATE TABLE IF NOT EXISTS admin_audit_logs (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	admin_user_id INTEGER, 
	action VARCHAR(64) NOT NULL, 
	target_user_id INTEGER, 
	target_account_id INTEGER, 
	note VARCHAR(1000) NOT NULL DEFAULT '', 
	ip VARCHAR(45), 
	user_agent VARCHAR(255), 
	created_at DATETIME NOT NULL DEFAULT (now()), 
	PRIMARY KEY (id), 
	FOREIGN KEY(admin_user_id) REFERENCES users (id), 
	FOREIGN KEY(target_user_id) REFERENCES users (id), 
	FOREIGN KEY(target_account_id) REFERENCES accounts (id)
);

CREATE INDEX IF NOT EXISTS `ix_admin_audit_logs_created_at` ON `admin_audit_logs` (`created_at`);
CREATE INDEX IF NOT EXISTS `ix_admin_audit_logs_admin_user_id` ON `admin_audit_logs` (`admin_user_id`);
CREATE INDEX IF NOT EXISTS `ix_admin_audit_logs_target_account_id` ON `admin_audit_logs` (`target_account_id`);
CREATE INDEX IF NOT EXISTS `ix_admin_audit_logs_target_user_id` ON `admin_audit_logs` (`target_user_id`);
CREATE INDEX IF NOT EXISTS `ix_admin_audit_logs_action` ON `admin_audit_logs` (`action`);

-- Table: ads
CREATE TABLE IF NOT EXISTS ads (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	ad_group_id INTEGER NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	ad_type VARCHAR(20) NOT NULL, 
	headline1 VARCHAR(30) NOT NULL, 
	headline2 VARCHAR(30), 
	headline3 VARCHAR(30), 
	description1 VARCHAR(90), 
	description2 VARCHAR(90), 
	path1 VARCHAR(15), 
	path2 VARCHAR(15), 
	final_url VARCHAR(2048) NOT NULL, 
	google_ad_id VARCHAR(64), 
	variant_group VARCHAR(64), 
	is_control BOOL NOT NULL, 
	test_name VARCHAR(128), 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(ad_group_id) REFERENCES ad_groups (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS `ix_ads_ad_group_id` ON `ads` (`ad_group_id`);
CREATE INDEX IF NOT EXISTS `ix_ads_google_ad_id` ON `ads` (`google_ad_id`);
CREATE INDEX IF NOT EXISTS `ix_ads_variant_group` ON `ads` (`variant_group`);

-- Table: agent_knowledge_sources
CREATE TABLE IF NOT EXISTS agent_knowledge_sources (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	agent_type VARCHAR(64) NOT NULL, 
	title VARCHAR(255) NOT NULL, 
	url TEXT NOT NULL, 
	source_type VARCHAR(32), 
	category VARCHAR(64), 
	refresh_frequency VARCHAR(16), 
	is_approved BOOL NOT NULL, 
	is_active BOOL NOT NULL, 
	is_default BOOL NOT NULL, 
	approved_by_user_id INTEGER, 
	last_fetched_at DATETIME, 
	fetch_error TEXT, 
	created_at DATETIME, 
	updated_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(approved_by_user_id) REFERENCES users (id)
);

CREATE INDEX IF NOT EXISTS `ix_agent_knowledge_sources_agent_type` ON `agent_knowledge_sources` (`agent_type`);

-- Table: alert_settings
CREATE TABLE IF NOT EXISTS alert_settings (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	user_id INTEGER NOT NULL, 
	paused_campaign_enabled BOOL NOT NULL, 
	cpl_spike_enabled BOOL NOT NULL, 
	cpl_spike_threshold_percent INTEGER NOT NULL, 
	cpl_spike_lookback_days INTEGER NOT NULL, 
	quality_score_enabled BOOL NOT NULL, 
	quality_score_threshold INTEGER NOT NULL, 
	email_notifications_enabled BOOL NOT NULL, 
	email_digest_enabled BOOL NOT NULL, 
	email_digest_time VARCHAR(5) NOT NULL, 
	max_alerts_per_day INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE UNIQUE INDEX IF NOT EXISTS `ix_alert_settings_user_id` ON `alert_settings` (`user_id`);

-- Table: alerts
CREATE TABLE IF NOT EXISTS alerts (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	alert_type ENUM('paused_campaign','cpl_spike','quality_score_drop','custom') NOT NULL, 
	severity ENUM('info','warning','critical') NOT NULL, 
	title VARCHAR(255) NOT NULL, 
	description TEXT NOT NULL, 
	data JSON, 
	status ENUM('active','resolved','dismissed') NOT NULL, 
	created_at DATETIME NOT NULL, 
	resolved_at DATETIME, 
	dismissed_at DATETIME, 
	notified_at DATETIME, 
	email_sent BOOL NOT NULL, 
	action_url VARCHAR(512), 
	action_text VARCHAR(100), 
	PRIMARY KEY (id), 
	FOREIGN KEY(account_id) REFERENCES accounts (id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE INDEX IF NOT EXISTS `idx_alerts_account_status` ON `alerts` (`account_id`, `status`);
CREATE INDEX IF NOT EXISTS `ix_alerts_created_at` ON `alerts` (`created_at`);
CREATE INDEX IF NOT EXISTS `ix_alerts_status` ON `alerts` (`status`);
CREATE INDEX IF NOT EXISTS `idx_alerts_user_status` ON `alerts` (`user_id`, `status`);
CREATE INDEX IF NOT EXISTS `ix_alerts_account_id` ON `alerts` (`account_id`);
CREATE INDEX IF NOT EXISTS `idx_alerts_type_status` ON `alerts` (`alert_type`, `status`);
CREATE INDEX IF NOT EXISTS `ix_alerts_alert_type` ON `alerts` (`alert_type`);
CREATE INDEX IF NOT EXISTS `ix_alerts_severity` ON `alerts` (`severity`);
CREATE INDEX IF NOT EXISTS `idx_alerts_created` ON `alerts` (`created_at`);
CREATE INDEX IF NOT EXISTS `ix_alerts_user_id` ON `alerts` (`user_id`);

-- Table: audit_logs
CREATE TABLE IF NOT EXISTS audit_logs (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	user_id INTEGER, 
	account_id INTEGER NOT NULL, 
	action VARCHAR(64) NOT NULL, 
	resource_type VARCHAR(64), 
	resource_id VARCHAR(64), 
	context_data JSON, 
	ip_address VARCHAR(45), 
	user_agent VARCHAR(255), 
	created_at DATETIME NOT NULL DEFAULT (now()), 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id), 
	FOREIGN KEY(account_id) REFERENCES accounts (id)
);

CREATE INDEX IF NOT EXISTS `ix_audit_logs_action` ON `audit_logs` (`action`);
CREATE INDEX IF NOT EXISTS `idx_audit_user_created` ON `audit_logs` (`user_id`, `created_at`);
CREATE INDEX IF NOT EXISTS `ix_audit_logs_resource_type` ON `audit_logs` (`resource_type`);
CREATE INDEX IF NOT EXISTS `idx_audit_account_action` ON `audit_logs` (`account_id`, `action`);
CREATE INDEX IF NOT EXISTS `idx_audit_resource` ON `audit_logs` (`resource_type`, `resource_id`);
CREATE INDEX IF NOT EXISTS `ix_audit_logs_user_id` ON `audit_logs` (`user_id`);
CREATE INDEX IF NOT EXISTS `ix_audit_logs_created_at` ON `audit_logs` (`created_at`);
CREATE INDEX IF NOT EXISTS `ix_audit_logs_account_id` ON `audit_logs` (`account_id`);

-- Table: budget_trackers
CREATE TABLE IF NOT EXISTS budget_trackers (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	customer_id VARCHAR(32) NOT NULL, 
	campaign_id VARCHAR(32), 
	campaign_name VARCHAR(255), 
	budget_type ENUM('monthly','weekly','daily','campaign') NOT NULL, 
	budget_amount INTEGER NOT NULL, 
	start_date DATETIME NOT NULL, 
	end_date DATETIME NOT NULL, 
	alert_threshold_percent INTEGER NOT NULL, 
	alert_enabled BOOL NOT NULL, 
	status ENUM('active','paused','completed','cancelled') NOT NULL, 
	last_checked_at DATETIME, 
	last_spend_amount INTEGER, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(account_id) REFERENCES accounts (id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE INDEX IF NOT EXISTS `idx_budget_trackers_end_date` ON `budget_trackers` (`end_date`);
CREATE INDEX IF NOT EXISTS `ix_budget_trackers_end_date` ON `budget_trackers` (`end_date`);
CREATE INDEX IF NOT EXISTS `idx_budget_trackers_status` ON `budget_trackers` (`status`);
CREATE INDEX IF NOT EXISTS `ix_budget_trackers_user_id` ON `budget_trackers` (`user_id`);
CREATE INDEX IF NOT EXISTS `ix_budget_trackers_account_id` ON `budget_trackers` (`account_id`);
CREATE INDEX IF NOT EXISTS `idx_budget_trackers_customer` ON `budget_trackers` (`customer_id`);
CREATE INDEX IF NOT EXISTS `ix_budget_trackers_campaign_id` ON `budget_trackers` (`campaign_id`);
CREATE INDEX IF NOT EXISTS `ix_budget_trackers_customer_id` ON `budget_trackers` (`customer_id`);
CREATE INDEX IF NOT EXISTS `idx_budget_trackers_account` ON `budget_trackers` (`account_id`);
CREATE INDEX IF NOT EXISTS `ix_budget_trackers_status` ON `budget_trackers` (`status`);

-- Table: campaign_uploads
CREATE TABLE IF NOT EXISTS campaign_uploads (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	campaign_draft_id INTEGER NOT NULL, 
	upload_status ENUM('pending','success','failed') NOT NULL DEFAULT 'pending', 
	google_ads_job_id VARCHAR(128), 
	error_text TEXT, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(campaign_draft_id) REFERENCES campaign_drafts (id)
);

CREATE INDEX IF NOT EXISTS `ix_campaign_uploads_account_id` ON `campaign_uploads` (`account_id`);
CREATE INDEX IF NOT EXISTS `ix_campaign_uploads_campaign_draft_id` ON `campaign_uploads` (`campaign_draft_id`);
CREATE INDEX IF NOT EXISTS `ix_campaign_uploads_user_id` ON `campaign_uploads` (`user_id`);

-- Table: crm_contacts
CREATE TABLE IF NOT EXISTS crm_contacts (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	stage VARCHAR(24) NOT NULL, 
	business_name VARCHAR(255) NOT NULL, 
	contact_name VARCHAR(255), 
	email VARCHAR(255), 
	phone VARCHAR(64), 
	domain VARCHAR(255), 
	address1 VARCHAR(255), 
	address2 VARCHAR(255), 
	city VARCHAR(128), 
	region VARCHAR(128), 
	postal_code VARCHAR(32), 
	country VARCHAR(64), 
	source VARCHAR(128), 
	notes TEXT, 
	last_crawled_at DATETIME, 
	crawl_attempts INTEGER NOT NULL, 
	owner_user_id INTEGER, 
	account_id INTEGER, 
	PRIMARY KEY (id), 
	FOREIGN KEY(owner_user_id) REFERENCES users (id), 
	FOREIGN KEY(account_id) REFERENCES accounts (id)
);

CREATE INDEX IF NOT EXISTS `idx_crm_contacts_domain` ON `crm_contacts` (`domain`);
CREATE INDEX IF NOT EXISTS `idx_crm_contacts_stage` ON `crm_contacts` (`stage`);
CREATE INDEX IF NOT EXISTS `idx_crm_contacts_email` ON `crm_contacts` (`email`);
CREATE INDEX IF NOT EXISTS `idx_crm_contacts_created_at` ON `crm_contacts` (`created_at`);

-- Table: email_templates
CREATE TABLE IF NOT EXISTS email_templates (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	name VARCHAR(255) NOT NULL, 
	description TEXT, 
	subject VARCHAR(500) NOT NULL, 
	body_html LONGTEXT, 
	body_text TEXT, 
	created_by_user_id INTEGER, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	is_active BOOL NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(created_by_user_id) REFERENCES users (id)
);

CREATE UNIQUE INDEX IF NOT EXISTS `ix_email_templates_name` ON `email_templates` (`name`);

-- Table: email_workflows
CREATE TABLE IF NOT EXISTS email_workflows (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	name VARCHAR(255) NOT NULL, 
	description TEXT, 
	target_groups JSON, 
	created_by_user_id INTEGER, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	is_active BOOL NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(created_by_user_id) REFERENCES users (id)
);

CREATE UNIQUE INDEX IF NOT EXISTS `ix_email_workflows_name` ON `email_workflows` (`name`);

-- Table: facebook_ads_grader_reports
CREATE TABLE IF NOT EXISTS facebook_ads_grader_reports (
	id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
	account_id INTEGER, 
	user_id INTEGER, 
	fb_ad_account_id VARCHAR(128) NOT NULL, 
	fb_ad_account_name VARCHAR(255), 
	fb_business_id VARCHAR(128), 
	fb_business_name VARCHAR(255), 
	currency VARCHAR(10), 
	overall_score FLOAT NOT NULL, 
	overall_grade VARCHAR(3) NOT NULL, 
	ctr_avg FLOAT, 
	cpc_avg FLOAT, 
	cpm_avg FLOAT, 
	relevance_score_avg FLOAT, 
	roas_avg FLOAT, 
	conversion_rate_avg FLOAT, 
	wasted_spend_365d FLOAT, 
	projected_waste_12m FLOAT, 
	active_campaigns INTEGER, 
	active_ad_sets INTEGER, 
	active_ads INTEGER, 
	total_audiences INTEGER, 
	clicks_365d INTEGER, 
	impressions_365d BIGINT, 
	conversions_365d INTEGER, 
	spend_365d FLOAT, 
	revenue_365d FLOAT, 
	avg_monthly_spend FLOAT, 
	wasted_spend_score FLOAT, 
	creative_optimization_score FLOAT, 
	audience_targeting_score FLOAT, 
	relevance_score_optimization_score FLOAT, 
	ctr_optimization_score FLOAT, 
	account_activity_score FLOAT, 
	ad_format_diversity_score FLOAT, 
	campaign_structure_score FLOAT, 
	landing_page_score FLOAT, 
	mobile_optimization_score FLOAT, 
	conversion_tracking_score FLOAT, 
	roas_score FLOAT, 
	detailed_metrics JSON, 
	best_practices JSON, 
	recommendations JSON, 
	report_date DATETIME NOT NULL, 
	date_range_start DATETIME, 
	date_range_end DATETIME, 
	pdf_download_count INTEGER, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(account_id) REFERENCES accounts (id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE INDEX IF NOT EXISTS `ix_facebook_ads_grader_reports_account_id` ON `facebook_ads_grader_reports` (`account_id`);
CREATE INDEX IF NOT EXISTS `ix_facebook_ads_grader_reports_fb_ad_account_id` ON `facebook_ads_grader_reports` (`fb_ad_account_id`);
CREATE INDEX IF NOT EXISTS `ix_facebook_ads_grader_reports_overall_score` ON `facebook_ads_grader_reports` (`overall_score`);
CREATE INDEX IF NOT EXISTS `ix_facebook_ads_grader_reports_user_id` ON `facebook_ads_grader_reports` (`user_id`);

-- Table: glsa_call_records
CREATE TABLE IF NOT EXISTS glsa_call_records (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	account_id BIGINT NOT NULL, 
	lead_id BIGINT NOT NULL, 
	storage_url VARCHAR(1024), 
	mime_type VARCHAR(128), 
	duration_sec INTEGER, 
	transcript TEXT, 
	outcome_label VARCHAR(64), 
	outcome_reason VARCHAR(255), 
	confidence NUMERIC(4, 3), 
	reviewed BOOL, 
	reviewer_notes TEXT, 
	created_at DATETIME, 
	updated_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(lead_id) REFERENCES glsa_leads (id) ON DELETE CASCADE
);

-- Table: google_ads_grader_reports
CREATE TABLE IF NOT EXISTS google_ads_grader_reports (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	account_id INTEGER, 
	user_id INTEGER, 
	google_ads_customer_id VARCHAR(20) NOT NULL, 
	google_ads_account_name VARCHAR(255), 
	overall_score FLOAT NOT NULL, 
	overall_grade VARCHAR(2), 
	quality_score_avg FLOAT, 
	ctr_avg FLOAT, 
	wasted_spend_90d FLOAT, 
	projected_waste_12m FLOAT, 
	active_campaigns INTEGER, 
	active_ad_groups INTEGER, 
	active_text_ads INTEGER, 
	active_keywords INTEGER, 
	clicks_90d INTEGER, 
	conversions_90d INTEGER, 
	avg_cpa_90d FLOAT, 
	avg_monthly_spend FLOAT, 
	wasted_spend_score FLOAT, 
	expanded_text_ads_score FLOAT, 
	text_ad_optimization_score FLOAT, 
	quality_score_optimization_score FLOAT, 
	ctr_optimization_score FLOAT, 
	account_activity_score FLOAT, 
	long_tail_keywords_score FLOAT, 
	impression_share_score FLOAT, 
	landing_page_score FLOAT, 
	mobile_advertising_score FLOAT, 
	detailed_metrics JSON, 
	best_practices JSON, 
	recommendations JSON, 
	report_date DATETIME NOT NULL DEFAULT (now()), 
	date_range_start DATETIME, 
	date_range_end DATETIME, 
	shareable_token VARCHAR(64), 
	pdf_generated BOOL NOT NULL DEFAULT '0', 
	pdf_download_count INTEGER NOT NULL DEFAULT '0', 
	created_at DATETIME NOT NULL DEFAULT (now()), 
	updated_at DATETIME NOT NULL DEFAULT (now()), 
	PRIMARY KEY (id), 
	FOREIGN KEY(account_id) REFERENCES accounts (id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE UNIQUE INDEX IF NOT EXISTS `ix_google_ads_grader_reports_shareable_token` ON `google_ads_grader_reports` (`shareable_token`);
CREATE INDEX IF NOT EXISTS `ix_google_ads_grader_reports_google_ads_customer_id` ON `google_ads_grader_reports` (`google_ads_customer_id`);
CREATE INDEX IF NOT EXISTS `ix_google_ads_grader_reports_user_id` ON `google_ads_grader_reports` (`user_id`);
CREATE INDEX IF NOT EXISTS `ix_google_ads_grader_reports_account_id` ON `google_ads_grader_reports` (`account_id`);

-- Table: keywords
CREATE TABLE IF NOT EXISTS keywords (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	ad_group_id INTEGER NOT NULL, 
	text VARCHAR(256) NOT NULL, 
	match_type VARCHAR(10) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	max_cpc_cents INTEGER, 
	google_keyword_id VARCHAR(64), 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_ads_adgroup_kw UNIQUE (ad_group_id, text, match_type), 
	FOREIGN KEY(ad_group_id) REFERENCES ad_groups (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS `ix_keywords_google_keyword_id` ON `keywords` (`google_keyword_id`);
CREATE INDEX IF NOT EXISTS `ix_keywords_ad_group_id` ON `keywords` (`ad_group_id`);

-- Table: linkedin_category_topics
CREATE TABLE IF NOT EXISTS linkedin_category_topics (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	category_id INTEGER NOT NULL, 
	topic_idea TEXT NOT NULL, 
	tone VARCHAR(50) DEFAULT 'professional', 
	used BOOL NOT NULL DEFAULT 'false', 
	used_date DATE, 
	post_id INTEGER, 
	created_at DATETIME NOT NULL DEFAULT (now()), 
	PRIMARY KEY (id), 
	FOREIGN KEY(category_id) REFERENCES linkedin_categories (id) ON DELETE CASCADE, 
	FOREIGN KEY(post_id) REFERENCES linkedin_scheduled_posts (id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS `ix_linkedin_category_topics_category_id` ON `linkedin_category_topics` (`category_id`);

-- Table: negative_keywords
CREATE TABLE IF NOT EXISTS negative_keywords (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	scope VARCHAR(16) NOT NULL, 
	campaign_id INTEGER, 
	ad_group_id INTEGER, 
	list_id BIGINT, 
	text VARCHAR(255) NOT NULL, 
	match_type VARCHAR(16) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(campaign_id) REFERENCES ads_campaigns (id), 
	FOREIGN KEY(ad_group_id) REFERENCES ad_groups (id), 
	FOREIGN KEY(list_id) REFERENCES shared_negative_lists (id)
);

CREATE INDEX IF NOT EXISTS `ix_negative_keywords_ad_group_id` ON `negative_keywords` (`ad_group_id`);
CREATE INDEX IF NOT EXISTS `ix_negative_keywords_list_id` ON `negative_keywords` (`list_id`);
CREATE INDEX IF NOT EXISTS `ix_negative_keywords_campaign_id` ON `negative_keywords` (`campaign_id`);

-- Table: page_views
CREATE TABLE IF NOT EXISTS page_views (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	session_id VARCHAR(64) NOT NULL, 
	user_id INTEGER, 
	path VARCHAR(512) NOT NULL, 
	page_title VARCHAR(255), 
	referrer VARCHAR(512), 
	query_string VARCHAR(512), 
	viewed_at DATETIME NOT NULL, 
	time_on_page INTEGER, 
	ip_address VARCHAR(45), 
	user_agent VARCHAR(512), 
	device_type VARCHAR(20), 
	browser VARCHAR(50), 
	utm_source VARCHAR(100), 
	utm_medium VARCHAR(100), 
	utm_campaign VARCHAR(100), 
	utm_term VARCHAR(100), 
	utm_content VARCHAR(100), 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE INDEX IF NOT EXISTS `ix_page_views_viewed_at` ON `page_views` (`viewed_at`);
CREATE INDEX IF NOT EXISTS `idx_page_views_session` ON `page_views` (`session_id`);
CREATE INDEX IF NOT EXISTS `ix_page_views_user_id` ON `page_views` (`user_id`);
CREATE INDEX IF NOT EXISTS `idx_page_views_user` ON `page_views` (`user_id`);
CREATE INDEX IF NOT EXISTS `idx_page_views_path` ON `page_views` (`path`);
CREATE INDEX IF NOT EXISTS `ix_page_views_session_id` ON `page_views` (`session_id`);
CREATE INDEX IF NOT EXISTS `idx_page_views_date` ON `page_views` (`viewed_at`);
CREATE INDEX IF NOT EXISTS `idx_page_views_session_date` ON `page_views` (`session_id`, `viewed_at`);
CREATE INDEX IF NOT EXISTS `ix_page_views_path` ON `page_views` (`path`);

-- Table: roi_settings
CREATE TABLE IF NOT EXISTS roi_settings (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	setting_key VARCHAR(64) NOT NULL, 
	setting_name VARCHAR(128) NOT NULL, 
	setting_value TEXT NOT NULL, 
	setting_type VARCHAR(32) NOT NULL, 
	description TEXT, 
	category VARCHAR(64), 
	updated_at DATETIME, 
	updated_by INTEGER, 
	PRIMARY KEY (id), 
	FOREIGN KEY(updated_by) REFERENCES users (id)
);

CREATE UNIQUE INDEX IF NOT EXISTS `ix_roi_settings_setting_key` ON `roi_settings` (`setting_key`);

-- Table: servicetitan_connections
CREATE TABLE IF NOT EXISTS servicetitan_connections (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	tenant_id VARCHAR(100) NOT NULL, 
	client_id VARCHAR(255) NOT NULL, 
	client_secret VARCHAR(255) NOT NULL, 
	access_token TEXT, 
	refresh_token TEXT, 
	token_expires_at DATETIME, 
	app_key VARCHAR(255), 
	is_active BOOL NOT NULL, 
	sync_enabled BOOL NOT NULL, 
	sync_frequency_hours INTEGER NOT NULL, 
	last_sync_at DATETIME, 
	next_sync_at DATETIME, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	created_by_user_id INTEGER, 
	PRIMARY KEY (id), 
	FOREIGN KEY(account_id) REFERENCES accounts (id), 
	FOREIGN KEY(created_by_user_id) REFERENCES users (id)
);

CREATE UNIQUE INDEX IF NOT EXISTS `ix_servicetitan_connections_account_id` ON `servicetitan_connections` (`account_id`);

-- Table: team_invites
CREATE TABLE IF NOT EXISTS team_invites (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	email VARCHAR(255) NOT NULL, 
	`role` VARCHAR(32) NOT NULL DEFAULT 'member', 
	invited_by_user_id INTEGER NOT NULL, 
	token VARCHAR(64) NOT NULL, 
	status VARCHAR(32) NOT NULL DEFAULT 'pending', 
	created_at DATETIME NOT NULL DEFAULT (now()), 
	expires_at DATETIME NOT NULL, 
	accepted_at DATETIME, 
	revoked_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(account_id) REFERENCES accounts (id), 
	FOREIGN KEY(invited_by_user_id) REFERENCES users (id)
);

CREATE INDEX IF NOT EXISTS `ix_team_invites_account_id` ON `team_invites` (`account_id`);
CREATE INDEX IF NOT EXISTS `ix_team_invites_status` ON `team_invites` (`status`);
CREATE UNIQUE INDEX IF NOT EXISTS `ix_team_invites_token` ON `team_invites` (`token`);
CREATE INDEX IF NOT EXISTS `ix_team_invites_email` ON `team_invites` (`email`);

-- Table: team_members
CREATE TABLE IF NOT EXISTS team_members (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	custom_permissions JSON, 
	joined_at DATETIME NOT NULL DEFAULT (now()), 
	last_active_at DATETIME, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_account_user UNIQUE (account_id, user_id), 
	FOREIGN KEY(account_id) REFERENCES accounts (id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE INDEX IF NOT EXISTS `ix_team_members_account_id` ON `team_members` (`account_id`);
CREATE INDEX IF NOT EXISTS `ix_team_members_user_id` ON `team_members` (`user_id`);

-- Table: tutorial_user_progress
CREATE TABLE IF NOT EXISTS tutorial_user_progress (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	user_id INTEGER NOT NULL, 
	popup_id INTEGER NOT NULL, 
	viewed_at DATETIME NOT NULL DEFAULT (now()), 
	dismissed_at DATETIME, 
	dismissed_action VARCHAR(50), 
	view_count INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id), 
	FOREIGN KEY(popup_id) REFERENCES tutorial_popups (id)
);

CREATE INDEX IF NOT EXISTS `ix_tutorial_user_progress_user_id` ON `tutorial_user_progress` (`user_id`);
CREATE INDEX IF NOT EXISTS `ix_tutorial_user_progress_popup_id` ON `tutorial_user_progress` (`popup_id`);
CREATE UNIQUE INDEX IF NOT EXISTS `ix_tutorial_user_popup` ON `tutorial_user_progress` (`user_id`, `popup_id`);

-- Table: user_oauth_providers
CREATE TABLE IF NOT EXISTS user_oauth_providers (
	id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
	user_id INTEGER NOT NULL, 
	provider VARCHAR(32) NOT NULL, 
	provider_user_id VARCHAR(255) NOT NULL, 
	email VARCHAR(255), 
	name VARCHAR(255), 
	picture VARCHAR(512), 
	access_token TEXT, 
	refresh_token TEXT, 
	token_expires_at DATETIME, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	last_login_at DATETIME, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_user_provider UNIQUE (user_id, provider), 
	CONSTRAINT uq_provider_user_id UNIQUE (provider, provider_user_id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE INDEX IF NOT EXISTS `ix_user_oauth_providers_provider` ON `user_oauth_providers` (`provider`);
CREATE INDEX IF NOT EXISTS `ix_user_oauth_providers_user_id` ON `user_oauth_providers` (`user_id`);

-- Table: wp_logs
CREATE TABLE IF NOT EXISTS wp_logs (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	site_id INTEGER NOT NULL, 
	job_id INTEGER, 
	level VARCHAR(16) NOT NULL, 
	message TEXT NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(site_id) REFERENCES wp_sites (id), 
	FOREIGN KEY(job_id) REFERENCES wp_jobs (id)
);

-- Table: ad_analytics_events
CREATE TABLE IF NOT EXISTS ad_analytics_events (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	user_id INTEGER, 
	account_id INTEGER, 
	creative_id INTEGER, 
	event_type ENUM('ad_generated','creative_saved','image_downloaded','creative_exported','creative_viewed','creative_edited','variation_created') NOT NULL, 
	platform VARCHAR(50), 
	industry VARCHAR(100), 
	generation_method VARCHAR(50), 
	image_count INTEGER, 
	ai_cost FLOAT, 
	predicted_ctr FLOAT, 
	quality_score INTEGER, 
	engagement_score INTEGER, 
	event_data JSON, 
	session_id VARCHAR(255), 
	created_at DATETIME NOT NULL DEFAULT (now()), 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id), 
	FOREIGN KEY(account_id) REFERENCES accounts (id), 
	FOREIGN KEY(creative_id) REFERENCES ad_creatives (id)
);

CREATE INDEX IF NOT EXISTS `ix_ad_analytics_events_created_at` ON `ad_analytics_events` (`created_at`);
CREATE INDEX IF NOT EXISTS `ix_ad_analytics_events_session_id` ON `ad_analytics_events` (`session_id`);
CREATE INDEX IF NOT EXISTS `ix_ad_analytics_events_creative_id` ON `ad_analytics_events` (`creative_id`);
CREATE INDEX IF NOT EXISTS `ix_ad_analytics_events_account_id` ON `ad_analytics_events` (`account_id`);
CREATE INDEX IF NOT EXISTS `ix_ad_analytics_events_event_type` ON `ad_analytics_events` (`event_type`);
CREATE INDEX IF NOT EXISTS `ix_ad_analytics_events_user_id` ON `ad_analytics_events` (`user_id`);

-- Table: ad_creative_variations
CREATE TABLE IF NOT EXISTS ad_creative_variations (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	parent_creative_id INTEGER NOT NULL, 
	variation_type ENUM('headline','image','copy','cta','full') NOT NULL, 
	headline VARCHAR(255), 
	primary_text TEXT, 
	description VARCHAR(500), 
	call_to_action VARCHAR(100), 
	image_url VARCHAR(1000), 
	impressions INTEGER, 
	clicks INTEGER, 
	conversions INTEGER, 
	is_winner BOOL, 
	created_at DATETIME NOT NULL DEFAULT (now()), 
	PRIMARY KEY (id), 
	FOREIGN KEY(parent_creative_id) REFERENCES ad_creatives (id)
);

CREATE INDEX IF NOT EXISTS `ix_ad_creative_variations_parent_creative_id` ON `ad_creative_variations` (`parent_creative_id`);

-- Table: ad_generation_jobs
CREATE TABLE IF NOT EXISTS ad_generation_jobs (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	user_id INTEGER NOT NULL, 
	job_type ENUM('website_scan','image_generation','copy_generation','full_creative') NOT NULL, 
	input_data JSON, 
	creative_id INTEGER, 
	output_data JSON, 
	status ENUM('pending','processing','completed','failed') NOT NULL, 
	error_message TEXT, 
	created_at DATETIME NOT NULL DEFAULT (now()), 
	completed_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id), 
	FOREIGN KEY(creative_id) REFERENCES ad_creatives (id)
);

CREATE INDEX IF NOT EXISTS `ix_ad_generation_jobs_creative_id` ON `ad_generation_jobs` (`creative_id`);
CREATE INDEX IF NOT EXISTS `ix_ad_generation_jobs_user_id` ON `ad_generation_jobs` (`user_id`);

-- Table: agent_knowledge_cache
CREATE TABLE IF NOT EXISTS agent_knowledge_cache (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	agent_type VARCHAR(64) NOT NULL, 
	source_id INTEGER, 
	summary TEXT NOT NULL, 
	key_insights JSON, 
	refreshed_at DATETIME, 
	token_count INTEGER, 
	PRIMARY KEY (id), 
	FOREIGN KEY(source_id) REFERENCES agent_knowledge_sources (id)
);

CREATE INDEX IF NOT EXISTS `ix_agent_knowledge_cache_agent_type` ON `agent_knowledge_cache` (`agent_type`);

-- Table: budget_alerts
CREATE TABLE IF NOT EXISTS budget_alerts (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	budget_tracker_id INTEGER NOT NULL, 
	alert_type ENUM('threshold_reached','overspend','underspend','pacing_ahead','pacing_behind','budget_depleted') NOT NULL, 
	alert_message TEXT NOT NULL, 
	severity ENUM('info','warning','critical') NOT NULL, 
	spend_amount INTEGER NOT NULL, 
	budget_amount INTEGER NOT NULL, 
	spend_percentage FLOAT NOT NULL, 
	sent_at DATETIME NOT NULL, 
	acknowledged BOOL NOT NULL, 
	acknowledged_at DATETIME, 
	acknowledged_by_user_id INTEGER, 
	PRIMARY KEY (id), 
	FOREIGN KEY(budget_tracker_id) REFERENCES budget_trackers (id), 
	FOREIGN KEY(acknowledged_by_user_id) REFERENCES users (id)
);

CREATE INDEX IF NOT EXISTS `idx_budget_alerts_tracker` ON `budget_alerts` (`budget_tracker_id`);
CREATE INDEX IF NOT EXISTS `ix_budget_alerts_sent_at` ON `budget_alerts` (`sent_at`);
CREATE INDEX IF NOT EXISTS `idx_budget_alerts_type` ON `budget_alerts` (`alert_type`);
CREATE INDEX IF NOT EXISTS `ix_budget_alerts_budget_tracker_id` ON `budget_alerts` (`budget_tracker_id`);
CREATE INDEX IF NOT EXISTS `idx_budget_alerts_sent` ON `budget_alerts` (`sent_at`);
CREATE INDEX IF NOT EXISTS `idx_budget_alerts_ack` ON `budget_alerts` (`acknowledged`);
CREATE INDEX IF NOT EXISTS `ix_budget_alerts_alert_type` ON `budget_alerts` (`alert_type`);

-- Table: company_contacts
CREATE TABLE IF NOT EXISTS company_contacts (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	crm_contact_id INTEGER NOT NULL, 
	full_name VARCHAR(255) NOT NULL, 
	title VARCHAR(255), 
	email VARCHAR(255), 
	phone VARCHAR(64), 
	linkedin_url VARCHAR(512), 
	role_category VARCHAR(50), 
	source VARCHAR(128), 
	discovered_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(crm_contact_id) REFERENCES crm_contacts (id)
);

CREATE INDEX IF NOT EXISTS `idx_company_contacts_email` ON `company_contacts` (`email`);
CREATE INDEX IF NOT EXISTS `idx_company_contacts_role` ON `company_contacts` (`role_category`);
CREATE INDEX IF NOT EXISTS `ix_company_contacts_crm_contact_id` ON `company_contacts` (`crm_contact_id`);
CREATE INDEX IF NOT EXISTS `idx_company_contacts_crm` ON `company_contacts` (`crm_contact_id`);

-- Table: contact_group_members
CREATE TABLE IF NOT EXISTS contact_group_members (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	contact_id INTEGER NOT NULL, 
	group_id INTEGER NOT NULL, 
	added_at DATETIME NOT NULL, 
	added_by_user_id INTEGER, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_contact_group UNIQUE (contact_id, group_id), 
	FOREIGN KEY(contact_id) REFERENCES crm_contacts (id), 
	FOREIGN KEY(group_id) REFERENCES contact_groups (id), 
	FOREIGN KEY(added_by_user_id) REFERENCES users (id)
);

CREATE INDEX IF NOT EXISTS `idx_contact_group_members_contact` ON `contact_group_members` (`contact_id`);
CREATE INDEX IF NOT EXISTS `ix_contact_group_members_contact_id` ON `contact_group_members` (`contact_id`);
CREATE INDEX IF NOT EXISTS `idx_contact_group_members_group` ON `contact_group_members` (`group_id`);
CREATE INDEX IF NOT EXISTS `ix_contact_group_members_group_id` ON `contact_group_members` (`group_id`);

-- Table: emails_sent
CREATE TABLE IF NOT EXISTS emails_sent (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	crm_contact_id INTEGER NOT NULL, 
	sent_by_user_id INTEGER, 
	subject VARCHAR(500) NOT NULL, 
	body_html LONGTEXT, 
	body_text TEXT, 
	tracking_token VARCHAR(64) NOT NULL, 
	campaign_name VARCHAR(255), 
	sent_at DATETIME NOT NULL, 
	delivered BOOL NOT NULL, 
	bounced BOOL NOT NULL, 
	bounced_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(crm_contact_id) REFERENCES crm_contacts (id), 
	FOREIGN KEY(sent_by_user_id) REFERENCES users (id)
);

CREATE INDEX IF NOT EXISTS `ix_emails_sent_campaign_name` ON `emails_sent` (`campaign_name`);
CREATE INDEX IF NOT EXISTS `ix_emails_sent_crm_contact_id` ON `emails_sent` (`crm_contact_id`);
CREATE INDEX IF NOT EXISTS `idx_emails_sent_user` ON `emails_sent` (`sent_by_user_id`);
CREATE INDEX IF NOT EXISTS `idx_emails_sent_token` ON `emails_sent` (`tracking_token`);
CREATE INDEX IF NOT EXISTS `idx_emails_sent_campaign` ON `emails_sent` (`campaign_name`);
CREATE INDEX IF NOT EXISTS `idx_emails_sent_contact` ON `emails_sent` (`crm_contact_id`);
CREATE INDEX IF NOT EXISTS `idx_emails_sent_date` ON `emails_sent` (`sent_at`);
CREATE UNIQUE INDEX IF NOT EXISTS `ix_emails_sent_tracking_token` ON `emails_sent` (`tracking_token`);
CREATE INDEX IF NOT EXISTS `ix_emails_sent_sent_by_user_id` ON `emails_sent` (`sent_by_user_id`);

-- Table: leads
CREATE TABLE IF NOT EXISTS leads (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	campaign_id INTEGER NOT NULL, 
	crm_contact_id INTEGER, 
	company_name VARCHAR(255) NOT NULL, 
	website VARCHAR(500), 
	phone VARCHAR(50), 
	address VARCHAR(500), 
	source_type ENUM('ad','map','lsa','organic') NOT NULL, 
	source_url VARCHAR(1000), 
	serp_position INTEGER, 
	email_format VARCHAR(100), 
	decision_maker_name VARCHAR(200), 
	decision_maker_title VARCHAR(100), 
	decision_maker_email VARCHAR(255), 
	decision_maker_linkedin VARCHAR(500), 
	enrichment_status ENUM('pending','in_progress','completed','failed') NOT NULL, 
	enrichment_attempts INTEGER, 
	enriched_at DATETIME, 
	email_status ENUM('pending','sending','sent','opened','replied','bounced','unsubscribed') NOT NULL, 
	current_sequence_step INTEGER, 
	last_email_sent_at DATETIME, 
	first_opened_at DATETIME, 
	replied_at DATETIME, 
	unsubscribed_at DATETIME, 
	auto_delete_at DATETIME, 
	extra_data JSON, 
	created_at DATETIME NOT NULL DEFAULT (now()), 
	updated_at DATETIME NOT NULL DEFAULT (now()), 
	PRIMARY KEY (id), 
	FOREIGN KEY(campaign_id) REFERENCES lead_campaigns (id), 
	FOREIGN KEY(crm_contact_id) REFERENCES crm_contacts (id)
);

CREATE INDEX IF NOT EXISTS `ix_leads_crm_contact_id` ON `leads` (`crm_contact_id`);
CREATE INDEX IF NOT EXISTS `ix_leads_campaign_id` ON `leads` (`campaign_id`);
CREATE INDEX IF NOT EXISTS `ix_leads_email_status` ON `leads` (`email_status`);
CREATE INDEX IF NOT EXISTS `ix_leads_decision_maker_email` ON `leads` (`decision_maker_email`);

-- Table: rsa_assets
CREATE TABLE IF NOT EXISTS rsa_assets (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	account_id INTEGER NOT NULL, 
	ad_id INTEGER, 
	google_ad_id VARCHAR(64), 
	asset_type VARCHAR(16) NOT NULL, 
	asset_text VARCHAR(255) NOT NULL, 
	pinned_field VARCHAR(32), 
	performance_label VARCHAR(32), 
	impressions BIGINT NOT NULL, 
	clicks BIGINT NOT NULL, 
	conversions FLOAT NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_rsa_asset UNIQUE (google_ad_id, asset_type, asset_text), 
	FOREIGN KEY(ad_id) REFERENCES ads (id)
);

CREATE INDEX IF NOT EXISTS `ix_rsa_assets_ad_id` ON `rsa_assets` (`ad_id`);
CREATE INDEX IF NOT EXISTS `ix_rsa_assets_account_id` ON `rsa_assets` (`account_id`);
CREATE INDEX IF NOT EXISTS `ix_rsa_assets_google_ad_id` ON `rsa_assets` (`google_ad_id`);

-- Table: search_terms
CREATE TABLE IF NOT EXISTS search_terms (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	campaign_id INTEGER, 
	ad_group_id INTEGER, 
	keyword_id INTEGER, 
	search_term VARCHAR(512) NOT NULL, 
	clicks BIGINT NOT NULL, 
	impressions BIGINT NOT NULL, 
	cost_micros BIGINT NOT NULL, 
	conversions FLOAT NOT NULL, 
	added_as_keyword BOOL NOT NULL, 
	added_as_negative BOOL NOT NULL, 
	date DATE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(campaign_id) REFERENCES ads_campaigns (id), 
	FOREIGN KEY(ad_group_id) REFERENCES ad_groups (id), 
	FOREIGN KEY(keyword_id) REFERENCES keywords (id)
);

CREATE INDEX IF NOT EXISTS `ix_search_terms_search_term` ON `search_terms` (`search_term`);
CREATE INDEX IF NOT EXISTS `ix_search_terms_campaign_id` ON `search_terms` (`campaign_id`);
CREATE INDEX IF NOT EXISTS `ix_search_terms_keyword_id` ON `search_terms` (`keyword_id`);
CREATE INDEX IF NOT EXISTS `ix_search_terms_ad_group_id` ON `search_terms` (`ad_group_id`);

-- Table: workflow_steps
CREATE TABLE IF NOT EXISTS workflow_steps (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	workflow_id INTEGER NOT NULL, 
	email_template_id INTEGER NOT NULL, 
	step_order INTEGER NOT NULL, 
	delay_days INTEGER NOT NULL, 
	delay_hours INTEGER NOT NULL, 
	condition_type ENUM('none','email_opened','email_not_opened','link_clicked') NOT NULL, 
	condition_wait_hours INTEGER NOT NULL, 
	alt_email_template_id INTEGER, 
	condition_data JSON, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_workflow_step_order UNIQUE (workflow_id, step_order), 
	FOREIGN KEY(workflow_id) REFERENCES email_workflows (id), 
	FOREIGN KEY(email_template_id) REFERENCES email_templates (id), 
	FOREIGN KEY(alt_email_template_id) REFERENCES email_templates (id)
);

CREATE INDEX IF NOT EXISTS `ix_workflow_steps_condition_type` ON `workflow_steps` (`condition_type`);
CREATE INDEX IF NOT EXISTS `idx_workflow_steps_order` ON `workflow_steps` (`workflow_id`, `step_order`);
CREATE INDEX IF NOT EXISTS `idx_workflow_steps_workflow` ON `workflow_steps` (`workflow_id`);
CREATE INDEX IF NOT EXISTS `ix_workflow_steps_workflow_id` ON `workflow_steps` (`workflow_id`);
CREATE INDEX IF NOT EXISTS `ix_workflow_steps_email_template_id` ON `workflow_steps` (`email_template_id`);

-- Table: email_clicks
CREATE TABLE IF NOT EXISTS email_clicks (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	email_sent_id INTEGER NOT NULL, 
	clicked_at DATETIME NOT NULL, 
	url VARCHAR(2048) NOT NULL, 
	ip_address VARCHAR(45), 
	user_agent VARCHAR(512), 
	PRIMARY KEY (id), 
	FOREIGN KEY(email_sent_id) REFERENCES emails_sent (id)
);

CREATE INDEX IF NOT EXISTS `idx_email_clicks_date` ON `email_clicks` (`clicked_at`);
CREATE INDEX IF NOT EXISTS `ix_email_clicks_email_sent_id` ON `email_clicks` (`email_sent_id`);
CREATE INDEX IF NOT EXISTS `idx_email_clicks_email` ON `email_clicks` (`email_sent_id`);

-- Table: email_opens
CREATE TABLE IF NOT EXISTS email_opens (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	email_sent_id INTEGER NOT NULL, 
	opened_at DATETIME NOT NULL, 
	ip_address VARCHAR(45), 
	user_agent VARCHAR(512), 
	PRIMARY KEY (id), 
	FOREIGN KEY(email_sent_id) REFERENCES emails_sent (id)
);

CREATE INDEX IF NOT EXISTS `ix_email_opens_email_sent_id` ON `email_opens` (`email_sent_id`);
CREATE INDEX IF NOT EXISTS `idx_email_opens_date` ON `email_opens` (`opened_at`);
CREATE INDEX IF NOT EXISTS `idx_email_opens_email` ON `email_opens` (`email_sent_id`);

-- Table: lead_contacts
CREATE TABLE IF NOT EXISTS lead_contacts (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	lead_id INTEGER NOT NULL, 
	company_contact_id INTEGER, 
	name VARCHAR(200) NOT NULL, 
	title VARCHAR(100), 
	email VARCHAR(255), 
	linkedin_url VARCHAR(500), 
	role_category ENUM('executive','owner','marketing','operations','sales','other') NOT NULL, 
	is_primary BOOL, 
	email_status ENUM('pending','sending','sent','opened','replied','bounced','unsubscribed') NOT NULL, 
	current_sequence_step INTEGER, 
	last_email_sent_at DATETIME, 
	first_opened_at DATETIME, 
	replied_at DATETIME, 
	unsubscribed_at DATETIME, 
	created_at DATETIME NOT NULL DEFAULT (now()), 
	updated_at DATETIME NOT NULL DEFAULT (now()), 
	PRIMARY KEY (id), 
	FOREIGN KEY(lead_id) REFERENCES leads (id), 
	FOREIGN KEY(company_contact_id) REFERENCES company_contacts (id)
);

CREATE INDEX IF NOT EXISTS `ix_lead_contacts_lead_id` ON `lead_contacts` (`lead_id`);
CREATE INDEX IF NOT EXISTS `ix_lead_contacts_email_status` ON `lead_contacts` (`email_status`);
CREATE INDEX IF NOT EXISTS `ix_lead_contacts_email` ON `lead_contacts` (`email`);
CREATE INDEX IF NOT EXISTS `ix_lead_contacts_company_contact_id` ON `lead_contacts` (`company_contact_id`);

-- Table: lead_emails_sent
CREATE TABLE IF NOT EXISTS lead_emails_sent (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	lead_id INTEGER NOT NULL, 
	sequence_id INTEGER NOT NULL, 
	to_email VARCHAR(255) NOT NULL, 
	subject VARCHAR(500) NOT NULL, 
	body_html TEXT, 
	body_text TEXT, 
	mailgun_message_id VARCHAR(255), 
	status ENUM('queued','sent','delivered','opened','clicked','bounced','failed','complained') NOT NULL, 
	sent_at DATETIME, 
	delivered_at DATETIME, 
	opened_at DATETIME, 
	clicked_at DATETIME, 
	bounced_at DATETIME, 
	complained_at DATETIME, 
	error_message TEXT, 
	created_at DATETIME NOT NULL DEFAULT (now()), 
	updated_at DATETIME NOT NULL DEFAULT (now()), 
	PRIMARY KEY (id), 
	FOREIGN KEY(lead_id) REFERENCES leads (id), 
	FOREIGN KEY(sequence_id) REFERENCES email_sequences (id)
);

CREATE INDEX IF NOT EXISTS `ix_lead_emails_sent_to_email` ON `lead_emails_sent` (`to_email`);
CREATE INDEX IF NOT EXISTS `ix_lead_emails_sent_status` ON `lead_emails_sent` (`status`);
CREATE INDEX IF NOT EXISTS `ix_lead_emails_sent_lead_id` ON `lead_emails_sent` (`lead_id`);
CREATE UNIQUE INDEX IF NOT EXISTS `ix_lead_emails_sent_mailgun_message_id` ON `lead_emails_sent` (`mailgun_message_id`);
CREATE INDEX IF NOT EXISTS `ix_lead_emails_sent_sequence_id` ON `lead_emails_sent` (`sequence_id`);

-- Table: workflow_enrollments
CREATE TABLE IF NOT EXISTS workflow_enrollments (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	workflow_id INTEGER NOT NULL, 
	crm_contact_id INTEGER NOT NULL, 
	current_step INTEGER NOT NULL, 
	status ENUM('active','paused','completed','unsubscribed','bounced') NOT NULL, 
	enrolled_at DATETIME NOT NULL, 
	last_email_sent_at DATETIME, 
	next_email_scheduled_at DATETIME, 
	step_history JSON, 
	completed_at DATETIME, 
	last_email_sent_id INTEGER, 
	enrolled_by_user_id INTEGER, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_workflow_enrollment UNIQUE (workflow_id, crm_contact_id), 
	FOREIGN KEY(workflow_id) REFERENCES email_workflows (id), 
	FOREIGN KEY(crm_contact_id) REFERENCES crm_contacts (id), 
	FOREIGN KEY(last_email_sent_id) REFERENCES emails_sent (id), 
	FOREIGN KEY(enrolled_by_user_id) REFERENCES users (id)
);

CREATE INDEX IF NOT EXISTS `ix_workflow_enrollments_next_email_scheduled_at` ON `workflow_enrollments` (`next_email_scheduled_at`);
CREATE INDEX IF NOT EXISTS `idx_workflow_enrollments_next_send` ON `workflow_enrollments` (`next_email_scheduled_at`);
CREATE INDEX IF NOT EXISTS `idx_workflow_enrollments_contact` ON `workflow_enrollments` (`crm_contact_id`);
CREATE INDEX IF NOT EXISTS `ix_workflow_enrollments_last_email_sent_id` ON `workflow_enrollments` (`last_email_sent_id`);
CREATE INDEX IF NOT EXISTS `ix_workflow_enrollments_crm_contact_id` ON `workflow_enrollments` (`crm_contact_id`);
CREATE INDEX IF NOT EXISTS `ix_workflow_enrollments_status` ON `workflow_enrollments` (`status`);
CREATE INDEX IF NOT EXISTS `idx_workflow_enrollments_workflow` ON `workflow_enrollments` (`workflow_id`);
CREATE INDEX IF NOT EXISTS `ix_workflow_enrollments_enrolled_at` ON `workflow_enrollments` (`enrolled_at`);
CREATE INDEX IF NOT EXISTS `ix_workflow_enrollments_workflow_id` ON `workflow_enrollments` (`workflow_id`);
CREATE INDEX IF NOT EXISTS `idx_workflow_enrollments_status` ON `workflow_enrollments` (`status`);

-- Table: email_conversations
CREATE TABLE IF NOT EXISTS email_conversations (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	lead_contact_id INTEGER NOT NULL, 
	thread_id VARCHAR(255), 
	subject VARCHAR(500), 
	status VARCHAR(50), 
	ai_handled BOOL, 
	requires_human BOOL, 
	total_messages INTEGER, 
	ai_messages INTEGER, 
	human_messages INTEGER, 
	prospect_messages INTEGER, 
	last_sentiment VARCHAR(50), 
	lead_score INTEGER, 
	last_message_at DATETIME NOT NULL, 
	last_prospect_reply_at DATETIME, 
	last_ai_reply_at DATETIME, 
	escalated_at DATETIME, 
	created_at DATETIME NOT NULL DEFAULT (now()), 
	PRIMARY KEY (id), 
	FOREIGN KEY(lead_contact_id) REFERENCES lead_contacts (id)
);

CREATE UNIQUE INDEX IF NOT EXISTS `ix_email_conversations_thread_id` ON `email_conversations` (`thread_id`);

-- Table: lead_contact_emails
CREATE TABLE IF NOT EXISTS lead_contact_emails (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	contact_id INTEGER NOT NULL, 
	lead_id INTEGER NOT NULL, 
	campaign_id INTEGER NOT NULL, 
	sequence_step INTEGER NOT NULL, 
	subject VARCHAR(500) NOT NULL, 
	body TEXT, 
	to_email VARCHAR(255), 
	email_provider VARCHAR(50), 
	mailgun_message_id VARCHAR(255), 
	brevo_message_id VARCHAR(255), 
	status ENUM('queued','sent','delivered','opened','clicked','bounced','failed') NOT NULL, 
	sent_at DATETIME, 
	delivered_at DATETIME, 
	opened_at DATETIME, 
	clicked_at DATETIME, 
	bounced_at DATETIME, 
	error_message TEXT, 
	created_at DATETIME NOT NULL DEFAULT (now()), 
	updated_at DATETIME NOT NULL DEFAULT (now()), 
	PRIMARY KEY (id), 
	CONSTRAINT uq_lead_contact_emails_contact_step UNIQUE (contact_id, sequence_step), 
	FOREIGN KEY(contact_id) REFERENCES lead_contacts (id), 
	FOREIGN KEY(lead_id) REFERENCES leads (id), 
	FOREIGN KEY(campaign_id) REFERENCES lead_campaigns (id)
);

CREATE INDEX IF NOT EXISTS `ix_lead_contact_emails_brevo_message_id` ON `lead_contact_emails` (`brevo_message_id`);
CREATE INDEX IF NOT EXISTS `ix_lead_contact_emails_lead_id` ON `lead_contact_emails` (`lead_id`);
CREATE INDEX IF NOT EXISTS `ix_lead_contact_emails_campaign_id` ON `lead_contact_emails` (`campaign_id`);
CREATE UNIQUE INDEX IF NOT EXISTS `ix_lead_contact_emails_mailgun_message_id` ON `lead_contact_emails` (`mailgun_message_id`);
CREATE INDEX IF NOT EXISTS `ix_lead_contact_emails_status` ON `lead_contact_emails` (`status`);
CREATE INDEX IF NOT EXISTS `ix_lead_contact_emails_contact_id` ON `lead_contact_emails` (`contact_id`);

-- Table: conversation_alerts
CREATE TABLE IF NOT EXISTS conversation_alerts (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	conversation_id INTEGER NOT NULL, 
	alert_type VARCHAR(50) NOT NULL, 
	message TEXT, 
	severity VARCHAR(50), 
	is_read BOOL, 
	read_at DATETIME, 
	dismissed BOOL, 
	dismissed_at DATETIME, 
	created_at DATETIME NOT NULL DEFAULT (now()), 
	PRIMARY KEY (id), 
	FOREIGN KEY(conversation_id) REFERENCES email_conversations (id)
);

CREATE INDEX IF NOT EXISTS `ix_conversation_alerts_created_at` ON `conversation_alerts` (`created_at`);
CREATE INDEX IF NOT EXISTS `ix_conversation_alerts_is_read` ON `conversation_alerts` (`is_read`);

-- Table: email_conversation_messages
CREATE TABLE IF NOT EXISTS email_conversation_messages (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	conversation_id INTEGER NOT NULL, 
	direction VARCHAR(50) NOT NULL, 
	from_email VARCHAR(255) NOT NULL, 
	to_email VARCHAR(255) NOT NULL, 
	subject TEXT, 
	body_text TEXT, 
	body_html TEXT, 
	is_ai_generated BOOL, 
	ai_model VARCHAR(100), 
	ai_prompt_used TEXT, 
	ai_confidence NUMERIC(3, 2), 
	message_id VARCHAR(255), 
	in_reply_to VARCHAR(255), 
	`references` TEXT, 
	sentiment VARCHAR(50), 
	contains_question BOOL, 
	urgency_level VARCHAR(50), 
	received_at DATETIME, 
	sent_at DATETIME, 
	created_at DATETIME NOT NULL DEFAULT (now()), 
	PRIMARY KEY (id), 
	FOREIGN KEY(conversation_id) REFERENCES email_conversations (id)
);

CREATE INDEX IF NOT EXISTS `ix_email_conversation_messages_message_id` ON `email_conversation_messages` (`message_id`);


-- =============================================================
-- Migration-only tables (not defined in ORM models)
-- =============================================================

-- Table: zip_boundaries
CREATE TABLE IF NOT EXISTS `zip_boundaries` (
    `id` INT NOT NULL AUTO_INCREMENT,
    `zip` VARCHAR(16) DEFAULT NULL,
    `centroid_lat` FLOAT DEFAULT NULL,
    `centroid_lng` FLOAT DEFAULT NULL,
    `polygon_geojson` TEXT,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uq_zip_boundaries_zip` (`zip`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE INDEX IF NOT EXISTS `ix_zip_boundaries_zip` ON `zip_boundaries` (`zip`);

-- ===== Billboard Tables =====
CREATE TABLE IF NOT EXISTS billboard_locations (
  id INT PRIMARY KEY AUTO_INCREMENT,
  name VARCHAR(200) NOT NULL,
  address_area VARCHAR(200),
  city VARCHAR(100) NOT NULL,
  state VARCHAR(2) NOT NULL,
  zip VARCHAR(10),
  lat DECIMAL(10,7) NOT NULL,
  lng DECIMAL(10,7) NOT NULL,
  screen_type ENUM('digital_billboard','static_billboard','street_level','transit','wallscape') NOT NULL DEFAULT 'digital_billboard',
  size VARCHAR(30) NOT NULL DEFAULT '14x48',
  faces INT NOT NULL DEFAULT 1,
  facing VARCHAR(10),
  traffic_daily INT NOT NULL DEFAULT 20000,
  impressions_weekly INT NOT NULL DEFAULT 50000,
  cpp DECIMAL(8,4) NOT NULL DEFAULT 1.00,
  plays_per_day INT NOT NULL DEFAULT 480,
  dma VARCHAR(100),
  illuminated TINYINT(1) DEFAULT 1,
  image_placeholder VARCHAR(10),
  active TINYINT(1) NOT NULL DEFAULT 1,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS billboard_campaigns (
  id INT PRIMARY KEY AUTO_INCREMENT,
  account_id INT NOT NULL,
  name VARCHAR(200) NOT NULL,
  objective ENUM('awareness','traffic','leads') NOT NULL DEFAULT 'awareness',
  status ENUM('draft','pending_review','active','paused','completed','cancelled') NOT NULL DEFAULT 'draft',
  start_date DATE,
  end_date DATE,
  total_budget DECIMAL(10,2) NOT NULL DEFAULT 0,
  spent DECIMAL(10,2) NOT NULL DEFAULT 0,
  plays_delivered INT NOT NULL DEFAULT 0,
  impressions_delivered INT NOT NULL DEFAULT 0,
  creative_headline VARCHAR(100),
  creative_subtext VARCHAR(200),
  creative_cta VARCHAR(60),
  creative_type ENUM('ai_generated','uploaded') DEFAULT 'ai_generated',
  notes TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS billboard_campaign_locations (
  id INT PRIMARY KEY AUTO_INCREMENT,
  campaign_id INT NOT NULL,
  location_id INT NOT NULL,
  plays_per_day INT NOT NULL DEFAULT 480,
  cpp DECIMAL(8,4) NOT NULL,
  campaign_days INT NOT NULL DEFAULT 30,
  estimated_total_plays INT NOT NULL DEFAULT 0,
  estimated_impressions INT NOT NULL DEFAULT 0,
  estimated_cost DECIMAL(10,2) NOT NULL DEFAULT 0,
  FOREIGN KEY (campaign_id) REFERENCES billboard_campaigns(id) ON DELETE CASCADE,
  FOREIGN KEY (location_id) REFERENCES billboard_locations(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ===== Auto Budget & Competitive Tables =====
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

-- ===== Budget Forecasting Tables =====
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

-- ===== Campaign Budget Group Tables =====
CREATE TABLE IF NOT EXISTS campaign_budget_groups (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- Account association
    account_id BIGINT NOT NULL,

    -- Group details
    name VARCHAR(100) NOT NULL,
    description TEXT DEFAULT NULL,

    -- Budget allocation
    monthly_budget_cents INT NOT NULL DEFAULT 0,  -- Total monthly budget for this group
    daily_budget_cents INT GENERATED ALWAYS AS (monthly_budget_cents / 30) STORED,  -- Auto-calculated

    -- Status and control
    status VARCHAR(20) NOT NULL DEFAULT 'active',  -- active, paused, archived
    priority INT DEFAULT 0,  -- For budget allocation priority (higher = first)

    -- Budget Guardian integration
    auto_pause_on_overspend BOOLEAN DEFAULT TRUE,  -- Pause campaigns when group budget exhausted
    alert_threshold_pct DECIMAL(3,2) DEFAULT 0.80,  -- Alert when 80% of budget spent

    -- Metadata
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_by INT DEFAULT NULL,

    -- Indexes
    INDEX idx_account (account_id),
    INDEX idx_status (status),
    INDEX idx_priority (priority),

    -- Foreign keys
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS campaign_budget_assignments (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- Campaign and group
    campaign_id BIGINT NOT NULL,
    budget_group_id INT NOT NULL,

    -- Assignment metadata
    assigned_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    assigned_by INT DEFAULT NULL,

    -- Indexes
    UNIQUE KEY unique_campaign_assignment (campaign_id),  -- Each campaign can only be in ONE group
    INDEX idx_budget_group (budget_group_id),

    -- Foreign keys
    FOREIGN KEY (campaign_id) REFERENCES ads_campaigns(id) ON DELETE CASCADE,
    FOREIGN KEY (budget_group_id) REFERENCES campaign_budget_groups(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS campaign_budget_group_spend (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- Group and time period
    budget_group_id INT NOT NULL,
    period_month DATE NOT NULL,  -- First day of the month (e.g., 2025-01-01)

    -- Spend tracking
    total_spend_cents INT DEFAULT 0,
    total_impressions BIGINT DEFAULT 0,
    total_clicks INT DEFAULT 0,
    total_conversions DECIMAL(10,2) DEFAULT 0,

    -- Budget status
    budget_status VARCHAR(20) DEFAULT 'active',  -- active, warning, exceeded, paused
    alert_sent_at DATETIME DEFAULT NULL,

    -- Metadata
    last_updated DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- Indexes
    UNIQUE KEY unique_group_month (budget_group_id, period_month),
    INDEX idx_period (period_month),
    INDEX idx_budget_status (budget_status),

    -- Foreign keys
    FOREIGN KEY (budget_group_id) REFERENCES campaign_budget_groups(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ===== Digest Safety Tables =====
CREATE TABLE IF NOT EXISTS digest_send_log (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    account_id      INT          NOT NULL,
    digest_date     DATE         NOT NULL,
    channel         VARCHAR(20)  NOT NULL DEFAULT 'sms',   -- sms | email | both
    recipient       VARCHAR(255) NOT NULL DEFAULT '',
    status          VARCHAR(32)  NOT NULL DEFAULT 'sent',
        -- sent | failed | blocked_idempotent | blocked_circuit |
        -- blocked_approval | blocked_cap | blocked_number_check
    blocked_reason  TEXT,
    confidence      DECIMAL(4,3),                          -- from render_digest_structured
    created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_digest_send (account_id, digest_date, channel)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS digest_circuit_breaker (
    account_id          INT         NOT NULL PRIMARY KEY,
    consecutive_failures INT        NOT NULL DEFAULT 0,
    tripped_at          DATETIME,                    -- NULL = closed (ok to send)
    cooldown_seconds    INT         NOT NULL DEFAULT 86400,  -- 24 h default
    updated_at          DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS digest_ai_spend (
    account_id      INT         NOT NULL,
    period          CHAR(7)     NOT NULL,   -- YYYY-MM
    spend_cents     INT         NOT NULL DEFAULT 0,
    cap_cents       INT         NOT NULL DEFAULT 500,  -- $5.00 default monthly cap
    updated_at      DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (account_id, period)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS digest_approval_queue (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    account_id      INT          NOT NULL,
    digest_date     DATE         NOT NULL,
    channel         VARCHAR(20)  NOT NULL DEFAULT 'sms',
    reason          VARCHAR(64)  NOT NULL,
        -- first_digest | low_confidence | money_change | number_check_failed
    status          VARCHAR(16)  NOT NULL DEFAULT 'pending',
        -- pending | approved | rejected | auto_expired
    structured_json MEDIUMTEXT,              -- JSON from render_digest_structured
    confidence      DECIMAL(4,3),
    created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at     DATETIME,
    resolved_by     INT,                     -- user_id of approver
    KEY ix_approval_account (account_id),
    KEY ix_approval_status  (status),
    UNIQUE KEY uq_approval (account_id, digest_date, channel, reason)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ===== ML / Analytics Tables =====
CREATE TABLE IF NOT EXISTS user_events (
    id BIGBIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    account_id INTEGER DEFAULT NULL,
    user_id INTEGER DEFAULT NULL,
    session_fingerprint VARCHAR(64) DEFAULT NULL,
    event_type VARCHAR(100) NOT NULL,
    event_source VARCHAR(100) DEFAULT NULL,
    tool_name VARCHAR(100) DEFAULT NULL,
    detected_trade VARCHAR(100) DEFAULT NULL,
    properties JSON DEFAULT NULL,
    ip_hash VARCHAR(64) DEFAULT NULL,
    user_agent_hash VARCHAR(64) DEFAULT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id BIGBIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    account_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    conversation_id VARCHAR(64) NOT NULL,
    role VARCHAR(20) NOT NULL,
    content TEXT NOT NULL,
    context_snapshot JSON DEFAULT NULL,
    model_used VARCHAR(100) DEFAULT NULL,
    tokens_input INTEGER DEFAULT NULL,
    tokens_output INTEGER DEFAULT NULL,
    latency_ms INTEGER DEFAULT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tool_usage_log (
    id BIGBIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    tool_name VARCHAR(100) NOT NULL,
    account_id INTEGER DEFAULT NULL,
    session_fingerprint VARCHAR(64) DEFAULT NULL,
    detected_trade VARCHAR(100) DEFAULT NULL,
    service_area VARCHAR(200) DEFAULT NULL,
    inputs JSON NOT NULL,
    outputs JSON DEFAULT NULL,
    converted BOOLEAN NOT NULL DEFAULT FALSE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_user_events_account ON user_events(account_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_user_events_type ON user_events(event_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_user_events_trade ON user_events(detected_trade, event_type);
CREATE INDEX IF NOT EXISTS idx_chat_messages_account ON chat_messages(account_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_chat_messages_conv ON chat_messages(conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_tool_usage_name ON tool_usage_log(tool_name, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tool_usage_trade ON tool_usage_log(detected_trade, tool_name);

-- ===== Agent Configuration Tables =====
CREATE TABLE IF NOT EXISTS agent_configurations (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- Account scope (NULL = global default, account_id = per-account override)
    account_id INT DEFAULT NULL,

    -- Agent identification
    agent_id VARCHAR(100) NOT NULL,
    agent_type VARCHAR(100) NOT NULL,

    -- Basic settings
    enabled BOOLEAN DEFAULT TRUE,
    auto_execute_threshold DECIMAL(3,2) DEFAULT 0.95,

    -- Custom prompt additions (business-specific context)
    custom_prompt TEXT DEFAULT NULL,

    -- Risk level overrides (JSON)
    -- Example: {"pause_keyword": "medium", "add_negative_keyword": "low"}
    risk_overrides JSON DEFAULT NULL,

    -- Business rules (JSON array of if/then rules)
    -- Example: [{"if": "campaign_spend > 1000 AND roas < 2.0", "then": "require_approval"}]
    business_rules JSON DEFAULT NULL,

    -- Schedule settings
    run_frequency VARCHAR(50) DEFAULT 'default',  -- default, hourly, daily, weekly, custom

    -- Metadata
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_by INT DEFAULT NULL,

    -- Indexes
    UNIQUE KEY unique_agent_account (agent_id, account_id),
    INDEX idx_account (account_id),
    INDEX idx_enabled (enabled),

    -- Foreign key
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ===== Agent Decisions Table =====
CREATE TABLE IF NOT EXISTS agent_decisions (
    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,

    -- Agent identification
    agent_id VARCHAR(100) NOT NULL,
    agent_type VARCHAR(100) NOT NULL,
    decision_type VARCHAR(100) NOT NULL,

    -- Decision details
    title VARCHAR(500) NOT NULL,
    description TEXT,
    reasoning TEXT,

    -- Target (where this decision applies)
    account_id INTEGER NOT NULL,
    customer_id VARCHAR(50) NOT NULL,
    campaign_id VARCHAR(50),
    ad_group_id VARCHAR(50),

    -- Action data (JSON string)
    action_data TEXT,

    -- Risk & Approval
    risk_level VARCHAR(20) NOT NULL DEFAULT 'medium',
    requires_approval BOOLEAN NOT NULL DEFAULT TRUE,
    confidence DECIMAL(5, 4),  -- 0.0000 to 1.0000

    -- Expected Impact
    expected_monthly_savings DECIMAL(12, 2),
    expected_monthly_leads INTEGER,
    expected_improvement_pct DECIMAL(5, 2),

    -- Timeline
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    execute_after TIMESTAMP,
    expires_at TIMESTAMP,

    -- Status tracking
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    executed_at TIMESTAMP,
    execution_result TEXT,

    -- Learning (predicted vs actual outcomes)
    predicted_outcome TEXT,
    actual_outcome TEXT,
    prediction_accuracy DECIMAL(5, 4),  -- 0.0000 to 1.0000

    -- Metadata
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_agent_decisions_account ON agent_decisions(account_id);
CREATE INDEX IF NOT EXISTS idx_agent_decisions_customer ON agent_decisions(customer_id);
CREATE INDEX IF NOT EXISTS idx_agent_decisions_status ON agent_decisions(status);
CREATE INDEX IF NOT EXISTS idx_agent_decisions_agent_id ON agent_decisions(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_decisions_decision_type ON agent_decisions(decision_type);
CREATE INDEX IF NOT EXISTS idx_agent_decisions_created_at ON agent_decisions(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_decisions_risk_level ON agent_decisions(risk_level);
CREATE INDEX IF NOT EXISTS idx_agent_decisions_approval_queue
CREATE INDEX IF NOT EXISTS idx_agent_decisions_learning

-- ===== Agent Execution Log =====
CREATE TABLE IF NOT EXISTS agent_execution_log (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- Account and agent info
    account_id INT NOT NULL,
    agent_id VARCHAR(100) NOT NULL,
    agent_type VARCHAR(100) NOT NULL,

    -- Execution timing
    cycle_start DATETIME NOT NULL,
    cycle_duration_seconds DECIMAL(10,3),

    -- Results
    opportunities_found INT DEFAULT 0,
    decisions_made INT DEFAULT 0,
    auto_executed INT DEFAULT 0,
    pending_approval INT DEFAULT 0,

    -- Status
    status VARCHAR(50) DEFAULT 'completed',
    error_message TEXT,

    -- Timestamp
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Indexes
    INDEX idx_account_agent (account_id, agent_type, created_at),
    INDEX idx_created (created_at),
    INDEX idx_status (status, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ===== Captured Leads =====
CREATE TABLE IF NOT EXISTS captured_leads (
  id             INT AUTO_INCREMENT PRIMARY KEY,
  email          VARCHAR(254) NOT NULL,
  tool_name      VARCHAR(100),
  detected_trade VARCHAR(100),
  service_area   VARCHAR(200),
  result_summary TEXT,
  source         VARCHAR(100) DEFAULT 'free_tool',
  ip_hash        VARCHAR(64),
  created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_email   (email),
  INDEX idx_tool    (tool_name),
  INDEX idx_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


SET foreign_key_checks = 1;
