# app/social_listen/models.py
"""
DB table definitions for social listening.
Uses raw SQL DDL via db.engine.begin() — no ORM models.
"""
from __future__ import annotations

import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)

_CONFIG_DDL = """
CREATE TABLE IF NOT EXISTS social_listen_config (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    user_id         INT          NOT NULL,
    topics          TEXT         NOT NULL DEFAULT '[]',
    sources         TEXT         NOT NULL DEFAULT '[]',
    email_recipient VARCHAR(255) NOT NULL DEFAULT '',
    schedule        VARCHAR(10)  NOT NULL DEFAULT 'daily',
    enabled         TINYINT      NOT NULL DEFAULT 1,
    created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_slc_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

_OPPORTUNITIES_DDL = """
CREATE TABLE IF NOT EXISTS social_opportunities (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    user_id          INT           NOT NULL,
    source           VARCHAR(50)   NOT NULL,
    source_url       VARCHAR(1000) NOT NULL DEFAULT '',
    author           VARCHAR(200)  NOT NULL DEFAULT '',
    original_content TEXT,
    topic            VARCHAR(200)  NOT NULL DEFAULT '',
    ai_score         FLOAT         NOT NULL DEFAULT 5.0,
    ai_reason        TEXT,
    draft_comment    TEXT,
    draft_post       TEXT,
    user_take        TEXT,
    status           VARCHAR(20)   NOT NULL DEFAULT 'new',
    email_token      VARCHAR(64)   NULL,
    posted_at        DATETIME      NULL,
    created_at       DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_opp_token (email_token),
    KEY ix_opp_user_status (user_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""


def ensure_tables() -> None:
    """Create both social listening tables if they don't already exist."""
    from app import db
    try:
        with db.engine.begin() as conn:
            conn.execute(text(_CONFIG_DDL))
            conn.execute(text(_OPPORTUNITIES_DDL))
        logger.info("social_listen tables ensured")
    except Exception as exc:
        logger.warning("social_listen table creation failed: %s", exc)
