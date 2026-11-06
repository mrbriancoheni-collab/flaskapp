"""Called by cron_tasks.run_hourly — SMS alerts for new pending actions."""
import logging

log = logging.getLogger(__name__)


def notify_pending_actions(app, db) -> None:
    """Send SMS to account owners for pending actions created in the last hour."""
    try:
        from sqlalchemy import text
        with db.engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT account_id, COUNT(*) AS cnt, MAX(title) AS latest_title
                FROM agent_decisions
                WHERE status = 'pending'
                  AND requires_approval = TRUE
                  AND created_at > NOW() - INTERVAL 1 HOUR
                GROUP BY account_id
            """)).fetchall()
        for row in rows:
            try:
                from app.services.sms_service import notify_action_ready
                notify_action_ready(int(row[0]), str(row[2] or ""), int(row[1]))
            except Exception as e:
                log.warning("notify_pending_actions per-account error (aid=%s): %s", row[0], e)
    except Exception as e:
        log.warning("notify_pending_actions failed: %s", e)


def check_cpl_spikes(app, db) -> None:
    """Send SMS when any account's recent daily CPL is >40% above their 30-day average."""
    try:
        from sqlalchemy import text
        with db.engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT
                    r.account_id,
                    a.detected_trade,
                    r.today_cpl,
                    r.avg_cpl
                FROM (
                    SELECT
                        account_id,
                        SUM(CASE WHEN date = CURDATE() - INTERVAL 1 DAY THEN cost_micros ELSE 0 END) / 1e6
                            / NULLIF(SUM(CASE WHEN date = CURDATE() - INTERVAL 1 DAY THEN conversions ELSE 0 END), 0) AS today_cpl,
                        AVG(cost_micros / 1e6) / NULLIF(AVG(conversions), 0) AS avg_cpl
                    FROM google_ads_metrics
                    WHERE date >= CURDATE() - INTERVAL 31 DAY
                    GROUP BY account_id
                ) r
                JOIN accounts a ON a.id = r.account_id
                WHERE r.today_cpl IS NOT NULL
                  AND r.avg_cpl IS NOT NULL
                  AND r.avg_cpl > 0
                  AND r.today_cpl > r.avg_cpl * 1.4
            """)).fetchall()
        for row in rows:
            try:
                from app.services.sms_service import notify_cpl_spike
                notify_cpl_spike(int(row[0]), str(row[1] or "trade"), float(row[2]), float(row[3]))
            except Exception as e:
                log.warning("check_cpl_spikes per-account error (aid=%s): %s", row[0], e)
    except Exception as e:
        log.warning("check_cpl_spikes failed: %s", e)
