-- ============================================================================
-- Agent Execution Log Table - Track when agents run
-- ============================================================================

CREATE TABLE IF NOT EXISTS agent_execution_log (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- Account and agent info
    account_id INT NOT NULL,
    agent_id VARCHAR(100) NOT NULL,
    agent_type VARCHAR(100) NOT NULL,

    -- Execution timing
    cycle_start DATETIME NOT NULL,
    cycle_duration_seconds DECIMAL(10,3),

    -- Results
    opportunities_found INT DEFAULT 0,
    decisions_made INT DEFAULT 0,
    auto_executed INT DEFAULT 0,
    pending_approval INT DEFAULT 0,

    -- Status
    status VARCHAR(50) DEFAULT 'completed',
    error_message TEXT,

    -- Timestamp
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Indexes
    INDEX idx_account_agent (account_id, agent_type, created_at),
    INDEX idx_created (created_at),
    INDEX idx_status (status, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Comments
COMMENT ON TABLE agent_execution_log IS 'Tracks when AI agents run and their results';
