-- Migration 025: Marketing Command Center
-- New tables for offline channel tracking, lead aggregators, budget pacing,
-- attribution engine, and seasonal planning.

-- ── Offline Channel Spend ─────────────────────────────────────────────────────
-- Tracks spend for Billboard, Direct Mail, Print, Radio, Door Hangers, etc.

CREATE TABLE IF NOT EXISTS offline_channel_spend (
  id              INT            NOT NULL AUTO_INCREMENT PRIMARY KEY,
  account_id      INT            NOT NULL,
  channel_type    VARCHAR(32)    NOT NULL,   -- billboard|direct_mail|print|radio|door_hanger|vehicle_wrap|other
  channel_label   VARCHAR(255)   NOT NULL,   -- "I-35 Billboard", "Spring EDDM Campaign"
  spend_date      DATE           NOT NULL,
  amount          DECIMAL(12,2)  NOT NULL,
  tracking_number VARCHAR(32)    NULL,       -- unique phone # used for attribution
  estimated_reach INT            NULL,       -- DEC for billboard, pieces for mail
  zone            VARCHAR(255)   NULL,       -- zip codes, neighborhoods, or zones
  promo_code      VARCHAR(64)    NULL,       -- coupon code for tracking responses
  notes           TEXT           NULL,
  created_at      DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at      DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_offline_channel_account_date (account_id, spend_date),
  INDEX idx_offline_channel_account_type (account_id, channel_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── Lead Aggregator Accounts ──────────────────────────────────────────────────
-- Angi, HomeAdvisor, Thumbtack, Nextdoor, Bark, Porch, Houzz configurations

CREATE TABLE IF NOT EXISTS aggregator_accounts (
  id                  INT           NOT NULL AUTO_INCREMENT PRIMARY KEY,
  account_id          INT           NOT NULL,
  platform            VARCHAR(32)   NOT NULL,  -- angi|homeadvisor|thumbtack|nextdoor|bark|porch|houzz
  platform_label      VARCHAR(128)  NULL,       -- user-friendly label
  platform_account_id VARCHAR(128)  NULL,       -- external account ID if available
  api_key             VARCHAR(512)  NULL,       -- encrypted API key
  webhook_secret      VARCHAR(128)  NULL,
  default_lead_cost   DECIMAL(10,2) NULL,       -- default CPL when not provided by platform
  is_active           TINYINT(1)    NOT NULL DEFAULT 1,
  notes               TEXT          NULL,
  created_at          DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at          DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_aggregator_account_platform (account_id, platform),
  INDEX idx_aggregator_account (account_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── Aggregator Leads ──────────────────────────────────────────────────────────
-- Leads received from Angi, HomeAdvisor, Thumbtack, etc.

CREATE TABLE IF NOT EXISTS aggregator_leads (
  id                    INT            NOT NULL AUTO_INCREMENT PRIMARY KEY,
  account_id            INT            NOT NULL,
  aggregator_account_id INT            NULL,
  platform              VARCHAR(32)    NOT NULL,
  external_lead_id      VARCHAR(128)   NULL,
  name                  VARCHAR(255)   NULL,
  phone                 VARCHAR(64)    NULL,
  email                 VARCHAR(255)   NULL,
  service_type          VARCHAR(128)   NULL,
  city                  VARCHAR(128)   NULL,
  zip                   VARCHAR(16)    NULL,
  lead_cost             DECIMAL(10,2)  NULL,
  status                VARCHAR(32)    NOT NULL DEFAULT 'new',  -- new|contacted|booked|completed|lost
  notes                 TEXT           NULL,
  contacted_at          DATETIME       NULL,
  booked_at             DATETIME       NULL,
  completed_at          DATETIME       NULL,
  occurred_at           DATETIME       NULL,
  raw                   JSON           NULL,
  created_at            DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_aggregator_leads_account (account_id, platform),
  INDEX idx_aggregator_leads_status (account_id, status),
  INDEX idx_aggregator_leads_occurred (account_id, occurred_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── Channel Monthly Budgets ───────────────────────────────────────────────────
-- Per-channel monthly budget targets for pacing dashboard

CREATE TABLE IF NOT EXISTS channel_monthly_budgets (
  id             INT            NOT NULL AUTO_INCREMENT PRIMARY KEY,
  account_id     INT            NOT NULL,
  channel        VARCHAR(64)    NOT NULL,  -- google_ads|glsa|facebook|yelp|angi|billboard|direct_mail|print|radio|other
  budget_month   DATE           NOT NULL,  -- first day of the month
  budget_cents   INT            NOT NULL DEFAULT 0,
  notes          VARCHAR(255)   NULL,
  created_at     DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at     DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_channel_budget_month (account_id, channel, budget_month),
  INDEX idx_channel_budget_account (account_id, budget_month)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── Lead–Job Attribution Links ────────────────────────────────────────────────
-- Links a LeadIngest or aggregator_lead to a ServiceTitan job for true CAC

CREATE TABLE IF NOT EXISTS lead_job_links (
  id              INT           NOT NULL AUTO_INCREMENT PRIMARY KEY,
  account_id      INT           NOT NULL,
  lead_source     VARCHAR(32)   NOT NULL,   -- 'lead_ingest' | 'aggregator_lead' | 'call_event'
  lead_id         INT           NOT NULL,   -- FK to respective source table
  st_job_id       INT           NULL,       -- servicetitan_jobs.id
  st_job_external_id VARCHAR(64) NULL,      -- ServiceTitan's own job ID
  revenue_cents   INT           NULL,       -- job total in cents
  job_type        VARCHAR(128)  NULL,
  linked_at       DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_lead_job_links_account (account_id),
  INDEX idx_lead_job_links_lead (lead_source, lead_id),
  INDEX idx_lead_job_links_job (account_id, st_job_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── Seasonal Budget Plans ─────────────────────────────────────────────────────
-- 12-month marketing budget plans by channel, for the seasonal planner

CREATE TABLE IF NOT EXISTS seasonal_budget_plans (
  id             INT           NOT NULL AUTO_INCREMENT PRIMARY KEY,
  account_id     INT           NOT NULL,
  plan_year      SMALLINT      NOT NULL,
  channel        VARCHAR(64)   NOT NULL,
  jan_cents      INT           NOT NULL DEFAULT 0,
  feb_cents      INT           NOT NULL DEFAULT 0,
  mar_cents      INT           NOT NULL DEFAULT 0,
  apr_cents      INT           NOT NULL DEFAULT 0,
  may_cents      INT           NOT NULL DEFAULT 0,
  jun_cents      INT           NOT NULL DEFAULT 0,
  jul_cents      INT           NOT NULL DEFAULT 0,
  aug_cents      INT           NOT NULL DEFAULT 0,
  sep_cents      INT           NOT NULL DEFAULT 0,
  oct_cents      INT           NOT NULL DEFAULT 0,
  nov_cents      INT           NOT NULL DEFAULT 0,
  dec_cents      INT           NOT NULL DEFAULT 0,
  created_at     DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at     DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_seasonal_plan (account_id, plan_year, channel),
  INDEX idx_seasonal_plan_account (account_id, plan_year)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
