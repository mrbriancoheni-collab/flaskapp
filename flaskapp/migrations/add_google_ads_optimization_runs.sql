-- Migration: google_ads_optimization_runs
-- Tracks the last time each account's Google Ads optimization analysis
-- was run so cron can skip accounts analysed recently.

CREATE TABLE IF NOT EXISTS google_ads_optimization_runs (
    account_id  INTEGER NOT NULL,
    ran_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (account_id)
);

CREATE INDEX IF NOT EXISTS idx_gads_opt_runs_ran_at
    ON google_ads_optimization_runs (ran_at DESC);
