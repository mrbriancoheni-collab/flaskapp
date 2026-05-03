-- Rollback for migration 024

ALTER TABLE lead_ingest
  DROP COLUMN IF EXISTS service_type,
  DROP COLUMN IF EXISTS lead_cost,
  DROP COLUMN IF EXISTS status,
  DROP COLUMN IF EXISTS job_notes,
  DROP COLUMN IF EXISTS contacted_at,
  DROP COLUMN IF EXISTS booked_at,
  DROP COLUMN IF EXISTS completed_at;

DROP TABLE IF EXISTS lead_intake_configs;

ALTER TABLE review_requests
  DROP COLUMN IF EXISTS customer_name,
  DROP COLUMN IF EXISTS job_type,
  DROP COLUMN IF EXISTS review_link_google,
  DROP COLUMN IF EXISTS review_link_yelp;

ALTER TABLE ai_actions
  DROP COLUMN IF EXISTS approval_token,
  DROP COLUMN IF EXISTS approval_sent_at,
  DROP COLUMN IF EXISTS approved_at,
  DROP COLUMN IF EXISTS rejected_at;
