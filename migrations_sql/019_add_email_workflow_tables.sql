-- Migration 019: Add Email Workflow System Tables
-- Creates tables for email templates, workflows, contact groups, and enrollment tracking

-- Contact Groups table
CREATE TABLE IF NOT EXISTS contact_groups (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_contact_groups_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Contact Group Members (junction table for many-to-many)
CREATE TABLE IF NOT EXISTS contact_group_members (
    id INT AUTO_INCREMENT PRIMARY KEY,
    contact_id INT NOT NULL,
    group_id INT NOT NULL,
    added_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    added_by_user_id INT NULL,
    UNIQUE KEY uq_contact_group (contact_id, group_id),
    INDEX idx_contact_group_members_contact (contact_id),
    INDEX idx_contact_group_members_group (group_id),
    FOREIGN KEY (contact_id) REFERENCES crm_contacts(id) ON DELETE CASCADE,
    FOREIGN KEY (group_id) REFERENCES contact_groups(id) ON DELETE CASCADE,
    FOREIGN KEY (added_by_user_id) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Email Templates table
CREATE TABLE IF NOT EXISTS email_templates (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    description TEXT NULL,
    subject VARCHAR(500) NOT NULL,
    body_html LONGTEXT NULL,
    body_text TEXT NULL,
    created_by_user_id INT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    INDEX idx_email_templates_name (name),
    INDEX idx_email_templates_active (is_active),
    FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Email Workflows table
CREATE TABLE IF NOT EXISTS email_workflows (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    description TEXT NULL,
    target_groups JSON NULL,
    created_by_user_id INT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    INDEX idx_email_workflows_name (name),
    INDEX idx_email_workflows_active (is_active),
    FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Workflow Steps table
CREATE TABLE IF NOT EXISTS workflow_steps (
    id INT AUTO_INCREMENT PRIMARY KEY,
    workflow_id INT NOT NULL,
    email_template_id INT NOT NULL,
    step_order INT NOT NULL,
    delay_days INT NOT NULL DEFAULT 0,
    delay_hours INT NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_workflow_step_order (workflow_id, step_order),
    INDEX idx_workflow_steps_workflow (workflow_id),
    INDEX idx_workflow_steps_order (workflow_id, step_order),
    FOREIGN KEY (workflow_id) REFERENCES email_workflows(id) ON DELETE CASCADE,
    FOREIGN KEY (email_template_id) REFERENCES email_templates(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Workflow Enrollments table
CREATE TABLE IF NOT EXISTS workflow_enrollments (
    id INT AUTO_INCREMENT PRIMARY KEY,
    workflow_id INT NOT NULL,
    crm_contact_id INT NOT NULL,
    current_step INT NOT NULL DEFAULT 0,
    status ENUM('active', 'paused', 'completed', 'unsubscribed', 'bounced') NOT NULL DEFAULT 'active',
    enrolled_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_email_sent_at DATETIME NULL,
    next_email_scheduled_at DATETIME NULL,
    completed_at DATETIME NULL,
    enrolled_by_user_id INT NULL,
    UNIQUE KEY uq_workflow_enrollment (workflow_id, crm_contact_id),
    INDEX idx_workflow_enrollments_workflow (workflow_id),
    INDEX idx_workflow_enrollments_contact (crm_contact_id),
    INDEX idx_workflow_enrollments_status (status),
    INDEX idx_workflow_enrollments_next_send (next_email_scheduled_at),
    INDEX idx_workflow_enrollments_enrolled (enrolled_at),
    FOREIGN KEY (workflow_id) REFERENCES email_workflows(id) ON DELETE CASCADE,
    FOREIGN KEY (crm_contact_id) REFERENCES crm_contacts(id) ON DELETE CASCADE,
    FOREIGN KEY (enrolled_by_user_id) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
