-- Migration: add referral_requests, reactivation_sends, nps_surveys tables
-- Run after: add_appointment_reminder_sent_at.sql

CREATE TABLE IF NOT EXISTS referral_requests (
    id           SERIAL PRIMARY KEY,
    account_id   INTEGER NOT NULL,
    channel      VARCHAR(16) NOT NULL,          -- 'email' | 'sms'
    recipient    VARCHAR(255) NOT NULL,
    customer_name VARCHAR(255),
    job_type     VARCHAR(255),
    status       VARCHAR(32) NOT NULL DEFAULT 'queued',  -- queued | sent | failed
    created_at   TIMESTAMP NOT NULL DEFAULT NOW(),
    sent_at      TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_referral_requests_account_id ON referral_requests (account_id);
CREATE INDEX IF NOT EXISTS ix_referral_requests_status     ON referral_requests (status);


CREATE TABLE IF NOT EXISTS reactivation_sends (
    id             SERIAL PRIMARY KEY,
    account_id     INTEGER NOT NULL,
    customer_email VARCHAR(255),
    customer_phone VARCHAR(32),
    customer_name  VARCHAR(255),
    sent_at        TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_reactivation_sends_account_id     ON reactivation_sends (account_id);
CREATE INDEX IF NOT EXISTS ix_reactivation_sends_customer_email ON reactivation_sends (customer_email);
CREATE INDEX IF NOT EXISTS ix_reactivation_sends_sent_at        ON reactivation_sends (sent_at);


CREATE TABLE IF NOT EXISTS nps_surveys (
    id                  SERIAL PRIMARY KEY,
    account_id          INTEGER NOT NULL,
    token               VARCHAR(64) NOT NULL UNIQUE,
    customer_name       VARCHAR(255),
    customer_email      VARCHAR(255),
    customer_phone      VARCHAR(32),
    job_type            VARCHAR(255),
    score               SMALLINT CHECK (score >= 1 AND score <= 10),
    review_link_google  TEXT,
    status              VARCHAR(32) NOT NULL DEFAULT 'queued',  -- queued | sent | responded | failed
    created_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    sent_at             TIMESTAMP,
    responded_at        TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_nps_surveys_account_id ON nps_surveys (account_id);
CREATE INDEX IF NOT EXISTS ix_nps_surveys_status     ON nps_surveys (status);
