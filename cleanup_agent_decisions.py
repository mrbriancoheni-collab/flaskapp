#!/usr/bin/env python3
"""
Cleanup: Fix risk levels and remove duplicate pending agent decisions.

Run this once to:
1. Update any legacy 'medium'/'critical' risk_level values to 'high'
2. Delete duplicate pending decisions (keep only most recent per account+decision_type+campaign)

Usage:
    python3 cleanup_agent_decisions.py
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'flaskapp'))

from app import create_app
from sqlalchemy import text

app = create_app()
with app.app_context():
    from app import db

    # 1. Fix legacy risk levels
    result = db.session.execute(text("""
        UPDATE agent_decisions
        SET risk_level = 'high'
        WHERE risk_level IN ('medium', 'critical')
    """))
    print(f"Updated {result.rowcount} medium/critical decisions to 'high'")
    db.session.commit()

    # 2. Remove duplicates (keep most recent per account+type+campaign)
    result = db.session.execute(text("""
        DELETE FROM agent_decisions
        WHERE status = 'pending'
          AND id NOT IN (
            SELECT max_id FROM (
              SELECT MAX(id) AS max_id
              FROM agent_decisions
              WHERE status = 'pending'
              GROUP BY account_id, decision_type, IFNULL(campaign_id, '')
            ) AS keep_rows
          )
    """))
    print(f"Deleted {result.rowcount} duplicate pending decisions")
    db.session.commit()

    # 3. Report
    row = db.session.execute(text("""
        SELECT 
            COUNT(*) AS total,
            SUM(CASE WHEN risk_level = 'high' THEN 1 ELSE 0 END) AS high_count,
            SUM(CASE WHEN risk_level = 'low' THEN 1 ELSE 0 END) AS low_count
        FROM agent_decisions
        WHERE status = 'pending'
    """)).fetchone()
    print(f"Remaining pending: {row[0]} total ({row[1]} high, {row[2]} low)")
    print("Done!")
