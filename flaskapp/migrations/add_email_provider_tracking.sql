-- Add email provider tracking to lead_contact_emails table
-- This allows tracking which email service provider (Brevo, Mailgun) sent each email

-- Add to_email column to store recipient email
ALTER TABLE lead_contact_emails
ADD COLUMN IF NOT EXISTS to_email VARCHAR(255);

-- Add email_provider column to track which provider sent the email
ALTER TABLE lead_contact_emails
ADD COLUMN IF NOT EXISTS email_provider VARCHAR(50) DEFAULT 'mailgun';

-- Add brevo_message_id column for Brevo API tracking
ALTER TABLE lead_contact_emails
ADD COLUMN IF NOT EXISTS brevo_message_id VARCHAR(255);

-- Create index on brevo_message_id for faster lookups
CREATE INDEX IF NOT EXISTS idx_lead_contact_emails_brevo_message_id
ON lead_contact_emails(brevo_message_id);

-- Update existing records to have mailgun as the default provider
UPDATE lead_contact_emails
SET email_provider = 'mailgun'
WHERE email_provider IS NULL;
