-- Migration: create seo_scan_results table
-- Required by SEOScanResult model (app/models_seo.py)
-- Used to store content recommendations, freshness scans, image audits, etc.

CREATE TABLE IF NOT EXISTS seo_scan_results (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    account_id  INT          NOT NULL,
    site_id     INT          NULL,
    scan_type   VARCHAR(64)  NOT NULL,
    url         VARCHAR(2048) NULL,
    score       INT          NULL,
    pass_count  INT          NULL,
    warn_count  INT          NULL,
    fail_count  INT          NULL,
    issue_count INT          NULL,
    item_count  INT          NULL,
    data        JSON         NULL,
    created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_seo_scan_account    (account_id),
    INDEX idx_seo_scan_type       (scan_type),
    INDEX idx_seo_scan_acct_type  (account_id, scan_type),
    INDEX idx_seo_scan_created    (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
