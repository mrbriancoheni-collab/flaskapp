-- Add sharon@visitingangels.com to unsubscribe list
-- This ensures this email address will never receive emails from us again

-- Insert into email_unsubscribes table
INSERT INTO email_unsubscribes (email, reason, created_at)
VALUES (
    'sharon@visitingangels.com',
    'User requested unsubscribe',
    NOW()
)
ON DUPLICATE KEY UPDATE
    reason = 'User requested unsubscribe',
    created_at = NOW();

-- Verify the insert
SELECT * FROM email_unsubscribes WHERE email = 'sharon@visitingangels.com';

-- Also check if this email has any existing contacts
SELECT lc.id, lc.email, lc.name, l.company_name, lc.email_status
FROM lead_contacts lc
JOIN leads l ON lc.lead_id = l.id
WHERE lc.email = 'sharon@visitingangels.com';

-- Mark any existing contacts as unsubscribed
UPDATE lead_contacts
SET email_status = 'unsubscribed',
    unsubscribed_at = NOW()
WHERE email = 'sharon@visitingangels.com';

-- Verify the update
SELECT 'UNSUBSCRIBE COMPLETE' AS status;
SELECT email, reason, created_at FROM email_unsubscribes WHERE email = 'sharon@visitingangels.com';
