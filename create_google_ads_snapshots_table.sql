-- Create table to store Google Ads snapshots with full history
-- Each API fetch creates a new record, allowing trend analysis and change tracking

CREATE TABLE IF NOT EXISTS google_ads_snapshots (
    id INT AUTO_INCREMENT PRIMARY KEY,
    account_id INT NOT NULL,
    fetched_at DATETIME NOT NULL,
    snapshot_data LONGTEXT NOT NULL COMMENT 'Full Google Ads data as JSON',
    campaigns_count INT DEFAULT 0,
    ad_groups_count INT DEFAULT 0,
    keywords_count INT DEFAULT 0,
    total_cost_30d DECIMAL(10,2) DEFAULT 0,
    total_conversions_30d INT DEFAULT 0,
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
    INDEX idx_account_fetched (account_id, fetched_at DESC),
    INDEX idx_fetched (fetched_at DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Add index for fast "latest snapshot" queries
CREATE INDEX idx_latest_snapshot ON google_ads_snapshots(account_id, fetched_at DESC);

COMMENT ON TABLE google_ads_snapshots IS 'Historical Google Ads data snapshots - one record per fetch';
