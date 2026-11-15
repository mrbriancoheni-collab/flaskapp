-- Add phone column for SMS notifications
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS phone VARCHAR(20) DEFAULT NULL;
