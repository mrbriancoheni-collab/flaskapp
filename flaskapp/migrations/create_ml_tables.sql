-- Universal event log — every meaningful user interaction
CREATE TABLE IF NOT EXISTS user_events (
    id BIGSERIAL PRIMARY KEY,
    account_id INTEGER DEFAULT NULL,
    user_id INTEGER DEFAULT NULL,
    session_fingerprint VARCHAR(64) DEFAULT NULL,
    event_type VARCHAR(100) NOT NULL,
    event_source VARCHAR(100) DEFAULT NULL,
    tool_name VARCHAR(100) DEFAULT NULL,
    detected_trade VARCHAR(100) DEFAULT NULL,
    properties JSONB DEFAULT NULL,
    ip_hash VARCHAR(64) DEFAULT NULL,
    user_agent_hash VARCHAR(64) DEFAULT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- AI chat messages — every question and response
CREATE TABLE IF NOT EXISTS chat_messages (
    id BIGSERIAL PRIMARY KEY,
    account_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    conversation_id VARCHAR(64) NOT NULL,
    role VARCHAR(20) NOT NULL,
    content TEXT NOT NULL,
    context_snapshot JSONB DEFAULT NULL,
    model_used VARCHAR(100) DEFAULT NULL,
    tokens_input INTEGER DEFAULT NULL,
    tokens_output INTEGER DEFAULT NULL,
    latency_ms INTEGER DEFAULT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Free tool usage — inputs and outputs from all tools
CREATE TABLE IF NOT EXISTS tool_usage_log (
    id BIGSERIAL PRIMARY KEY,
    tool_name VARCHAR(100) NOT NULL,
    account_id INTEGER DEFAULT NULL,
    session_fingerprint VARCHAR(64) DEFAULT NULL,
    detected_trade VARCHAR(100) DEFAULT NULL,
    service_area VARCHAR(200) DEFAULT NULL,
    inputs JSONB NOT NULL,
    outputs JSONB DEFAULT NULL,
    converted BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_user_events_account ON user_events(account_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_user_events_type ON user_events(event_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_user_events_trade ON user_events(detected_trade, event_type);
CREATE INDEX IF NOT EXISTS idx_chat_messages_account ON chat_messages(account_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_chat_messages_conv ON chat_messages(conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_tool_usage_name ON tool_usage_log(tool_name, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tool_usage_trade ON tool_usage_log(detected_trade, tool_name);
