-- Migration: Add unique constraint on lead_contact_emails(contact_id, sequence_step)
-- Prevents duplicate emails to the same contact for the same sequence step at the DB level
--
-- Run: mysql -u root -p fieldsprout < migrations_sql/023_add_lead_contact_emails_unique_constraint.sql

-- First, remove any existing duplicate records (keep the first one based on created_at)
-- This is necessary before adding the unique constraint
DELETE lce1 FROM lead_contact_emails lce1
INNER JOIN lead_contact_emails lce2
WHERE lce1.contact_id = lce2.contact_id
  AND lce1.sequence_step = lce2.sequence_step
  AND lce1.id > lce2.id;

-- Add unique constraint on (contact_id, sequence_step)
-- This prevents sending the same sequence step to the same contact twice
ALTER TABLE lead_contact_emails
ADD CONSTRAINT uq_lead_contact_emails_contact_step
UNIQUE (contact_id, sequence_step);

-- Verify the constraint was added
SHOW INDEX FROM lead_contact_emails WHERE Key_name = 'uq_lead_contact_emails_contact_step';
