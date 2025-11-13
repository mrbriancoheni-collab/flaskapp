-- Migration 014: Add Alert System Tables
-- Creates tables for general-purpose Google Ads alerting system

-- Create enum types for alerts
CREATE TYPE alert_type_enum AS ENUM ('paused_campaign', 'cpl_spike', 'quality_score_drop', 'custom');
CREATE TYPE alert_severity_enum_general AS ENUM ('info', 'warning', 'critical');
CREATE TYPE alert_status_enum AS ENUM ('active', 'resolved', 'dismissed');

-- Create alerts table
CREATE TABLE alerts (
    id SERIAL PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    -- Alert classification
    alert_type alert_type_enum NOT NULL,
    severity alert_severity_enum_general NOT NULL DEFAULT 'warning',

    -- Alert content
    title VARCHAR(255) NOT NULL,
    description TEXT NOT NULL,
    data JSONB,

    -- Status tracking
    status alert_status_enum NOT NULL DEFAULT 'active',

    -- Timestamps
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMP,
    dismissed_at TIMESTAMP,

    -- Notification tracking
    notified_at TIMESTAMP,
    email_sent BOOLEAN NOT NULL DEFAULT FALSE,

    -- Action link
    action_url VARCHAR(512),
    action_text VARCHAR(100)
);

-- Create indexes for alerts
CREATE INDEX idx_alerts_account_id ON alerts(account_id);
CREATE INDEX idx_alerts_user_id ON alerts(user_id);
CREATE INDEX idx_alerts_alert_type ON alerts(alert_type);
CREATE INDEX idx_alerts_severity ON alerts(severity);
CREATE INDEX idx_alerts_status ON alerts(status);
CREATE INDEX idx_alerts_created_at ON alerts(created_at);
CREATE INDEX idx_alerts_account_status ON alerts(account_id, status);
CREATE INDEX idx_alerts_user_status ON alerts(user_id, status);
CREATE INDEX idx_alerts_type_status ON alerts(alert_type, status);

-- Create alert_settings table
CREATE TABLE alert_settings (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,

    -- Paused Campaign Alerts
    paused_campaign_enabled BOOLEAN NOT NULL DEFAULT TRUE,

    -- CPL Spike Alerts
    cpl_spike_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    cpl_spike_threshold_percent INTEGER NOT NULL DEFAULT 20,
    cpl_spike_lookback_days INTEGER NOT NULL DEFAULT 7,

    -- Quality Score Drop Alerts
    quality_score_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    quality_score_threshold INTEGER NOT NULL DEFAULT 5,

    -- Email Notifications
    email_notifications_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    email_digest_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    email_digest_time VARCHAR(5) NOT NULL DEFAULT '09:00',

    -- Alert frequency limits
    max_alerts_per_day INTEGER NOT NULL DEFAULT 10,

    -- Timestamps
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Create index for alert_settings
CREATE INDEX idx_alert_settings_user_id ON alert_settings(user_id);

-- Create function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_alert_settings_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger for alert_settings updated_at
CREATE TRIGGER alert_settings_updated_at_trigger
BEFORE UPDATE ON alert_settings
FOR EACH ROW
EXECUTE FUNCTION update_alert_settings_updated_at();
