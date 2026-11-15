-- Digest send safety tables (Item 3)
-- Run once on deploy. All tables use IF NOT EXISTS / IGNORE for idempotency.

-- ── 1. Digest send log ────────────────────────────────────────────────────────
-- One row per (account, date, channel). Unique key enforces idempotency.
-- If the row already exists, INSERT IGNORE skips the send.
CREATE TABLE IF NOT EXISTS digest_send_log (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    account_id      INT          NOT NULL,
    digest_date     DATE         NOT NULL,
    channel         VARCHAR(20)  NOT NULL DEFAULT 'sms',   -- sms | email | both
    recipient       VARCHAR(255) NOT NULL DEFAULT '',
    status          VARCHAR(32)  NOT NULL DEFAULT 'sent',
        -- sent | failed | blocked_idempotent | blocked_circuit |
        -- blocked_approval | blocked_cap | blocked_number_check
    blocked_reason  TEXT,
    confidence      DECIMAL(4,3),                          -- from render_digest_structured
    created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_digest_send (account_id, digest_date, channel)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- If the table already exists but lacks newer columns, add them silently.
-- (MySQL ALTER IGNORE is not available; use a stored procedure trick.)
SET @col_exists = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME   = 'digest_send_log'
      AND COLUMN_NAME  = 'status'
);
SET @sql = IF(@col_exists = 0,
    'ALTER TABLE digest_send_log ADD COLUMN status VARCHAR(32) NOT NULL DEFAULT ''sent'' AFTER recipient',
    'SELECT 1'
);
PREPARE _stmt FROM @sql; EXECUTE _stmt; DEALLOCATE PREPARE _stmt;

SET @col_exists = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME   = 'digest_send_log'
      AND COLUMN_NAME  = 'blocked_reason'
);
SET @sql = IF(@col_exists = 0,
    'ALTER TABLE digest_send_log ADD COLUMN blocked_reason TEXT AFTER status',
    'SELECT 1'
);
PREPARE _stmt FROM @sql; EXECUTE _stmt; DEALLOCATE PREPARE _stmt;

SET @col_exists = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME   = 'digest_send_log'
      AND COLUMN_NAME  = 'confidence'
);
SET @sql = IF(@col_exists = 0,
    'ALTER TABLE digest_send_log ADD COLUMN confidence DECIMAL(4,3) AFTER blocked_reason',
    'SELECT 1'
);
PREPARE _stmt FROM @sql; EXECUTE _stmt; DEALLOCATE PREPARE _stmt;


-- ── 2. Circuit breaker ────────────────────────────────────────────────────────
-- One row per account. tripped_at IS NOT NULL means the breaker is open (paused).
CREATE TABLE IF NOT EXISTS digest_circuit_breaker (
    account_id          INT         NOT NULL PRIMARY KEY,
    consecutive_failures INT        NOT NULL DEFAULT 0,
    tripped_at          DATETIME,                    -- NULL = closed (ok to send)
    cooldown_seconds    INT         NOT NULL DEFAULT 86400,  -- 24 h default
    updated_at          DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ── 3. Per-tenant AI spend cap ────────────────────────────────────────────────
-- Tracks estimated AI API spend (in cents) per account per month.
CREATE TABLE IF NOT EXISTS digest_ai_spend (
    account_id      INT         NOT NULL,
    period          CHAR(7)     NOT NULL,   -- YYYY-MM
    spend_cents     INT         NOT NULL DEFAULT 0,
    cap_cents       INT         NOT NULL DEFAULT 500,  -- $5.00 default monthly cap
    updated_at      DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (account_id, period)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ── 4. Digest approval queue ──────────────────────────────────────────────────
-- Rows inserted when approval is required before sending.
CREATE TABLE IF NOT EXISTS digest_approval_queue (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    account_id      INT          NOT NULL,
    digest_date     DATE         NOT NULL,
    channel         VARCHAR(20)  NOT NULL DEFAULT 'sms',
    reason          VARCHAR(64)  NOT NULL,
        -- first_digest | low_confidence | money_change | number_check_failed
    status          VARCHAR(16)  NOT NULL DEFAULT 'pending',
        -- pending | approved | rejected | auto_expired
    structured_json MEDIUMTEXT,              -- JSON from render_digest_structured
    confidence      DECIMAL(4,3),
    created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at     DATETIME,
    resolved_by     INT,                     -- user_id of approver
    KEY ix_approval_account (account_id),
    KEY ix_approval_status  (status),
    UNIQUE KEY uq_approval (account_id, digest_date, channel, reason)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
