-- CRM foundation: estimate pipeline + appointment/invoice tracking
-- Run once on production after deploying this release.
-- Safe to re-run (uses IF NOT EXISTS / IF column not exists guards).

-- 1. New columns on crm_jobs
--    appointment_at  — scheduled appointment datetime
--    invoiced_at     — when invoice was sent to customer

ALTER TABLE crm_jobs
    ADD COLUMN IF NOT EXISTS appointment_at DATETIME NULL AFTER job_date,
    ADD COLUMN IF NOT EXISTS invoiced_at    DATETIME NULL AFTER appointment_at;

-- Update job_status comment to document new valid values
-- (no data change, just documentation)
-- booked | scheduled | estimate | completed | invoiced | cancelled

-- 2. New crm_estimates table

CREATE TABLE IF NOT EXISTS crm_estimates (
    id                   INT          NOT NULL AUTO_INCREMENT PRIMARY KEY,
    account_id           INT          NOT NULL,
    crm_connection_id    INT          NULL,
    external_estimate_id VARCHAR(128) NULL,

    -- Customer contact (denormalised for automation)
    customer_name        VARCHAR(255) NULL,
    customer_email       VARCHAR(255) NULL,
    customer_phone       VARCHAR(32)  NULL,

    job_type             VARCHAR(255) NULL,
    amount_cents         INT          NOT NULL DEFAULT 0,

    -- Status: sent | viewed | accepted | rejected | expired
    status               VARCHAR(32)  NOT NULL DEFAULT 'sent',

    -- Lifecycle timestamps
    sent_at              DATETIME     NULL,
    viewed_at            DATETIME     NULL,
    responded_at         DATETIME     NULL,
    expires_at           DATETIME     NULL,

    -- Follow-up tracking (prevents double-sends)
    follow_up_1_sent_at  DATETIME     NULL,
    follow_up_2_sent_at  DATETIME     NULL,

    source_provider      VARCHAR(64)  NULL,   -- servicetitan | jobber | housecall_pro | manual
    raw_data             JSON         NULL,

    created_at           DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at           DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    INDEX idx_ce_account  (account_id),
    INDEX idx_ce_status   (status),
    INDEX idx_ce_conn     (crm_connection_id),
    INDEX idx_ce_sent_at  (sent_at),

    -- Unique per CRM connection + external ID.
    -- NULLs are treated as distinct in MySQL, so manual entries (both NULL) are always allowed.
    UNIQUE KEY uq_crm_estimate (crm_connection_id, external_estimate_id),

    CONSTRAINT fk_ce_conn FOREIGN KEY (crm_connection_id)
        REFERENCES crm_connections (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
