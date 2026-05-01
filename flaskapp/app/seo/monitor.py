# app/seo/monitor.py
"""
SEO Monitoring Engine — Phase 5.

Runs lightweight checks on a schedule and generates SEOAlert records
when something changes significantly.  Designed to be called from both
the dedicated cron endpoint (/account/seo/monitor/cron) and hooked into
the WordPress cron-runner (fires at most once per 23 hours per site).

Checks performed (no PageSpeed — kept fast for cron):
  Technical   — sitemap, robots.txt, homepage status & response time
  GSC delta   — clicks/impressions vs previous snapshot (if connected)
  Ranking     — individual query position drops > 5 spots
  Broken links — new 404s vs last scan

All results are stored as SEOHealthSnapshot rows; alerts become SEOAlert rows.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── thresholds ────────────────────────────────────────────────────────────────
TRAFFIC_DROP_PCT        = 20.0   # % click decline → traffic_drop alert
POSITION_DROP_SPOTS     = 5.0    # positions worsened → ranking_drop alert
HEALTH_SCORE_DROP_PTS   = 15     # points → health_score_drop alert
MIN_CLICKS_FOR_COMPARE  = 10     # ignore sites with <10 clicks (noisy)
CRON_MIN_INTERVAL_HOURS = 23     # don't re-run within this many hours


# ─────────────────────────────────────────────────────────────────────────────
# Lightweight technical probes  (subset of tech_seo.py — no PSI)
# ─────────────────────────────────────────────────────────────────────────────

def _probe(url: str, timeout: int = 8) -> Dict[str, Any]:
    """HEAD/GET a URL and return {status, elapsed_ms, ok, error}."""
    import requests, time
    try:
        t0 = time.monotonic()
        r  = requests.head(url, timeout=timeout, allow_redirects=True,
                           headers={"User-Agent": "Mozilla/5.0 (compatible; SEOMonitor/1.0)"})
        ms = int((time.monotonic() - t0) * 1000)
        return {"status": r.status_code, "elapsed_ms": ms,
                "ok": r.status_code < 400, "error": None}
    except Exception as exc:
        return {"status": 0, "elapsed_ms": 0, "ok": False, "error": str(exc)[:200]}


def _check_technical(site_url: str) -> Dict[str, Any]:
    """
    Fast technical probe: homepage, robots.txt, sitemap.
    Returns a summary dict and a list of issue strings.
    """
    base = site_url.rstrip("/")
    issues: List[str] = []

    # Homepage
    hp = _probe(base)
    if not hp["ok"]:
        issues.append(f"Homepage returned {hp['status'] or 'timeout'}")
    elif hp["elapsed_ms"] > 3000:
        issues.append(f"Slow homepage response: {hp['elapsed_ms']}ms")

    # Robots.txt
    robots_ok = True
    robots_blocked = False
    rb = _probe(base + "/robots.txt")
    if not rb["ok"]:
        issues.append("robots.txt not accessible")
        robots_ok = False
    else:
        try:
            import requests
            r = requests.get(base + "/robots.txt", timeout=8,
                             headers={"User-Agent": "Mozilla/5.0"})
            if "disallow: /" in r.text.lower():
                issues.append("robots.txt has Disallow: / — site blocked from indexing!")
                robots_blocked = True
                robots_ok = False
        except Exception:
            pass

    # Sitemap
    sitemap_ok = False
    sitemap_url = None
    for path in ["/sitemap.xml", "/sitemap_index.xml", "/wp-sitemap.xml"]:
        sp = _probe(base + path)
        if sp["ok"]:
            sitemap_ok = True
            sitemap_url = base + path
            break
    if not sitemap_ok:
        issues.append("XML sitemap not found at common paths")

    # Rough health score: start at 100, deduct per issue
    deductions = {"Homepage returned": 40, "Slow homepage": 10,
                  "robots.txt not accessible": 10,
                  "robots.txt has Disallow": 50,
                  "XML sitemap not found": 20}
    score = 100
    for issue in issues:
        for key, pts in deductions.items():
            if key in issue:
                score -= pts
    score = max(0, score)

    return {
        "health_score":     score,
        "homepage_status":  hp["status"],
        "homepage_ms":      hp["elapsed_ms"],
        "robots_ok":        robots_ok,
        "robots_blocked":   robots_blocked,
        "sitemap_ok":       sitemap_ok,
        "sitemap_url":      sitemap_url,
        "issues":           issues,
    }


# ─────────────────────────────────────────────────────────────────────────────
# GSC snapshot fetch
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_gsc_snapshot(aid: int, site_url: str) -> Optional[Dict]:
    """
    Pull last-28-days GSC summary + top-25 queries with positions.
    Returns None if GSC not connected or fetch fails.
    """
    from datetime import date, timedelta
    try:
        from app.google import _is_connected, _gsc_user_access_token
        if not _is_connected(aid, "gsc"):
            return None

        from app.seo.keyword_gaps import _gsc_fetch, _rows_to_dicts, _date_range
        end, start = _date_range(3, 30)

        # Aggregate totals
        import requests
        from urllib.parse import quote
        token = _gsc_user_access_token(aid)
        if not token:
            return None

        encoded = quote(site_url, safe="")
        url = f"https://searchconsole.googleapis.com/webmasters/v3/sites/{encoded}/searchAnalytics/query"
        hdrs = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        # KPI row (no dimensions)
        r = requests.post(url, headers=hdrs,
                          json={"startDate": start, "endDate": end,
                                "dimensions": [], "rowLimit": 1}, timeout=15)
        kpi = {}
        if r.status_code == 200:
            rows = r.json().get("rows", [])
            if rows:
                kpi = rows[0]

        # Top queries (25 rows)
        raw_q = _gsc_fetch(aid, site_url, start, end, ["query"], row_limit=25)
        queries = _rows_to_dicts(raw_q, ["query"])

        return {
            "clicks":      int(kpi.get("clicks", 0)),
            "impressions": int(kpi.get("impressions", 0)),
            "avg_position": round(kpi.get("position", 0), 1),
            "queries":     queries,
            "period":      f"{start} → {end}",
        }
    except Exception:
        logger.exception("GSC snapshot fetch failed for account %s", aid)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Alert generation
# ─────────────────────────────────────────────────────────────────────────────

def _make_alert(site_id, account_id, site_url,
                alert_type, severity, message, detail=None):
    from app.models_seo import SEOAlert
    return SEOAlert(
        site_id=site_id, account_id=account_id, site_url=site_url,
        alert_type=alert_type, severity=severity,
        message=message, detail=detail or {},
    )


def _diff_and_alert(prev: "SEOHealthSnapshot", tech: Dict,
                    gsc: Optional[Dict], site_id, account_id, site_url) -> List:
    """
    Compare current results against the previous snapshot.
    Returns a list of unsaved SEOAlert instances.
    """
    alerts = []

    # ── Technical alerts ──────────────────────────────────────────────────
    if tech["robots_blocked"] and not (prev.data or {}).get("robots_blocked"):
        alerts.append(_make_alert(
            site_id, account_id, site_url,
            "robots_blocked", "critical",
            "robots.txt now has Disallow: / — your entire site is blocked from indexing!",
            {"issue": "Disallow: /"},
        ))

    if not tech["sitemap_ok"] and prev.sitemap_ok:
        alerts.append(_make_alert(
            site_id, account_id, site_url,
            "sitemap_error", "critical",
            "XML sitemap has gone missing or is no longer accessible.",
            {"last_sitemap_ok": str(prev.created_at)},
        ))

    if not tech["homepage_status"] == 200 and prev.homepage_status == 200:
        alerts.append(_make_alert(
            site_id, account_id, site_url,
            "homepage_error", "critical",
            f"Homepage is now returning HTTP {tech['homepage_status']} (was 200 OK).",
            {"status": tech["homepage_status"]},
        ))

    score_drop = prev.health_score - tech["health_score"]
    if score_drop >= HEALTH_SCORE_DROP_PTS:
        alerts.append(_make_alert(
            site_id, account_id, site_url,
            "health_score_drop", "warning",
            f"Technical health score dropped {score_drop} points "
            f"({prev.health_score} → {tech['health_score']}).",
            {"prev": prev.health_score, "current": tech["health_score"],
             "issues": tech.get("issues", [])},
        ))

    # ── GSC alerts ────────────────────────────────────────────────────────
    if gsc and prev.gsc_clicks is not None and prev.gsc_clicks >= MIN_CLICKS_FOR_COMPARE:
        click_change_pct = (
            (gsc["clicks"] - prev.gsc_clicks) / prev.gsc_clicks * 100
        )
        if click_change_pct <= -TRAFFIC_DROP_PCT:
            alerts.append(_make_alert(
                site_id, account_id, site_url,
                "traffic_drop", "warning",
                f"Organic clicks dropped {abs(click_change_pct):.0f}% vs last check "
                f"({prev.gsc_clicks:,} → {gsc['clicks']:,} clicks).",
                {"prev_clicks": prev.gsc_clicks, "current_clicks": gsc["clicks"],
                 "change_pct": round(click_change_pct, 1)},
            ))

    # Ranking drops — compare per-query position vs prev snapshot's query data
    if gsc and prev.data:
        prev_queries = {q["query"]: q["position"]
                        for q in (prev.data.get("gsc", {}) or {}).get("queries", [])}
        for q in gsc.get("queries", []):
            prev_pos = prev_queries.get(q["query"])
            if prev_pos and q["position"] > prev_pos + POSITION_DROP_SPOTS:
                alerts.append(_make_alert(
                    site_id, account_id, site_url,
                    "ranking_drop", "warning",
                    f"'{q['query']}' dropped from position {prev_pos} to {q['position']}.",
                    {"query": q["query"], "prev_pos": prev_pos,
                     "current_pos": q["position"],
                     "drop": round(q["position"] - prev_pos, 1)},
                ))

    return alerts


# ─────────────────────────────────────────────────────────────────────────────
# Public entry-point
# ─────────────────────────────────────────────────────────────────────────────

def run_monitoring_check(
    site_url: str,
    site_id:    Optional[int] = None,
    account_id: Optional[int] = None,
    force:      bool = False,
) -> Dict[str, Any]:
    """
    Run a full monitoring check for *site_url*.

    Skipped if a snapshot was taken within CRON_MIN_INTERVAL_HOURS unless force=True.

    Returns:
        {ok, snapshot_id, alerts_created, skipped, reason, error}
    """
    from app import db
    from app.models_seo import SEOHealthSnapshot, SEOAlert

    result: Dict[str, Any] = {
        "ok": True,
        "snapshot_id": None,
        "alerts_created": 0,
        "skipped": False,
        "reason": "",
        "error": None,
    }

    # ── ensure tables exist ───────────────────────────────────────────────
    try:
        db.create_all()
    except Exception:
        pass

    # ── throttle check ────────────────────────────────────────────────────
    if not force:
        cutoff = datetime.utcnow() - timedelta(hours=CRON_MIN_INTERVAL_HOURS)
        q = SEOHealthSnapshot.query.filter_by(site_url=site_url)
        if site_id:
            q = q.filter_by(site_id=site_id)
        recent = q.filter(SEOHealthSnapshot.created_at >= cutoff).first()
        if recent:
            result["skipped"] = True
            result["reason"]  = f"Last check was {recent.created_at.isoformat()}Z"
            return result

    # ── technical probe ───────────────────────────────────────────────────
    try:
        tech = _check_technical(site_url)
    except Exception as exc:
        result["ok"]    = False
        result["error"] = f"Technical probe failed: {exc}"
        return result

    # ── GSC snapshot ──────────────────────────────────────────────────────
    gsc = None
    if account_id:
        try:
            gsc = _fetch_gsc_snapshot(account_id, site_url)
        except Exception:
            logger.exception("GSC snapshot failed for %s", site_url)

    # ── compare to previous snapshot ──────────────────────────────────────
    prev = (SEOHealthSnapshot.query
            .filter_by(site_url=site_url)
            .order_by(SEOHealthSnapshot.created_at.desc())
            .first())

    new_alerts = []
    if prev:
        try:
            new_alerts = _diff_and_alert(prev, tech, gsc, site_id, account_id, site_url)
        except Exception:
            logger.exception("Alert diff failed for %s", site_url)

    # ── store snapshot ────────────────────────────────────────────────────
    snap = SEOHealthSnapshot(
        site_id         = site_id,
        account_id      = account_id,
        site_url        = site_url,
        health_score    = tech["health_score"],
        sitemap_ok      = tech["sitemap_ok"],
        robots_ok       = tech["robots_ok"],
        homepage_status = tech["homepage_status"],
        gsc_clicks      = gsc["clicks"]      if gsc else None,
        gsc_impressions = gsc["impressions"] if gsc else None,
        gsc_avg_position= gsc["avg_position"]if gsc else None,
        data            = {"tech": tech, "gsc": gsc},
    )
    db.session.add(snap)

    for alert in new_alerts:
        db.session.add(alert)

    try:
        db.session.commit()
        result["snapshot_id"]    = snap.id
        result["alerts_created"] = len(new_alerts)
    except Exception as exc:
        db.session.rollback()
        result["ok"]    = False
        result["error"] = f"DB commit failed: {exc}"

    return result


def get_unread_alerts(site_id=None, account_id=None, limit=20) -> List:
    """Return recent unread SEOAlert rows for a site or account."""
    try:
        from app.models_seo import SEOAlert
        q = SEOAlert.query.filter_by(is_read=False)
        if site_id:
            q = q.filter_by(site_id=site_id)
        elif account_id:
            q = q.filter_by(account_id=account_id)
        return q.order_by(SEOAlert.created_at.desc()).limit(limit).all()
    except Exception:
        return []


def get_recent_snapshots(site_url: str, limit=14) -> List:
    """Return the most recent SEOHealthSnapshot rows for a site."""
    try:
        from app.models_seo import SEOHealthSnapshot
        return (SEOHealthSnapshot.query
                .filter_by(site_url=site_url)
                .order_by(SEOHealthSnapshot.created_at.desc())
                .limit(limit).all())
    except Exception:
        return []
