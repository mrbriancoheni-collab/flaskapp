-- Migration: Add company_contacts table for individual contacts at companies
-- Date: 2025-10-28
-- Description: Stores individual contacts (CEO, owner, marketing, etc.) discovered for each CRM company

CREATE TABLE company_contacts (
    id INT AUTO_INCREMENT PRIMARY KEY,
    crm_contact_id INT NOT NULL,
    full_name VARCHAR(255) NOT NULL,
    title VARCHAR(255) NULL COMMENT 'Job title: CEO, President, Marketing Director, etc.',
    email VARCHAR(255) NULL,
    phone VARCHAR(64) NULL,
    linkedin_url VARCHAR(512) NULL,
    role_category VARCHAR(50) NULL COMMENT 'executive, owner, marketing, operations, other',
    source VARCHAR(128) NULL COMMENT 'Where we found them: team page, about page, etc.',
    discovered_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (crm_contact_id) REFERENCES crm_contacts(id) ON DELETE CASCADE,
    INDEX idx_company_contacts_crm (crm_contact_id),
    INDEX idx_company_contacts_role (role_category),
    INDEX idx_company_contacts_email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Rollback script saved in 006_add_company_contacts_table_rollback.sql
