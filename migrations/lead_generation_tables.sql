-- Lead Generation System Tables
-- Run this migration to create tables for the lead generation feature

-- Lead Campaigns table
CREATE TABLE IF NOT EXISTS lead_campaigns (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
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

    INDEX idx_status (status),
    INDEX idx_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Leads table
CREATE TABLE IF NOT EXISTS leads (
    id INT AUTO_INCREMENT PRIMARY KEY,
    campaign_id INT NOT NULL,

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
    INDEX idx_enrichment_status (enrichment_status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Email Sequences table
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

-- Lead Emails Sent table (renamed to avoid conflict with existing emails_sent table)
CREATE TABLE IF NOT EXISTS lead_emails_sent (
    id INT AUTO_INCREMENT PRIMARY KEY,
    lead_id INT NOT NULL,
    sequence_id INT NOT NULL,

    -- Email details
    to_email VARCHAR(255) NOT NULL,
    subject VARCHAR(500) NOT NULL,
    body_html TEXT NULL,
    body_text TEXT NULL,

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
    FOREIGN KEY (sequence_id) REFERENCES email_sequences(id) ON DELETE CASCADE,
    INDEX idx_lead (lead_id),
    INDEX idx_sequence (sequence_id),
    INDEX idx_to_email (to_email),
    INDEX idx_mailgun_id (mailgun_message_id),
    INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Email Unsubscribes table (CAN-SPAM compliance)
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
