-- Add appointment_reminder_sent_at to crm_jobs.
-- Prevents duplicate 24-hour reminders from being sent.
-- Safe to re-run (uses IF NOT EXISTS guard via ADD COLUMN IF NOT EXISTS).

ALTER TABLE crm_jobs
    ADD COLUMN IF NOT EXISTS appointment_reminder_sent_at DATETIME NULL
    AFTER appointment_at;
