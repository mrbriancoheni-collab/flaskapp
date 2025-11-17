-- ============================================================================
-- Agent Configurations Table - Admin panel settings for agents
-- ============================================================================

CREATE TABLE IF NOT EXISTS agent_configurations (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- Account scope (NULL = global default, account_id = per-account override)
    account_id INT DEFAULT NULL,

    -- Agent identification
    agent_id VARCHAR(100) NOT NULL,
    agent_type VARCHAR(100) NOT NULL,

    -- Basic settings
    enabled BOOLEAN DEFAULT TRUE,
    auto_execute_threshold DECIMAL(3,2) DEFAULT 0.95,

    -- Custom prompt additions (business-specific context)
    custom_prompt TEXT DEFAULT NULL,

    -- Risk level overrides (JSON)
    -- Example: {"pause_keyword": "medium", "add_negative_keyword": "low"}
    risk_overrides JSON DEFAULT NULL,

    -- Business rules (JSON array of if/then rules)
    -- Example: [{"if": "campaign_spend > 1000 AND roas < 2.0", "then": "require_approval"}]
    business_rules JSON DEFAULT NULL,

    -- Schedule settings
    run_frequency VARCHAR(50) DEFAULT 'default',  -- default, hourly, daily, weekly, custom

    -- Metadata
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_by INT DEFAULT NULL,

    -- Indexes
    UNIQUE KEY unique_agent_account (agent_id, account_id),
    INDEX idx_account (account_id),
    INDEX idx_enabled (enabled),

    -- Foreign key
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Comments
COMMENT ON TABLE agent_configurations IS 'Admin configuration settings for AI agents';
COMMENT ON COLUMN agent_configurations.account_id IS 'NULL = global default, specific value = account override';
COMMENT ON COLUMN agent_configurations.custom_prompt IS 'Business-specific context added to agent analysis';
COMMENT ON COLUMN agent_configurations.risk_overrides IS 'Override default risk levels per decision type';
COMMENT ON COLUMN agent_configurations.business_rules IS 'Custom if/then rules for decision making';

-- Seed global defaults for all agents
INSERT INTO agent_configurations (account_id, agent_id, agent_type, enabled, auto_execute_threshold, custom_prompt) VALUES
(NULL, 'strategic_director', 'StrategicDirectorAgent', TRUE, 0.85, NULL),
(NULL, 'campaign_manager', 'CampaignManagerAgent', TRUE, 0.90, NULL),
(NULL, 'budget_guardian', 'BudgetGuardianAgent', TRUE, 0.90, NULL),
(NULL, 'quality_score_agent', 'QualityScoreAgent', TRUE, 0.90, NULL),
(NULL, 'keyword_optimizer', 'KeywordOptimizerAgent', TRUE, 0.92, NULL),
(NULL, 'negative_keyword_agent', 'NegativeKeywordAgent', TRUE, 0.95, NULL),
(NULL, 'ad_copy_agent', 'AdCopyAgent', TRUE, 0.90, NULL),
(NULL, 'landing_page_analyst', 'LandingPageAnalystAgent', TRUE, 0.75, NULL);
