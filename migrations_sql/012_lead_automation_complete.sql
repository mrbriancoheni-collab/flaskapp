-- ============================================================================
-- Complete Lead Automation System Migration
-- ============================================================================
-- Creates all tables needed for the lead generation and email automation system
-- Run this migration to set up the full database schema
-- ============================================================================

-- 1. Lead Campaigns Table
CREATE TABLE IF NOT EXISTS lead_campaigns (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(200) NOT NULL,

    -- Search parameters
    industry_service VARCHAR(200) NOT NULL,
    location VARCHAR(200) NOT NULL,

    -- Scraping settings
    scrape_ads BOOLEAN DEFAULT TRUE,
    scrape_maps BOOLEAN DEFAULT TRUE,
    scrape_lsa BOOLEAN DEFAULT TRUE,
    scrape_organic BOOLEAN DEFAULT TRUE,
    max_organic_results INT DEFAULT 5,

    -- Email settings
    daily_email_limit INT DEFAULT 250,
    sequence_delay_days INT DEFAULT 3,

    -- Status
    status ENUM('draft', 'scraping', 'ready', 'sending', 'paused', 'completed') DEFAULT 'draft' NOT NULL,

    -- Stats
    leads_scraped INT DEFAULT 0,
    leads_enriched INT DEFAULT 0,
    emails_sent INT DEFAULT 0,
    emails_opened INT DEFAULT 0,
    emails_replied INT DEFAULT 0,

    -- Timestamps
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP NOT NULL,
    scraping_started_at DATETIME NULL,
    scraping_completed_at DATETIME NULL,
    sending_started_at DATETIME NULL,
    last_scraped_at DATETIME NULL,

    INDEX idx_status (status),
    INDEX idx_created (created_at),
    INDEX idx_last_scraped (last_scraped_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 2. Leads Table
CREATE TABLE IF NOT EXISTS leads (
    id INT AUTO_INCREMENT PRIMARY KEY,
    campaign_id INT NOT NULL,

    -- CRM integration
    crm_contact_id INT NULL,

    -- Company info
    company_name VARCHAR(255) NOT NULL,
    website VARCHAR(500) NULL,
    phone VARCHAR(50) NULL,
    address VARCHAR(500) NULL,

    -- Source
    source_type ENUM('ad', 'map', 'lsa', 'organic') NOT NULL,
    source_url VARCHAR(1000) NULL,
    serp_position INT NULL,

    -- Enrichment data
    email_format VARCHAR(100) NULL,
    decision_maker_name VARCHAR(200) NULL,
    decision_maker_title VARCHAR(100) NULL,
    decision_maker_email VARCHAR(255) NULL,
    decision_maker_linkedin VARCHAR(500) NULL,

    -- Enrichment status
    enrichment_status ENUM('pending', 'in_progress', 'completed', 'failed') DEFAULT 'pending' NOT NULL,
    enrichment_attempts INT DEFAULT 0,
    enriched_at DATETIME NULL,
    enrichment_completed_at DATETIME NULL,

    -- Email status
    email_status ENUM('pending', 'sending', 'sent', 'opened', 'replied', 'bounced', 'unsubscribed') DEFAULT 'pending' NOT NULL,
    current_sequence_step INT DEFAULT 0,

    -- Engagement tracking
    last_email_sent_at DATETIME NULL,
    first_opened_at DATETIME NULL,
    replied_at DATETIME NULL,
    unsubscribed_at DATETIME NULL,

    -- Auto-cleanup
    auto_delete_at DATETIME NULL,

    -- Extra data
    extra_data JSON NULL,

    -- Timestamps
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP NOT NULL,

    FOREIGN KEY (campaign_id) REFERENCES lead_campaigns(id) ON DELETE CASCADE,
    INDEX idx_campaign (campaign_id),
    INDEX idx_email (decision_maker_email),
    INDEX idx_email_status (email_status),
    INDEX idx_enrichment_status (enrichment_status),
    INDEX idx_enrichment_completed (enrichment_completed_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 3. Lead Contacts Table (multiple contacts per lead)
CREATE TABLE IF NOT EXISTS lead_contacts (
    id INT AUTO_INCREMENT PRIMARY KEY,
    lead_id INT NOT NULL,

    -- CRM integration
    company_contact_id INT NULL,

    -- Contact info
    name VARCHAR(200) NOT NULL,
    title VARCHAR(100) NULL,
    email VARCHAR(255) NULL,
    linkedin_url VARCHAR(500) NULL,

    -- Contact categorization
    role_category ENUM('executive', 'owner', 'marketing', 'operations', 'sales', 'other') DEFAULT 'other' NOT NULL,
    is_primary BOOLEAN DEFAULT FALSE,

    -- Email tracking for this specific contact
    email_status ENUM('pending', 'sending', 'sent', 'opened', 'replied', 'bounced', 'unsubscribed') DEFAULT 'pending' NOT NULL,
    current_sequence_step INT DEFAULT 0,
    last_email_sent_at DATETIME NULL,
    first_opened_at DATETIME NULL,
    replied_at DATETIME NULL,
    unsubscribed_at DATETIME NULL,

    -- Timestamps
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP NOT NULL,

    FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE,
    INDEX idx_lead (lead_id),
    INDEX idx_email (email),
    INDEX idx_email_status (email_status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 4. Email Sequences Table
CREATE TABLE IF NOT EXISTS email_sequences (
    id INT AUTO_INCREMENT PRIMARY KEY,
    campaign_id INT NOT NULL,

    step_number INT NOT NULL,
    name VARCHAR(200) NOT NULL,

    -- Email content
    subject VARCHAR(500) NOT NULL,
    body_html TEXT NOT NULL,
    body_text TEXT NULL,

    -- Timing
    delay_days INT DEFAULT 0,

    -- Status
    is_active BOOLEAN DEFAULT TRUE,

    -- Stats
    sent_count INT DEFAULT 0,
    opened_count INT DEFAULT 0,
    replied_count INT DEFAULT 0,

    -- Timestamps
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP NOT NULL,

    FOREIGN KEY (campaign_id) REFERENCES lead_campaigns(id) ON DELETE CASCADE,
    INDEX idx_campaign (campaign_id),
    INDEX idx_step (step_number),
    UNIQUE KEY unique_campaign_step (campaign_id, step_number)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 5. Lead Emails Sent Table (legacy table for leads without contacts)
CREATE TABLE IF NOT EXISTS lead_emails_sent (
    id INT AUTO_INCREMENT PRIMARY KEY,
    lead_id INT NOT NULL,
    campaign_id INT NULL,
    sequence_id INT NULL,
    sequence_step INT NULL,

    -- Email details
    to_email VARCHAR(255) NOT NULL,
    subject VARCHAR(500) NOT NULL,
    body_html TEXT NULL,
    body_text TEXT NULL,
    body TEXT NULL,

    -- Mailgun tracking
    mailgun_message_id VARCHAR(255) NULL,

    -- Status
    status ENUM('queued', 'sent', 'delivered', 'opened', 'clicked', 'bounced', 'failed', 'complained') DEFAULT 'queued' NOT NULL,

    -- Engagement
    sent_at DATETIME NULL,
    delivered_at DATETIME NULL,
    opened_at DATETIME NULL,
    clicked_at DATETIME NULL,
    bounced_at DATETIME NULL,
    complained_at DATETIME NULL,

    -- Error tracking
    error_message TEXT NULL,

    -- Timestamps
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP NOT NULL,

    FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE,
    INDEX idx_lead (lead_id),
    INDEX idx_campaign (campaign_id),
    INDEX idx_sequence (sequence_id),
    INDEX idx_to_email (to_email),
    INDEX idx_mailgun_id (mailgun_message_id),
    INDEX idx_status (status),
    INDEX idx_sent_at (sent_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 6. Lead Contact Emails Table (emails sent to specific contacts)
CREATE TABLE IF NOT EXISTS lead_contact_emails (
    id INT AUTO_INCREMENT PRIMARY KEY,
    contact_id INT NOT NULL,
    lead_id INT NOT NULL,
    campaign_id INT NOT NULL,
    sequence_step INT NOT NULL,

    -- Email details
    subject VARCHAR(500) NOT NULL,
    body TEXT NULL,
    to_email VARCHAR(255) NULL,

    -- Provider tracking
    email_provider VARCHAR(50) NULL DEFAULT 'mailgun',
    mailgun_message_id VARCHAR(255) NULL,
    brevo_message_id VARCHAR(255) NULL,

    -- Status
    status ENUM('queued', 'sent', 'delivered', 'opened', 'clicked', 'bounced', 'failed') DEFAULT 'queued' NOT NULL,

    -- Engagement tracking
    sent_at DATETIME NULL,
    delivered_at DATETIME NULL,
    opened_at DATETIME NULL,
    clicked_at DATETIME NULL,
    bounced_at DATETIME NULL,

    -- Error tracking
    error_message TEXT NULL,

    -- Timestamps
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP NOT NULL,

    FOREIGN KEY (contact_id) REFERENCES lead_contacts(id) ON DELETE CASCADE,
    FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE,
    FOREIGN KEY (campaign_id) REFERENCES lead_campaigns(id) ON DELETE CASCADE,
    INDEX idx_contact (contact_id),
    INDEX idx_lead (lead_id),
    INDEX idx_campaign (campaign_id),
    INDEX idx_mailgun_id (mailgun_message_id),
    INDEX idx_brevo_id (brevo_message_id),
    INDEX idx_status (status),
    INDEX idx_sent_at (sent_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 7. Email Unsubscribes Table (CAN-SPAM compliance)
CREATE TABLE IF NOT EXISTS email_unsubscribes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    email VARCHAR(255) NOT NULL,

    -- Metadata
    unsubscribed_from_campaign_id INT NULL,
    reason VARCHAR(500) NULL,

    -- Timestamp
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,

    UNIQUE KEY unique_email (email),
    INDEX idx_email (email),
    FOREIGN KEY (unsubscribed_from_campaign_id) REFERENCES lead_campaigns(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 8. Email Conversations Table (AI Auto-Responses)
CREATE TABLE IF NOT EXISTS email_conversations (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- Link to lead/contact
    lead_contact_id INT NOT NULL,

    -- Thread identification
    thread_id VARCHAR(255) NULL UNIQUE,
    subject VARCHAR(500) NULL,

    -- Status tracking
    status VARCHAR(50) DEFAULT 'active',
    ai_handled BOOLEAN DEFAULT TRUE,
    requires_human BOOLEAN DEFAULT FALSE,

    -- Metrics
    total_messages INT DEFAULT 0,
    ai_messages INT DEFAULT 0,
    human_messages INT DEFAULT 0,
    prospect_messages INT DEFAULT 0,

    -- Sentiment analysis
    last_sentiment VARCHAR(50) NULL,
    lead_score INT DEFAULT 0,

    -- Timestamps
    last_message_at DATETIME NOT NULL,
    last_prospect_reply_at DATETIME NULL,
    last_ai_reply_at DATETIME NULL,
    escalated_at DATETIME NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,

    FOREIGN KEY (lead_contact_id) REFERENCES lead_contacts(id) ON DELETE CASCADE,
    INDEX idx_contact (lead_contact_id),
    INDEX idx_thread (thread_id),
    INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 9. Email Conversation Messages Table
CREATE TABLE IF NOT EXISTS email_conversation_messages (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- Link to conversation
    conversation_id INT NOT NULL,

    -- Message details
    direction VARCHAR(50) NOT NULL,
    from_email VARCHAR(255) NOT NULL,
    to_email VARCHAR(255) NOT NULL,
    subject TEXT NULL,
    body_text TEXT NULL,
    body_html TEXT NULL,

    -- AI handling
    is_ai_generated BOOLEAN DEFAULT FALSE,
    ai_model VARCHAR(100) NULL,
    ai_prompt_used TEXT NULL,
    ai_confidence DECIMAL(3, 2) NULL,

    -- Provider details
    message_id VARCHAR(255) NULL,
    in_reply_to VARCHAR(255) NULL,
    `references` TEXT NULL,

    -- Sentiment & analysis
    sentiment VARCHAR(50) NULL,
    contains_question BOOLEAN DEFAULT FALSE,
    urgency_level VARCHAR(50) NULL,

    -- Timestamps
    received_at DATETIME NULL,
    sent_at DATETIME NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,

    FOREIGN KEY (conversation_id) REFERENCES email_conversations(id) ON DELETE CASCADE,
    INDEX idx_conversation (conversation_id),
    INDEX idx_message_id (message_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 10. Conversation Alerts Table
CREATE TABLE IF NOT EXISTS conversation_alerts (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- Link to conversation
    conversation_id INT NOT NULL,

    -- Alert details
    alert_type VARCHAR(50) NOT NULL,
    message TEXT NULL,
    severity VARCHAR(50) DEFAULT 'info',

    -- Status
    is_read BOOLEAN DEFAULT FALSE,
    read_at DATETIME NULL,
    dismissed BOOLEAN DEFAULT FALSE,
    dismissed_at DATETIME NULL,

    -- Timestamps
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,

    FOREIGN KEY (conversation_id) REFERENCES email_conversations(id) ON DELETE CASCADE,
    INDEX idx_conversation (conversation_id),
    INDEX idx_is_read (is_read),
    INDEX idx_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================================
-- Migration complete!
-- ============================================================================
SELECT '============================================================' as '';
SELECT 'Lead Automation Tables Created Successfully!' as '';
SELECT '============================================================' as '';
SELECT '' as '';
SELECT 'Created tables:' as '';
SELECT '1. lead_campaigns' as '';
SELECT '2. leads' as '';
SELECT '3. lead_contacts' as '';
SELECT '4. email_sequences' as '';
SELECT '5. lead_emails_sent' as '';
SELECT '6. lead_contact_emails' as '';
SELECT '7. email_unsubscribes' as '';
SELECT '8. email_conversations' as '';
SELECT '9. email_conversation_messages' as '';
SELECT '10. conversation_alerts' as '';
SELECT '' as '';
SELECT 'You can now run the lead automation system!' as '';
SELECT '============================================================' as '';
