-- Rollback: Remove unique constraint on lead_contact_emails(contact_id, sequence_step)
--
-- Run: mysql -u root -p fieldsprout < migrations_sql/023_add_lead_contact_emails_unique_constraint_rollback.sql

ALTER TABLE lead_contact_emails
DROP INDEX uq_lead_contact_emails_contact_step;
