-- Migration: ads_competitor_snapshots
-- Stores periodic snapshots of competitor auction insight metrics so
-- track_competitor_ad_copy() can detect meaningful changes over time.

CREATE TABLE IF NOT EXISTS ads_competitor_snapshots (
    id              SERIAL PRIMARY KEY,
    account_id      INTEGER NOT NULL,
    domain          VARCHAR(255) NOT NULL,
    impression_share NUMERIC(6,4),
    overlap_rate    NUMERIC(6,4),
    position_above_rate NUMERIC(6,4),
    top_impression_share NUMERIC(6,4),
    abs_top_impression_share NUMERIC(6,4),
    outranking_share NUMERIC(6,4),
    captured_at     TIMESTAMP NOT NULL DEFAULT NOW(),
    campaign_id     BIGINT
);

CREATE INDEX IF NOT EXISTS idx_ads_competitor_snapshots_account_domain
    ON ads_competitor_snapshots (account_id, domain);

CREATE INDEX IF NOT EXISTS idx_ads_competitor_snapshots_captured_at
    ON ads_competitor_snapshots (account_id, captured_at DESC);
