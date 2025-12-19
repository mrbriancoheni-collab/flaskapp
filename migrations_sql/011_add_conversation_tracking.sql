-- ============================================================================
-- Email Conversation Tracking Tables
-- Purpose: Track email threads and enable AI auto-responses
-- ============================================================================

-- Main conversations table
CREATE TABLE IF NOT EXISTS email_conversations (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- Link to lead/contact
    lead_contact_id INT NOT NULL,

    -- Thread identification
    thread_id VARCHAR(255) UNIQUE COMMENT 'Email thread ID from provider',
    subject VARCHAR(500) COMMENT 'Original email subject',

    -- Status tracking
    status ENUM('active', 'closed', 'escalated', 'spam') DEFAULT 'active',
    ai_handled BOOLEAN DEFAULT TRUE COMMENT 'True if AI can handle, false if needs human',
    requires_human BOOLEAN DEFAULT FALSE COMMENT 'Set true if AI determines human needed',

    -- Metrics
    total_messages INT DEFAULT 0,
    ai_messages INT DEFAULT 0,
    human_messages INT DEFAULT 0,
    prospect_messages INT DEFAULT 0,

    -- Sentiment analysis
    last_sentiment VARCHAR(50) COMMENT 'positive, negative, neutral, interested',
    lead_score INT DEFAULT 0 COMMENT '0-100 score based on engagement',

    -- Timestamps
    last_message_at DATETIME NOT NULL,
    last_prospect_reply_at DATETIME COMMENT 'Last time prospect replied',
    last_ai_reply_at DATETIME COMMENT 'Last time AI responded',
    escalated_at DATETIME COMMENT 'When conversation was escalated to human',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Indexes
    INDEX idx_lead_contact (lead_contact_id),
    INDEX idx_status (status),
    INDEX idx_requires_human (requires_human),
    INDEX idx_last_message (last_message_at DESC),

    FOREIGN KEY (lead_contact_id) REFERENCES lead_contacts(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Tracks email conversation threads for AI responses';

-- Individual messages in conversations
CREATE TABLE IF NOT EXISTS email_conversation_messages (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- Link to conversation
    conversation_id INT NOT NULL,

    -- Message details
    direction ENUM('inbound', 'outbound') NOT NULL,
    from_email VARCHAR(255) NOT NULL,
    to_email VARCHAR(255) NOT NULL,
    subject TEXT,
    body_text LONGTEXT,
    body_html LONGTEXT,

    -- AI handling
    is_ai_generated BOOLEAN DEFAULT FALSE,
    ai_model VARCHAR(100) COMMENT 'gpt-4, claude-3, etc',
    ai_prompt_used TEXT COMMENT 'Prompt used to generate response',
    ai_confidence DECIMAL(3,2) COMMENT 'AI confidence score 0.00-1.00',

    -- Provider details
    message_id VARCHAR(255) COMMENT 'Provider message ID',
    in_reply_to VARCHAR(255) COMMENT 'Message ID this replies to',
    references TEXT COMMENT 'Email References header',

    -- Sentiment & analysis
    sentiment VARCHAR(50) COMMENT 'positive, negative, neutral, interested',
    contains_question BOOLEAN DEFAULT FALSE,
    urgency_level VARCHAR(50) COMMENT 'low, medium, high, critical',

    -- Timestamps
    received_at DATETIME COMMENT 'When inbound message received',
    sent_at DATETIME COMMENT 'When outbound message sent',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Indexes
    INDEX idx_conversation (conversation_id),
    INDEX idx_direction (direction),
    INDEX idx_received_at (received_at DESC),
    INDEX idx_message_id (message_id),

    FOREIGN KEY (conversation_id) REFERENCES email_conversations(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Individual messages within conversation threads';

-- Conversation alerts for admin dashboard
CREATE TABLE IF NOT EXISTS conversation_alerts (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- Link to conversation
    conversation_id INT NOT NULL,

    -- Alert details
    alert_type ENUM('new_reply', 'needs_human', 'interested', 'negative', 'question') NOT NULL,
    message TEXT,
    severity ENUM('info', 'warning', 'urgent') DEFAULT 'info',

    -- Status
    is_read BOOLEAN DEFAULT FALSE,
    read_at DATETIME,
    dismissed BOOLEAN DEFAULT FALSE,
    dismissed_at DATETIME,

    -- Timestamps
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Indexes
    INDEX idx_conversation (conversation_id),
    INDEX idx_is_read (is_read),
    INDEX idx_created_at (created_at DESC),
    INDEX idx_severity (severity),

    FOREIGN KEY (conversation_id) REFERENCES email_conversations(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Notifications for admin about conversation activity';

-- ============================================================================
-- Verification queries
-- ============================================================================

-- Check tables were created
SELECT
    'email_conversations' as table_name,
    COUNT(*) as row_count
FROM email_conversations
UNION ALL
SELECT
    'email_conversation_messages' as table_name,
    COUNT(*) as row_count
FROM email_conversation_messages
UNION ALL
SELECT
    'conversation_alerts' as table_name,
    COUNT(*) as row_count
FROM conversation_alerts;

-- Show table structures
SHOW CREATE TABLE email_conversations\G
SHOW CREATE TABLE email_conversation_messages\G
SHOW CREATE TABLE conversation_alerts\G
