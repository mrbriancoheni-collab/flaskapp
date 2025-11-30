-- Migration 020: Add Conditional Branching to Email Workflows
-- Adds ability to send different emails based on whether the previous email was opened

-- Add conditional branching fields to workflow_steps
ALTER TABLE workflow_steps
ADD COLUMN condition_type ENUM('none', 'email_opened', 'email_not_opened', 'link_clicked')
    NOT NULL DEFAULT 'none'
    COMMENT 'Condition to check before sending this step'
    AFTER delay_hours;

ALTER TABLE workflow_steps
ADD COLUMN condition_wait_hours INT NOT NULL DEFAULT 24
    COMMENT 'Hours to wait before checking condition (e.g., wait 24hrs to see if previous email was opened)'
    AFTER condition_type;

ALTER TABLE workflow_steps
ADD COLUMN alt_email_template_id INT NULL
    COMMENT 'Alternative template to send if condition is not met (e.g., if email was NOT opened)'
    AFTER condition_wait_hours;

ALTER TABLE workflow_steps
ADD COLUMN condition_data JSON NULL
    COMMENT 'Additional condition data (e.g., specific URL for link_clicked condition)'
    AFTER alt_email_template_id;

-- Add foreign key for alternative template
ALTER TABLE workflow_steps
ADD CONSTRAINT fk_workflow_steps_alt_template
FOREIGN KEY (alt_email_template_id) REFERENCES email_templates(id) ON DELETE SET NULL;

-- Add index for condition type
ALTER TABLE workflow_steps
ADD INDEX idx_workflow_steps_condition (condition_type);

-- Add tracking field to workflow_enrollments to store which template path was taken
ALTER TABLE workflow_enrollments
ADD COLUMN step_history JSON NULL
    COMMENT 'History of which templates were sent at each step (for conditional branching)'
    AFTER next_email_scheduled_at;

-- Add last_email_sent_id to track the actual email sent for open tracking
ALTER TABLE workflow_enrollments
ADD COLUMN last_email_sent_id INT NULL
    COMMENT 'References emails_sent table to track opens/clicks for conditional logic'
    AFTER last_email_sent_at;

-- Add foreign key for last_email_sent_id
ALTER TABLE workflow_enrollments
ADD CONSTRAINT fk_workflow_enrollments_last_email
FOREIGN KEY (last_email_sent_id) REFERENCES emails_sent(id) ON DELETE SET NULL;

-- Add index for last_email_sent_id
ALTER TABLE workflow_enrollments
ADD INDEX idx_workflow_enrollments_last_email (last_email_sent_id);
