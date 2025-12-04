-- Migration: Add Social Media Ad Composer Tables
-- Date: 2025-12-04
-- Description: Creates tables for AI-powered ad creative generation

-- Table: ad_creatives
-- Stores generated ad creatives with images and copy
CREATE TABLE IF NOT EXISTS ad_creatives (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NULL,
    account_id INT NULL,

    -- Creative details
    name VARCHAR(255) NOT NULL,
    platform ENUM('facebook', 'instagram', 'linkedin', 'twitter', 'google', 'multi') NOT NULL DEFAULT 'facebook',

    -- Image
    image_url VARCHAR(1000) NULL,
    image_prompt TEXT NULL,
    image_storage_key VARCHAR(500) NULL,

    -- Copy
    headline VARCHAR(255) NULL,
    primary_text TEXT NULL,
    description VARCHAR(500) NULL,
    call_to_action VARCHAR(100) NULL,

    -- Generation details
    generation_method ENUM('ai_website', 'ai_manual', 'manual', 'template') NOT NULL DEFAULT 'ai_manual',
    source_url VARCHAR(1000) NULL,
    template_id INT NULL,

    -- AI model info
    image_model VARCHAR(100) NULL,
    copy_model VARCHAR(100) NULL,

    -- Metadata
    industry VARCHAR(100) NULL,
    target_audience VARCHAR(255) NULL,
    ad_objective VARCHAR(100) NULL,

    -- Usage tracking
    used_in_campaign BOOLEAN DEFAULT FALSE,
    impressions INT DEFAULT 0,
    clicks INT DEFAULT 0,
    conversions INT DEFAULT 0,

    -- Status
    status ENUM('draft', 'approved', 'published', 'archived') NOT NULL DEFAULT 'draft',

    -- Additional data
    extra_data JSON NULL,

    -- Timestamps
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    published_at DATETIME NULL,

    INDEX idx_user_id (user_id),
    INDEX idx_account_id (account_id),
    INDEX idx_status (status),
    INDEX idx_platform (platform),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Table: ad_creative_variations
-- A/B test variations of an ad creative
CREATE TABLE IF NOT EXISTS ad_creative_variations (
    id INT AUTO_INCREMENT PRIMARY KEY,
    parent_creative_id INT NOT NULL,

    -- Variation details
    variation_type ENUM('headline', 'image', 'copy', 'cta', 'full') NOT NULL,

    -- Variation content
    headline VARCHAR(255) NULL,
    primary_text TEXT NULL,
    description VARCHAR(500) NULL,
    call_to_action VARCHAR(100) NULL,
    image_url VARCHAR(1000) NULL,

    -- Performance
    impressions INT DEFAULT 0,
    clicks INT DEFAULT 0,
    conversions INT DEFAULT 0,
    is_winner BOOLEAN DEFAULT FALSE,

    -- Timestamps
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_parent_creative_id (parent_creative_id),
    FOREIGN KEY (parent_creative_id) REFERENCES ad_creatives(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Table: ad_templates
-- Pre-made templates for common local service business ads
CREATE TABLE IF NOT EXISTS ad_templates (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- Template details
    name VARCHAR(255) NOT NULL,
    description TEXT NULL,
    industry VARCHAR(100) NOT NULL,
    category VARCHAR(100) NULL,

    -- Template content (with variables like {{business_name}}, {{service}})
    headline_template VARCHAR(255) NOT NULL,
    copy_template TEXT NOT NULL,
    cta_template VARCHAR(100) NOT NULL,

    -- Image guidance
    image_style VARCHAR(100) NULL,
    image_prompt_template TEXT NULL,

    -- Platform compatibility
    platforms VARCHAR(255) NOT NULL,

    -- Performance
    times_used INT DEFAULT 0,
    avg_ctr FLOAT NULL,

    -- Status
    is_active BOOLEAN DEFAULT TRUE,
    is_featured BOOLEAN DEFAULT FALSE,

    -- Timestamps
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    INDEX idx_industry (industry),
    INDEX idx_is_active (is_active),
    INDEX idx_is_featured (is_featured)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Table: ad_generation_jobs
-- Track AI generation jobs (can take time for images)
CREATE TABLE IF NOT EXISTS ad_generation_jobs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,

    -- Job details
    job_type ENUM('website_scan', 'image_generation', 'copy_generation', 'full_creative') NOT NULL,

    -- Input
    input_data JSON NULL,

    -- Output
    creative_id INT NULL,
    output_data JSON NULL,

    -- Status
    status ENUM('pending', 'processing', 'completed', 'failed') NOT NULL DEFAULT 'pending',
    error_message TEXT NULL,

    -- Timestamps
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at DATETIME NULL,

    INDEX idx_user_id (user_id),
    INDEX idx_creative_id (creative_id),
    INDEX idx_status (status),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (creative_id) REFERENCES ad_creatives(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Insert sample templates for common home service industries
INSERT INTO ad_templates (name, description, industry, category, headline_template, copy_template, cta_template, platforms, is_active, is_featured) VALUES
('Emergency Plumbing', 'Emergency plumbing services ad', 'plumbing', 'emergency', '24/7 Emergency Plumbing - {{business_name}}', 'Need a plumber fast? {{business_name}} provides emergency plumbing services 24/7. Licensed, insured, and ready to help. {{service}}', 'Call Now', 'facebook,instagram,google', TRUE, TRUE),
('HVAC Seasonal', 'Seasonal HVAC maintenance ad', 'hvac', 'seasonal', 'Beat the Heat with {{business_name}}', 'Don\'t wait for your AC to break! Schedule your seasonal HVAC maintenance with {{business_name}}. Expert service, fair pricing. {{service}}', 'Schedule Now', 'facebook,instagram,linkedin', TRUE, TRUE),
('Electrical Safety', 'Electrical safety inspection ad', 'electrical', 'safety', 'Licensed Electricians - {{business_name}}', 'Protect your home with a professional electrical safety inspection from {{business_name}}. Licensed, certified, and trusted. {{service}}', 'Get Inspection', 'facebook,google,linkedin', TRUE, FALSE),
('Roofing Special', 'Roofing services promotion', 'roofing', 'promotion', 'Expert Roofing Services - {{business_name}}', 'Quality roofing you can trust. {{business_name}} offers professional installation, repair, and maintenance. Free estimates! {{service}}', 'Free Estimate', 'facebook,instagram,google', TRUE, TRUE);
