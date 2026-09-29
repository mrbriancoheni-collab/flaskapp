-- migrations/add_agent_knowledge_tables.sql
-- Agent Knowledge Base: approved external sources + cached summaries per agent type

CREATE TABLE IF NOT EXISTS agent_knowledge_sources (
    id                  INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    agent_type          VARCHAR(64)  NOT NULL,
    title               VARCHAR(255) NOT NULL,
    url                 TEXT         NOT NULL,
    source_type         VARCHAR(32)  NOT NULL DEFAULT 'webpage',
    category            VARCHAR(64)  NOT NULL DEFAULT 'best_practices',
    refresh_frequency   VARCHAR(16)  NOT NULL DEFAULT 'weekly',
    is_approved         TINYINT(1)   NOT NULL DEFAULT 0,
    is_active           TINYINT(1)   NOT NULL DEFAULT 1,
    is_default          TINYINT(1)   NOT NULL DEFAULT 0,
    approved_by_user_id INT UNSIGNED NULL,
    last_fetched_at     DATETIME     NULL,
    fetch_error         TEXT         NULL,
    created_at          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_agent_type (agent_type),
    INDEX idx_approved  (is_approved, is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS agent_knowledge_cache (
    id            INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    agent_type    VARCHAR(64)  NOT NULL,
    source_id     INT UNSIGNED NULL,
    summary       TEXT         NOT NULL,
    key_insights  JSON         NULL,
    refreshed_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    token_count   INT UNSIGNED NOT NULL DEFAULT 0,
    INDEX idx_agent_type_refreshed (agent_type, refreshed_at DESC),
    FOREIGN KEY (source_id) REFERENCES agent_knowledge_sources(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
