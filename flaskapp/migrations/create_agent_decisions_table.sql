-- Migration: Create agent_decisions table for AI agent decision tracking
-- This table logs all decisions made by AI agents for transparency, learning, and analytics

CREATE TABLE IF NOT EXISTS agent_decisions (
    id SERIAL PRIMARY KEY,

    -- Agent identification
    agent_id VARCHAR(100) NOT NULL,
    agent_type VARCHAR(100) NOT NULL,
    decision_type VARCHAR(100) NOT NULL,

    -- Decision details
    title VARCHAR(500) NOT NULL,
    description TEXT,
    reasoning TEXT,

    -- Target (where this decision applies)
    account_id INTEGER NOT NULL,
    customer_id VARCHAR(50) NOT NULL,
    campaign_id VARCHAR(50),
    ad_group_id VARCHAR(50),

    -- Action data (JSON string)
    action_data TEXT,

    -- Risk & Approval
    risk_level VARCHAR(20) NOT NULL DEFAULT 'medium',
    requires_approval BOOLEAN NOT NULL DEFAULT TRUE,
    confidence DECIMAL(5, 4),  -- 0.0000 to 1.0000

    -- Expected Impact
    expected_monthly_savings DECIMAL(12, 2),
    expected_monthly_leads INTEGER,
    expected_improvement_pct DECIMAL(5, 2),

    -- Timeline
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    execute_after TIMESTAMP,
    expires_at TIMESTAMP,

    -- Status tracking
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    executed_at TIMESTAMP,
    execution_result TEXT,

    -- Learning (predicted vs actual outcomes)
    predicted_outcome TEXT,  -- JSON string
    actual_outcome TEXT,  -- JSON string
    prediction_accuracy DECIMAL(5, 4),  -- 0.0000 to 1.0000

    -- Metadata
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_agent_decisions_account ON agent_decisions(account_id);
CREATE INDEX IF NOT EXISTS idx_agent_decisions_customer ON agent_decisions(customer_id);
CREATE INDEX IF NOT EXISTS idx_agent_decisions_status ON agent_decisions(status);
CREATE INDEX IF NOT EXISTS idx_agent_decisions_agent_id ON agent_decisions(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_decisions_decision_type ON agent_decisions(decision_type);
CREATE INDEX IF NOT EXISTS idx_agent_decisions_created_at ON agent_decisions(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_decisions_risk_level ON agent_decisions(risk_level);

-- Composite indexes for common queries
CREATE INDEX IF NOT EXISTS idx_agent_decisions_approval_queue
    ON agent_decisions(account_id, status, requires_approval, created_at DESC)
    WHERE status = 'pending' AND requires_approval = TRUE;

CREATE INDEX IF NOT EXISTS idx_agent_decisions_learning
    ON agent_decisions(agent_id, decision_type, prediction_accuracy)
    WHERE prediction_accuracy IS NOT NULL;

-- Comments for documentation
COMMENT ON TABLE agent_decisions IS 'Tracks all decisions made by AI agents in the multi-agent system';
COMMENT ON COLUMN agent_decisions.agent_id IS 'Unique identifier for the agent instance (e.g., "campaign_manager_01")';
COMMENT ON COLUMN agent_decisions.agent_type IS 'Type of agent (e.g., "CampaignManagerAgent")';
COMMENT ON COLUMN agent_decisions.decision_type IS 'Type of decision (e.g., "pause_keyword", "adjust_bid")';
COMMENT ON COLUMN agent_decisions.risk_level IS 'Risk level: low, medium, high, critical';
COMMENT ON COLUMN agent_decisions.confidence IS 'Agent confidence in this decision (0.0-1.0)';
COMMENT ON COLUMN agent_decisions.status IS 'Status: pending, approved, rejected, executed, failed';
COMMENT ON COLUMN agent_decisions.prediction_accuracy IS 'How accurate the predicted outcome was (0.0-1.0), calculated after execution';
