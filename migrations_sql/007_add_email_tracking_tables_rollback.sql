-- Rollback: Remove email tracking tables
-- Date: 2025-10-28

DROP TABLE IF EXISTS email_clicks;
DROP TABLE IF EXISTS email_opens;
DROP TABLE IF EXISTS emails_sent;
