"""Performance timeline: 90-day CPL + spend trend with RevForge start marker."""
from __future__ import annotations

import logging
from datetime import date, timedelta

from flask import render_template

from app import db
from app.auth.utils import login_required, current_account_id
from app.account import account_bp

log = logging.getLogger(__name__)


@account_bp.route("/performance", endpoint="performance_timeline")
@login_required
def performance_timeline():
    aid = current_account_id()
    rows = []
    account_created = None
    try:
        from sqlalchemy import text
        with db.engine.connect() as conn:
            # Get account creation date
            r = conn.execute(
                text("SELECT created_at FROM accounts WHERE id = :aid"),
                {"aid": aid},
            ).fetchone()
            if r:
                account_created = r[0]

            # Aggregate daily spend + conversions over last 90 days
            cutoff = date.today() - timedelta(days=90)
            raw = conn.execute(
                text("""
                    SELECT
                        date,
                        SUM(cost_micros) / 1e6 AS spend,
                        SUM(conversions)        AS convs
                    FROM google_ads_metrics
                    WHERE account_id = :aid AND date >= :cutoff
                    GROUP BY date
                    ORDER BY date ASC
                """),
                {"aid": aid, "cutoff": str(cutoff)},
            ).fetchall()
            for r in raw:
                spend = float(r[1] or 0)
                convs = float(r[2] or 0)
                cpl = round(spend / convs, 2) if convs > 0 else None
                rows.append({"date": str(r[0]), "spend": round(spend, 2), "cpl": cpl})
    except Exception as e:
        log.warning("performance_timeline query failed: %s", e)

    return render_template(
        "account/performance_timeline.html",
        rows=rows,
        account_created=account_created,
    )
