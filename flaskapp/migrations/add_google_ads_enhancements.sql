-- Google Ads tool enhancements (Items 1–10 from the 2026 report analysis)
-- Idempotent: IF NOT EXISTS guards + per-column ADD IF NOT EXISTS via information_schema.

-- ── 1. campaign_type — advertising_channel_type from Google Ads API ───────────
SET @col_exists = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'ads_campaigns'
      AND COLUMN_NAME = 'campaign_type'
);
SET @sql = IF(@col_exists = 0,
    'ALTER TABLE ads_campaigns ADD COLUMN campaign_type VARCHAR(32) DEFAULT NULL COMMENT ''SEARCH|PERFORMANCE_MAX|SHOPPING|DISPLAY|VIDEO|DEMAND_GEN'' AFTER network',
    'SELECT 1'
);
PREPARE _s FROM @sql; EXECUTE _s; DEALLOCATE PREPARE _s;

-- Index for type-based filtering in optimizer and digest
SET @idx_exists = (
    SELECT COUNT(*) FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'ads_campaigns'
      AND INDEX_NAME = 'ix_campaigns_type'
);
SET @sql = IF(@idx_exists = 0,
    'ALTER TABLE ads_campaigns ADD INDEX ix_campaigns_type (account_id, campaign_type)',
    'SELECT 1'
);
PREPARE _s FROM @sql; EXECUTE _s; DEALLOCATE PREPARE _s;


-- ── 2. Period budget (2026 open-beta campaign-level budgets) ──────────────────
SET @col_exists = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'ads_campaigns'
      AND COLUMN_NAME = 'period_budget_cents'
);
SET @sql = IF(@col_exists = 0,
    'ALTER TABLE ads_campaigns ADD COLUMN period_budget_cents BIGINT DEFAULT NULL COMMENT ''Total budget for the campaign period in cents'' AFTER daily_budget_cents',
    'SELECT 1'
);
PREPARE _s FROM @sql; EXECUTE _s; DEALLOCATE PREPARE _s;

SET @col_exists = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'ads_campaigns'
      AND COLUMN_NAME = 'period_budget_start'
);
SET @sql = IF(@col_exists = 0,
    'ALTER TABLE ads_campaigns ADD COLUMN period_budget_start DATE DEFAULT NULL AFTER period_budget_cents',
    'SELECT 1'
);
PREPARE _s FROM @sql; EXECUTE _s; DEALLOCATE PREPARE _s;

SET @col_exists = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'ads_campaigns'
      AND COLUMN_NAME = 'period_budget_end'
);
SET @sql = IF(@col_exists = 0,
    'ALTER TABLE ads_campaigns ADD COLUMN period_budget_end DATE DEFAULT NULL AFTER period_budget_start',
    'SELECT 1'
);
PREPARE _s FROM @sql; EXECUTE _s; DEALLOCATE PREPARE _s;


-- ── 3. Attribution ratio — last-click underestimate multiplier per campaign ───
-- 1.000 = no adjustment; 1.5 means last-click ROAS × 1.5 = estimated true ROAS
SET @col_exists = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'ads_campaigns'
      AND COLUMN_NAME = 'attribution_ratio'
);
SET @sql = IF(@col_exists = 0,
    'ALTER TABLE ads_campaigns ADD COLUMN attribution_ratio DECIMAL(5,3) NOT NULL DEFAULT 1.000 COMMENT ''Multiplier: last-click ROAS x this = estimated true ROAS'' AFTER target_roas',
    'SELECT 1'
);
PREPARE _s FROM @sql; EXECUTE _s; DEALLOCATE PREPARE _s;


-- ── 4. Campaign mix snapshots — weekly type distribution per account ──────────
CREATE TABLE IF NOT EXISTS gads_campaign_mix_snapshots (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    account_id      INT             NOT NULL,
    week_start      DATE            NOT NULL,
    campaign_type   VARCHAR(32)     NOT NULL,  -- SEARCH|PERFORMANCE_MAX|SHOPPING|...
    campaign_count  INT             NOT NULL DEFAULT 0,
    spend           DECIMAL(12,4)   NOT NULL DEFAULT 0,
    spend_pct       DECIMAL(5,2)    NOT NULL DEFAULT 0,  -- share of total account spend
    conversions     DECIMAL(10,2)   NOT NULL DEFAULT 0,
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_mix (account_id, week_start, campaign_type),
    KEY ix_mix_account (account_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
