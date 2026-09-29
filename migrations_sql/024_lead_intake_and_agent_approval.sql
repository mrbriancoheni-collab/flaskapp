-- Migration 024: Lead Intake, Lead Inbox, Agent Approval, Reputation
-- Adds columns and tables for:
--   • LeadIngest   — status pipeline, lead_cost, service_type, timestamps
--   • LeadIntakeConfig — per-account Networx/eLocal/review config
--   • AIAction     — one-tap approval token fields
--   • ReviewRequest — customer_name, job_type, review links

-- ── LeadIngest additions ─────────────────────────────────────────────────────

ALTER TABLE lead_ingest
  ADD COLUMN IF NOT EXISTS service_type    VARCHAR(128)      NULL AFTER city,
  ADD COLUMN IF NOT EXISTS lead_cost       DECIMAL(10,2)     NULL AFTER service_type,
  ADD COLUMN IF NOT EXISTS status          VARCHAR(32)       NOT NULL DEFAULT 'new' AFTER lead_cost,
  ADD COLUMN IF NOT EXISTS job_notes       TEXT              NULL AFTER status,
  ADD COLUMN IF NOT EXISTS contacted_at    DATETIME          NULL AFTER job_notes,
  ADD COLUMN IF NOT EXISTS booked_at       DATETIME          NULL AFTER contacted_at,
  ADD COLUMN IF NOT EXISTS completed_at    DATETIME          NULL AFTER booked_at;

-- Index for inbox queries
CREATE INDEX IF NOT EXISTS idx_lead_ingest_status    ON lead_ingest (account_id, status);
CREATE INDEX IF NOT EXISTS idx_lead_ingest_source    ON lead_ingest (account_id, source);

-- ── LeadIntakeConfig (new table) ──────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS lead_intake_configs (
  id                            INT            NOT NULL AUTO_INCREMENT PRIMARY KEY,
  account_id                    INT            NOT NULL,
  networx_webhook_secret        VARCHAR(128)   NULL,
  networx_default_lead_cost     DECIMAL(10,2)  NULL DEFAULT 45.00,
  elocal_tracking_number        VARCHAR(32)    NULL,
  elocal_default_lead_cost      DECIMAL(10,2)  NULL DEFAULT 35.00,
  missed_call_sms_body          TEXT           NULL,
  review_request_sms_template   TEXT           NULL,
  review_request_email_subject  VARCHAR(255)   NULL,
  review_link_google            VARCHAR(512)   NULL,
  review_link_yelp              VARCHAR(512)   NULL,
  created_at                    DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at                    DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_lead_intake_configs_account (account_id),
  INDEX idx_lead_intake_configs_account (account_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── ReviewRequest additions ───────────────────────────────────────────────────

ALTER TABLE review_requests
  ADD COLUMN IF NOT EXISTS customer_name      VARCHAR(255) NULL AFTER account_id,
  ADD COLUMN IF NOT EXISTS job_type           VARCHAR(128) NULL AFTER customer_name,
  ADD COLUMN IF NOT EXISTS review_link_google VARCHAR(512) NULL AFTER job_type,
  ADD COLUMN IF NOT EXISTS review_link_yelp   VARCHAR(512) NULL AFTER review_link_google;

-- ── AIAction additions (one-tap approval) ────────────────────────────────────

ALTER TABLE ai_actions
  ADD COLUMN IF NOT EXISTS approval_token  VARCHAR(64)  NULL AFTER undo_reason,
  ADD COLUMN IF NOT EXISTS approval_sent_at DATETIME    NULL AFTER approval_token,
  ADD COLUMN IF NOT EXISTS approved_at     DATETIME     NULL AFTER approval_sent_at,
  ADD COLUMN IF NOT EXISTS rejected_at     DATETIME     NULL AFTER approved_at;

CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_actions_approval_token ON ai_actions (approval_token);
