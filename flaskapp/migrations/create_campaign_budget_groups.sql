-- ============================================================================
-- Campaign Budget Groups - Segment campaigns into budget-controlled groups
-- ============================================================================
-- Use case: Allow users to allocate different budgets to campaign segments
-- Example: Campaigns 1,3,7 → $2,000/mo | Campaigns 2,4,9,10 → $5,000/mo | Rest → $3,000/mo

CREATE TABLE IF NOT EXISTS campaign_budget_groups (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- Account association
    account_id INT NOT NULL,

    -- Group details
    name VARCHAR(100) NOT NULL,
    description TEXT DEFAULT NULL,

    -- Budget allocation
    monthly_budget_cents INT NOT NULL DEFAULT 0,  -- Total monthly budget for this group
    daily_budget_cents INT GENERATED ALWAYS AS (monthly_budget_cents / 30) STORED,  -- Auto-calculated

    -- Status and control
    status VARCHAR(20) NOT NULL DEFAULT 'active',  -- active, paused, archived
    priority INT DEFAULT 0,  -- For budget allocation priority (higher = first)

    -- Budget Guardian integration
    auto_pause_on_overspend BOOLEAN DEFAULT TRUE,  -- Pause campaigns when group budget exhausted
    alert_threshold_pct DECIMAL(3,2) DEFAULT 0.80,  -- Alert when 80% of budget spent

    -- Metadata
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_by INT DEFAULT NULL,

    -- Indexes
    INDEX idx_account (account_id),
    INDEX idx_status (status),
    INDEX idx_priority (priority),

    -- Foreign keys
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ============================================================================
-- Campaign Budget Group Assignments - Maps campaigns to budget groups
-- ============================================================================

CREATE TABLE IF NOT EXISTS campaign_budget_assignments (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- Campaign and group
    campaign_id INT NOT NULL,
    budget_group_id INT NOT NULL,

    -- Assignment metadata
    assigned_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    assigned_by INT DEFAULT NULL,

    -- Indexes
    UNIQUE KEY unique_campaign_assignment (campaign_id),  -- Each campaign can only be in ONE group
    INDEX idx_budget_group (budget_group_id),

    -- Foreign keys
    FOREIGN KEY (campaign_id) REFERENCES ads_campaigns(id) ON DELETE CASCADE,
    FOREIGN KEY (budget_group_id) REFERENCES campaign_budget_groups(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ============================================================================
-- Budget Group Spend Tracking - Track actual spend per group
-- ============================================================================

CREATE TABLE IF NOT EXISTS campaign_budget_group_spend (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- Group and time period
    budget_group_id INT NOT NULL,
    period_month DATE NOT NULL,  -- First day of the month (e.g., 2025-01-01)

    -- Spend tracking
    total_spend_cents INT DEFAULT 0,
    total_impressions BIGINT DEFAULT 0,
    total_clicks INT DEFAULT 0,
    total_conversions DECIMAL(10,2) DEFAULT 0,

    -- Budget status
    budget_status VARCHAR(20) DEFAULT 'active',  -- active, warning, exceeded, paused
    alert_sent_at DATETIME DEFAULT NULL,

    -- Metadata
    last_updated DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- Indexes
    UNIQUE KEY unique_group_month (budget_group_id, period_month),
    INDEX idx_period (period_month),
    INDEX idx_budget_status (budget_status),

    -- Foreign keys
    FOREIGN KEY (budget_group_id) REFERENCES campaign_budget_groups(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ============================================================================
-- Comments
-- ============================================================================

COMMENT ON TABLE campaign_budget_groups IS 'Budget groups for segmenting campaigns with individual budgets';
COMMENT ON COLUMN campaign_budget_groups.monthly_budget_cents IS 'Total monthly budget allocated to this group in cents';
COMMENT ON COLUMN campaign_budget_groups.daily_budget_cents IS 'Auto-calculated daily budget (monthly/30)';
COMMENT ON COLUMN campaign_budget_groups.priority IS 'Higher priority groups get budget allocation first';
COMMENT ON COLUMN campaign_budget_groups.auto_pause_on_overspend IS 'Automatically pause campaigns when group budget is exhausted';

COMMENT ON TABLE campaign_budget_assignments IS 'Maps campaigns to budget groups (one campaign = one group)';
COMMENT ON COLUMN campaign_budget_assignments.campaign_id IS 'Unique - each campaign can only belong to one budget group';

COMMENT ON TABLE campaign_budget_group_spend IS 'Monthly spend tracking for budget groups';
COMMENT ON COLUMN campaign_budget_group_spend.period_month IS 'First day of month (e.g., 2025-01-01 for January 2025)';
COMMENT ON COLUMN campaign_budget_group_spend.budget_status IS 'active, warning (80%+), exceeded (100%+), paused';
