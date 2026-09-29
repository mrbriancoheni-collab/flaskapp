-- Migration 026: Home Services Enhancements
-- Service agreements, competitor radar, lead touches (multi-touch attribution),
-- notification settings, promo redemptions, lead aging, review automation.

-- ── Service / Maintenance Agreements ─────────────────────────────────────────
-- Recurring maintenance plan contracts (HVAC tune-ups, pest control, etc.)

CREATE TABLE IF NOT EXISTS service_agreements (
  id               INT            NOT NULL AUTO_INCREMENT PRIMARY KEY,
  account_id       INT            NOT NULL,
  customer_name    VARCHAR(255)   NOT NULL,
  customer_phone   VARCHAR(32)    NULL,
  customer_email   VARCHAR(255)   NULL,
  customer_address TEXT           NULL,
  plan_name        VARCHAR(255)   NOT NULL,     -- "HVAC Gold Plan", "Annual Pest Control"
  plan_type        VARCHAR(32)    NOT NULL DEFAULT 'annual',  -- annual|monthly|biannual
  service_type     VARCHAR(128)   NULL,         -- hvac|plumbing|pest|electrical|landscaping
  monthly_value    DECIMAL(10,2)  NOT NULL DEFAULT 0.00,
  annual_value     DECIMAL(10,2)  NOT NULL DEFAULT 0.00,
  start_date       DATE           NOT NULL,
  renewal_date     DATE           NOT NULL,
  status           VARCHAR(32)    NOT NULL DEFAULT 'active',  -- active|expired|cancelled|pending_renewal
  st_customer_id   VARCHAR(64)    NULL,         -- ServiceTitan customer ID
  notes            TEXT           NULL,
  created_at       DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at       DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_agreements_account (account_id),
  INDEX idx_agreements_renewal (account_id, renewal_date),
  INDEX idx_agreements_status (account_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── Competitor Radar ──────────────────────────────────────────────────────────
-- Track competitor GMB profile stats (review count, rating, velocity)

CREATE TABLE IF NOT EXISTS competitor_radar (
  id               INT            NOT NULL AUTO_INCREMENT PRIMARY KEY,
  account_id       INT            NOT NULL,
  competitor_name  VARCHAR(255)   NOT NULL,
  google_place_id  VARCHAR(255)   NULL,       -- Google Place ID for API lookups
  website_url      VARCHAR(500)   NULL,
  notes            TEXT           NULL,
  is_active        TINYINT(1)     NOT NULL DEFAULT 1,
  created_at       DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_competitor_radar_account (account_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS competitor_snapshots (
  id               INT            NOT NULL AUTO_INCREMENT PRIMARY KEY,
  competitor_id    INT            NOT NULL,
  account_id       INT            NOT NULL,
  snapshot_date    DATE           NOT NULL,
  review_count     INT            NULL,
  avg_rating       DECIMAL(3,2)   NULL,
  new_reviews      INT            NULL DEFAULT 0,   -- reviews gained since last snapshot
  notes            TEXT           NULL,
  created_at       DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_competitor_snapshot (competitor_id, snapshot_date),
  INDEX idx_competitor_snapshots_account (account_id, snapshot_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── Lead Touch Events (Multi-Touch Attribution) ───────────────────────────────
-- Tracks every touchpoint a lead has before converting

CREATE TABLE IF NOT EXISTS lead_touches (
  id               INT            NOT NULL AUTO_INCREMENT PRIMARY KEY,
  account_id       INT            NOT NULL,
  session_id       VARCHAR(128)   NULL,        -- anonymous session before lead conversion
  lead_ingest_id   INT            NULL,        -- FK to lead_ingest once converted
  touch_channel    VARCHAR(64)    NOT NULL,    -- google_ads|facebook|organic|direct|email|etc
  touch_type       VARCHAR(32)    NOT NULL DEFAULT 'visit',  -- visit|click|call|form|chat
  utm_source       VARCHAR(128)   NULL,
  utm_medium       VARCHAR(128)   NULL,
  utm_campaign     VARCHAR(255)   NULL,
  utm_content      VARCHAR(255)   NULL,
  referrer         VARCHAR(500)   NULL,
  landing_page     VARCHAR(500)   NULL,
  ip_hash          VARCHAR(64)    NULL,        -- hashed for privacy
  occurred_at      DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_lead_touches_account (account_id, occurred_at),
  INDEX idx_lead_touches_session (session_id),
  INDEX idx_lead_touches_lead (lead_ingest_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── Account Notification Settings ────────────────────────────────────────────
-- Controls what alerts/digests each account receives and how

CREATE TABLE IF NOT EXISTS account_notification_settings (
  id                          INT           NOT NULL AUTO_INCREMENT PRIMARY KEY,
  account_id                  INT           NOT NULL UNIQUE,
  -- Daily digest
  daily_digest_enabled        TINYINT(1)    NOT NULL DEFAULT 1,
  daily_digest_channel        VARCHAR(16)   NOT NULL DEFAULT 'sms',   -- sms|email|both
  daily_digest_phone          VARCHAR(32)   NULL,
  daily_digest_email          VARCHAR(255)  NULL,
  daily_digest_hour           TINYINT       NOT NULL DEFAULT 7,        -- 7 = 7am local
  -- Budget pacing alerts
  pacing_alert_enabled        TINYINT(1)    NOT NULL DEFAULT 1,
  pacing_alert_threshold_pct  INT           NOT NULL DEFAULT 120,      -- alert at 120% of expected pace
  pacing_alert_channel        VARCHAR(16)   NOT NULL DEFAULT 'sms',
  -- Speed-to-lead auto-response SMS
  auto_response_sms_enabled   TINYINT(1)    NOT NULL DEFAULT 0,
  auto_response_sms_template  TEXT          NULL,                      -- "Hi {name}, thanks for reaching out..."
  auto_response_delay_seconds INT           NOT NULL DEFAULT 60,
  -- Review request automation
  review_request_auto_enabled TINYINT(1)    NOT NULL DEFAULT 0,
  review_request_delay_hours  INT           NOT NULL DEFAULT 2,
  review_request_template     TEXT          NULL,
  review_request_link         VARCHAR(500)  NULL,                      -- Google review link
  -- Capacity alerts
  capacity_alert_enabled      TINYINT(1)    NOT NULL DEFAULT 1,
  capacity_high_threshold     INT           NOT NULL DEFAULT 85,       -- pause ads suggestion at 85%
  capacity_low_threshold      INT           NOT NULL DEFAULT 60,       -- increase ads suggestion at 60%
  -- Competitor alerts
  competitor_alert_enabled    TINYINT(1)    NOT NULL DEFAULT 1,
  competitor_alert_threshold  INT           NOT NULL DEFAULT 15,       -- alert if competitor gains 15+ reviews/month
  created_at                  DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at                  DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_notif_settings_account (account_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── Promo Code Redemptions ────────────────────────────────────────────────────
-- Tracks which leads redeemed which offline promo codes for ROI attribution

CREATE TABLE IF NOT EXISTS promo_redemptions (
  id                    INT           NOT NULL AUTO_INCREMENT PRIMARY KEY,
  account_id            INT           NOT NULL,
  promo_code            VARCHAR(64)   NOT NULL,
  offline_spend_id      INT           NULL,       -- FK to offline_channel_spend
  lead_ingest_id        INT           NULL,       -- FK to lead_ingest
  call_event_id         INT           NULL,       -- FK to call_events
  redeemed_at           DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  revenue_cents         INT           NULL,
  notes                 VARCHAR(500)  NULL,
  INDEX idx_promo_redemptions_account (account_id),
  INDEX idx_promo_redemptions_code (account_id, promo_code),
  INDEX idx_promo_redemptions_spend (offline_spend_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── Digest Send Log ───────────────────────────────────────────────────────────
-- Tracks daily digest sends to avoid duplicate delivery

CREATE TABLE IF NOT EXISTS digest_send_log (
  id                INT           NOT NULL AUTO_INCREMENT PRIMARY KEY,
  account_id        INT           NOT NULL,
  digest_date       DATE          NOT NULL,
  channel           VARCHAR(16)   NOT NULL,   -- sms|email
  recipient         VARCHAR(255)  NOT NULL,
  sent_at           DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  status            VARCHAR(32)   NOT NULL DEFAULT 'sent',
  UNIQUE KEY uq_digest_send (account_id, digest_date, channel),
  INDEX idx_digest_send_account (account_id, digest_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── Review Request Log ────────────────────────────────────────────────────────
-- Tracks automated review requests sent after job completion

CREATE TABLE IF NOT EXISTS review_request_log (
  id                INT           NOT NULL AUTO_INCREMENT PRIMARY KEY,
  account_id        INT           NOT NULL,
  st_job_id         VARCHAR(64)   NULL,       -- ServiceTitan job ID
  customer_name     VARCHAR(255)  NULL,
  customer_phone    VARCHAR(32)   NULL,
  customer_email    VARCHAR(255)  NULL,
  channel           VARCHAR(16)   NOT NULL DEFAULT 'sms',
  status            VARCHAR(32)   NOT NULL DEFAULT 'sent',  -- sent|delivered|clicked|reviewed
  sent_at           DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  clicked_at        DATETIME      NULL,
  reviewed_at       DATETIME      NULL,
  INDEX idx_review_req_account (account_id, sent_at),
  INDEX idx_review_req_job (account_id, st_job_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
