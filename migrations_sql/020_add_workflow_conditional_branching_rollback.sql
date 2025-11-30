-- Rollback Migration 020: Remove Conditional Branching from Email Workflows

-- Drop foreign keys first
ALTER TABLE workflow_enrollments DROP FOREIGN KEY IF EXISTS fk_workflow_enrollments_last_email;
ALTER TABLE workflow_steps DROP FOREIGN KEY IF EXISTS fk_workflow_steps_alt_template;

-- Drop indexes
ALTER TABLE workflow_enrollments DROP INDEX IF EXISTS idx_workflow_enrollments_last_email;
ALTER TABLE workflow_steps DROP INDEX IF EXISTS idx_workflow_steps_condition;

-- Drop columns from workflow_enrollments
ALTER TABLE workflow_enrollments DROP COLUMN IF EXISTS last_email_sent_id;
ALTER TABLE workflow_enrollments DROP COLUMN IF EXISTS step_history;

-- Drop columns from workflow_steps
ALTER TABLE workflow_steps DROP COLUMN IF EXISTS condition_data;
ALTER TABLE workflow_steps DROP COLUMN IF EXISTS alt_email_template_id;
ALTER TABLE workflow_steps DROP COLUMN IF EXISTS condition_wait_hours;
ALTER TABLE workflow_steps DROP COLUMN IF EXISTS condition_type;
