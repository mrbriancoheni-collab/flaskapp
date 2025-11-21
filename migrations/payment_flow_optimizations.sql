-- Payment Flow Optimizations Migration
-- Run this script to apply all database changes for the payment flow optimizations

-- Step 1: Add first_payment_at column to stripe_customers
ALTER TABLE stripe_customers
ADD COLUMN first_payment_at TIMESTAMP NULL;

-- Backfill first_payment_at for existing customers
UPDATE stripe_customers sc
SET first_payment_at = (
    SELECT MIN(p.created_at)
    FROM payments p
    WHERE p.user_id = sc.user_id
    AND p.status = 'paid'
);

-- Step 2: Create composite indexes for better query performance
CREATE INDEX IF NOT EXISTS idx_subscriptions_user_status ON subscriptions(user_id, status);
CREATE INDEX IF NOT EXISTS idx_payments_user_status ON payments(user_id, status);

-- Step 3: Create stripe_webhook_events table for idempotency
CREATE TABLE IF NOT EXISTS stripe_webhook_events (
    id SERIAL PRIMARY KEY,
    event_id VARCHAR(64) NOT NULL UNIQUE,
    event_type VARCHAR(64) NOT NULL,
    processed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(32) NOT NULL DEFAULT 'processed',
    error_message TEXT NULL,
    CONSTRAINT idx_webhook_events_event_id UNIQUE (event_id)
);

CREATE INDEX IF NOT EXISTS idx_webhook_events_event_type ON stripe_webhook_events(event_type);
CREATE INDEX IF NOT EXISTS idx_webhook_events_processed_at ON stripe_webhook_events(processed_at);

-- Step 4: Create email_queue table for background email processing
CREATE TABLE IF NOT EXISTS email_queue (
    id SERIAL PRIMARY KEY,
    to_email VARCHAR(255) NOT NULL,
    subject VARCHAR(255) NOT NULL,
    html_body TEXT NOT NULL,
    text_body TEXT NULL,
    use_bulk_credentials BOOLEAN NOT NULL DEFAULT FALSE,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    error_message TEXT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sent_at TIMESTAMP NULL
);

CREATE INDEX IF NOT EXISTS idx_email_queue_status ON email_queue(status);
CREATE INDEX IF NOT EXISTS idx_email_queue_status_created ON email_queue(status, created_at);

-- Step 5: Add comments for documentation
COMMENT ON COLUMN stripe_customers.first_payment_at IS 'Optimization: Tracks first successful payment to avoid COUNT queries';
COMMENT ON TABLE stripe_webhook_events IS 'Tracks processed webhook events to ensure idempotency and prevent duplicate processing';
COMMENT ON TABLE email_queue IS 'Background email queue to decouple email delivery from critical payment flows';

-- Step 6: Verify indexes were created
SELECT
    tablename,
    indexname,
    indexdef
FROM pg_indexes
WHERE schemaname = 'public'
AND tablename IN ('stripe_customers', 'subscriptions', 'payments', 'stripe_webhook_events', 'email_queue')
ORDER BY tablename, indexname;

-- Migration complete
SELECT 'Payment flow optimizations applied successfully!' as status;
