# app/account/competitive_routes.py
"""
Competitive Intelligence Routes

Provides UI and API endpoints for the competitive analysis dashboard.
Serves the account/competitive_dashboard.html template.

Data strategy:
  1. Try Google Ads Auction Insights via resolve_ads_context.
  2. Fall back to realistic demo data based on business industry.

Tables (created on first request if absent):
  - competitive_competitors  (tracked competitors per account)
  - competitive_alerts       (alerts surfaced to users)
"""

from __future__ import annotations

import json
import logging
import random
from datetime import datetime, timezone

from flask import Blueprint, jsonify, redirect, render_template, request, session
from sqlalchemy import text

from app import db
from app.auth.utils import current_account_id, login_required

log = logging.getLogger(__name__)

competitive_bp = Blueprint("competitive_bp", __name__, url_prefix="/account/competitive")

# ---------------------------------------------------------------------------
# Industry-based demo data
# ---------------------------------------------------------------------------

_DEMO_COMPETITORS: dict[str, list[dict]] = {
    "plumbing": [
        {"name": "ABC Plumbing & Heating", "domain": "abcplumbing.com"},
        {"name": "FastFix Plumbing", "domain": "fastfixplumbing.com"},
        {"name": "ProFlow Services", "domain": "proflowservices.com"},
        {"name": "QuickDrain Experts", "domain": "quickdrainexperts.com"},
        {"name": "AquaPro Solutions", "domain": "aquaprosolutions.com"},
    ],
    "hvac": [
        {"name": "FastFix HVAC", "domain": "fastfixhvac.com"},
        {"name": "CoolBreeze Systems", "domain": "coolbreezesystems.com"},
        {"name": "ClimateControl Pros", "domain": "climatecontrolpros.com"},
        {"name": "AirComfort Plus", "domain": "aircomfortplus.com"},
        {"name": "ThermalTech Services", "domain": "thermaltechservices.com"},
    ],
    "electrical": [
        {"name": "ProCare Electrical", "domain": "procareelectrical.com"},
        {"name": "BrightSpark Electric", "domain": "brightsparkelectric.com"},
        {"name": "PowerHouse Services", "domain": "powerhouseservices.com"},
        {"name": "VoltMaster Electric", "domain": "voltmasterelectric.com"},
        {"name": "CircuitPro Solutions", "domain": "circuitprosolutions.com"},
    ],
    "roofing": [
        {"name": "TopShield Roofing", "domain": "topshieldroofing.com"},
        {"name": "SkyHigh Contractors", "domain": "skyhighcontractors.com"},
        {"name": "RoofMaster Pro", "domain": "roofmasterpro.com"},
        {"name": "ApexRoof Solutions", "domain": "apexroofsolutions.com"},
        {"name": "RainProof Experts", "domain": "rainproofexperts.com"},
    ],
    "default": [
        {"name": "HomeService Pro", "domain": "homeservicepro.com"},
        {"name": "QuickFix Experts", "domain": "quickfixexperts.com"},
        {"name": "Reliable Home Services", "domain": "reliablehomeservices.com"},
        {"name": "Elite Home Care", "domain": "elitehomecare.com"},
        {"name": "PrimeTech Services", "domain": "primetechservices.com"},
    ],
}

_DEMO_CAMPAIGNS = ["Emergency Services", "General Repair", "Maintenance Plans", "Installation"]

_ALERT_TEMPLATES = [
    {
        "alert_type": "new_competitor",
        "severity": "high",
        "description": "New competitor entered your {campaign} campaign with {share:.0f}% impression share.",
        "recommended_action": "Increase bids by 10-15% in {campaign} to defend your position.",
    },
    {
        "alert_type": "position_threat",
        "severity": "warning",
        "description": "{name} is now outranking you {rate:.0f}% of the time in {campaign}.",
        "recommended_action": "Review ad copy quality scores and consider raising top-of-page bids.",
    },
    {
        "alert_type": "impression_share_loss",
        "severity": "info",
        "description": "{name} gained {share:.0f}% impression share in {campaign} this week.",
        "recommended_action": "Check budget pacing and keyword bids to recapture lost impressions.",
    },
]


def _get_industry(account_id: int) -> str:
    """Return the industry slug for an account, defaulting to 'default'."""
    try:
        with db.engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT industry FROM business_profiles WHERE account_id=:aid LIMIT 1"
                ),
                {"aid": account_id},
            ).mappings().first()
            if row and row.get("industry"):
                ind = str(row["industry"]).lower()
                for key in _DEMO_COMPETITORS:
                    if key in ind:
                        return key
    except Exception as exc:
        log.warning("Could not query business_profiles: %s", exc)
    return "default"


def _build_demo_competitors(industry: str) -> list[dict]:
    """Generate plausible competitor rows for demo mode."""
    pool = _DEMO_COMPETITORS.get(industry, _DEMO_COMPETITORS["default"])
    rng = random.Random(industry)  # deterministic per industry

    competitors = []
    your_share = rng.uniform(22.0, 45.0)

    for idx, info in enumerate(pool):
        share = rng.uniform(8.0, 35.0)
        overlap = rng.uniform(0.35, 0.85)
        pos_above = rng.uniform(0.20, 0.70)
        top_page = rng.uniform(0.30, 0.80)

        if pos_above > 0.60:
            threat = "high"
        elif pos_above > 0.45:
            threat = "medium"
        else:
            threat = "low"

        if idx == 0:
            trend = "increasing"
        elif idx == len(pool) - 1:
            trend = "decreasing"
        else:
            trend = "stable"

        campaigns = rng.sample(_DEMO_CAMPAIGNS, k=rng.randint(1, 3))

        competitors.append(
            {
                "id": str(idx + 1),
                "name": info["name"],
                "competitor_domain": info["domain"],
                "impression_share": round(share, 1),
                "overlap_rate": round(overlap, 2),
                "position_above_rate": round(pos_above, 2),
                "top_of_page_rate": round(top_page, 2),
                "trend": trend,
                "threat_level": threat,
                "first_seen": "2026-01-15",
                "campaigns": campaigns,
                "budget_recommendation": (
                    f"Raise bids 10-15% in {campaigns[0]} to defend your share."
                    if threat == "high"
                    else "Monitor weekly — no immediate action needed."
                ),
            }
        )

    num_threats = sum(1 for c in competitors if c["threat_level"] == "high")
    return competitors, round(your_share, 1), num_threats


def _build_demo_alerts(competitors: list[dict]) -> list[dict]:
    """Generate plausible alert rows for demo mode."""
    alerts = []
    for idx, comp in enumerate(competitors[:3]):  # at most 3 demo alerts
        tmpl = _ALERT_TEMPLATES[idx % len(_ALERT_TEMPLATES)]
        campaign = comp["campaigns"][0] if comp["campaigns"] else "General"
        alerts.append(
            {
                "id": str(idx + 1),
                "type": tmpl["alert_type"],
                "alert_type": tmpl["alert_type"],
                "severity": tmpl["severity"],
                "message": tmpl["description"].format(
                    name=comp["name"],
                    share=comp["impression_share"],
                    rate=comp["position_above_rate"] * 100,
                    campaign=campaign,
                ),
                "description": tmpl["description"].format(
                    name=comp["name"],
                    share=comp["impression_share"],
                    rate=comp["position_above_rate"] * 100,
                    campaign=campaign,
                ),
                "competitor": comp["name"],
                "competitor_domain": comp["competitor_domain"],
                "campaign": campaign,
                "recommended_action": tmpl["recommended_action"].format(
                    campaign=campaign
                ),
                "timestamp": "2026-05-20T10:00:00Z",
                "created_at": "2026-05-20T10:00:00Z",
                "addressed": False,
            }
        )
    return alerts


# ---------------------------------------------------------------------------
# Table setup
# ---------------------------------------------------------------------------

_tables_ready = False


def _ensure_tables() -> None:
    global _tables_ready
    if _tables_ready:
        return
    try:
        with db.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS competitive_competitors (
                        id            INTEGER PRIMARY KEY AUTOINCREMENT,
                        account_id    INTEGER NOT NULL,
                        name          TEXT,
                        domain        TEXT,
                        first_seen    TEXT,
                        last_seen     TEXT,
                        is_active     INTEGER DEFAULT 1,
                        meta          TEXT
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS competitive_alerts (
                        id              INTEGER PRIMARY KEY AUTOINCREMENT,
                        account_id      INTEGER NOT NULL,
                        competitor_name TEXT,
                        alert_type      TEXT,
                        message         TEXT,
                        campaign        TEXT,
                        severity        TEXT DEFAULT 'info',
                        addressed       INTEGER DEFAULT 0,
                        created_at      TEXT
                    )
                    """
                )
            )
        _tables_ready = True
    except Exception as exc:
        log.warning("Could not ensure competitive tables (may already exist): %s", exc)
        # Try PostgreSQL-compatible syntax
        try:
            with db.engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        CREATE TABLE IF NOT EXISTS competitive_competitors (
                            id            SERIAL PRIMARY KEY,
                            account_id    INTEGER NOT NULL,
                            name          TEXT,
                            domain        TEXT,
                            first_seen    TEXT,
                            last_seen     TEXT,
                            is_active     BOOLEAN DEFAULT TRUE,
                            meta          JSONB
                        )
                        """
                    )
                )
                conn.execute(
                    text(
                        """
                        CREATE TABLE IF NOT EXISTS competitive_alerts (
                            id              SERIAL PRIMARY KEY,
                            account_id      INTEGER NOT NULL,
                            competitor_name TEXT,
                            alert_type      TEXT,
                            message         TEXT,
                            campaign        TEXT,
                            severity        TEXT DEFAULT 'info',
                            addressed       BOOLEAN DEFAULT FALSE,
                            created_at      TIMESTAMPTZ DEFAULT NOW()
                        )
                        """
                    )
                )
            _tables_ready = True
        except Exception as exc2:
            log.warning("Table creation fallback also failed: %s", exc2)


# ---------------------------------------------------------------------------
# Helpers – try real Google Ads auction insights
# ---------------------------------------------------------------------------

def _try_real_competitors(account_id: int, customer_id_param: str) -> list[dict] | None:
    """
    Attempt to pull real competitor data via Google Ads Auction Insights.

    Returns None if Google Ads is not connected or the query fails.
    """
    try:
        from app.google.utils_ads import resolve_ads_context, google_ads_search
    except ImportError:
        return None

    try:
        ctx = resolve_ads_context(account_id) or {}
        cid = customer_id_param or ctx.get("customer_id")
        if not cid:
            return None

        # Basic auction insights GAQL query
        query = """
            SELECT
              auction_insight_competitor.domain,
              metrics.search_impression_share,
              metrics.search_overlap_rate,
              metrics.search_position_above_rate,
              metrics.search_top_impression_share
            FROM auction_insight_competitor
            WHERE segments.date DURING LAST_30_DAYS
        """
        results = google_ads_search(
            account_id=account_id,
            customer_id=cid,
            query=query,
        )
        if not results:
            return None

        competitors = []
        for idx, row in enumerate(results):
            domain = (
                row.get("auction_insight_competitor", {}).get("domain")
                or row.get("domain", "unknown.com")
            )
            metrics = row.get("metrics", {})
            share = float(metrics.get("search_impression_share", 0)) * 100
            overlap = float(metrics.get("search_overlap_rate", 0))
            pos_above = float(metrics.get("search_position_above_rate", 0))
            top_page = float(metrics.get("search_top_impression_share", 0)) * 100

            if pos_above > 0.60:
                threat = "high"
            elif pos_above > 0.45:
                threat = "medium"
            else:
                threat = "low"

            competitors.append(
                {
                    "id": str(idx + 1),
                    "name": domain,
                    "competitor_domain": domain,
                    "impression_share": round(share, 1),
                    "overlap_rate": round(overlap, 2),
                    "position_above_rate": round(pos_above, 2),
                    "top_of_page_rate": round(top_page, 1),
                    "trend": "stable",
                    "threat_level": threat,
                    "first_seen": None,
                    "campaigns": [],
                    "budget_recommendation": (
                        "Raise bids to defend your share."
                        if threat == "high"
                        else "Monitor weekly."
                    ),
                }
            )

        return competitors if competitors else None

    except Exception as exc:
        log.info("Real auction insights unavailable (%s); falling back to demo data.", exc)
        return None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@competitive_bp.route("/", methods=["GET"])
@competitive_bp.route("", methods=["GET"])
@login_required
def dashboard():
    """Render the competitive intelligence dashboard."""
    _ensure_tables()
    return render_template("account/competitive_dashboard.html")


@competitive_bp.route("/api/competitors", methods=["GET"])
@login_required
def get_competitors():
    """
    GET /account/competitive/api/competitors?customer_id=...

    Returns competitor list with market-share metrics.
    Tries real Google Ads data first; falls back to industry-based demo data.
    """
    _ensure_tables()
    account_id = current_account_id()
    customer_id_param = request.args.get("customer_id", "")

    is_demo = False

    # 1. Try real Google Ads
    competitors = _try_real_competitors(account_id, customer_id_param)

    if competitors is None:
        # 2. Fall back to demo data based on industry
        is_demo = True
        industry = _get_industry(account_id)
        competitors, your_share, num_threats = _build_demo_competitors(industry)
    else:
        your_share = 0.0
        num_threats = sum(1 for c in competitors if c.get("threat_level") == "high")

    # Also load any manually-tracked competitors from DB and merge
    try:
        with db.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, name, domain, first_seen FROM competitive_competitors "
                    "WHERE account_id=:aid AND is_active=1"
                ),
                {"aid": account_id},
            ).mappings().all()
            existing_domains = {c["competitor_domain"] for c in competitors}
            for row in rows:
                if row["domain"] and row["domain"] not in existing_domains:
                    competitors.append(
                        {
                            "id": str(row["id"]),
                            "name": row["name"] or row["domain"],
                            "competitor_domain": row["domain"],
                            "impression_share": 0.0,
                            "overlap_rate": 0.0,
                            "position_above_rate": 0.0,
                            "top_of_page_rate": 0.0,
                            "trend": "unknown",
                            "threat_level": "low",
                            "first_seen": row["first_seen"],
                            "campaigns": [],
                            "budget_recommendation": "Manually tracked — no metrics yet.",
                        }
                    )
    except Exception as exc:
        log.warning("Could not load manual competitors from DB: %s", exc)

    return jsonify(
        {
            "ok": True,
            "success": True,
            "is_demo": is_demo,
            "your_share": your_share,
            "num_competitors": len(competitors),
            "num_threats": num_threats,
            "competitors": competitors,
        }
    )


@competitive_bp.route("/api/add-competitor", methods=["POST"])
@login_required
def add_competitor():
    """
    POST /account/competitive/api/add-competitor

    Body JSON: { customer_id, competitor_domain, company_name, notes }
    """
    _ensure_tables()
    account_id = current_account_id()
    data = request.get_json(silent=True) or {}

    domain = (data.get("competitor_domain") or "").strip()
    name = (data.get("company_name") or domain).strip()

    if not domain:
        return jsonify({"ok": False, "success": False, "error": "competitor_domain is required"}), 400

    now_str = datetime.now(timezone.utc).isoformat()

    try:
        with db.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO competitive_competitors
                        (account_id, name, domain, first_seen, last_seen, is_active, meta)
                    VALUES
                        (:aid, :name, :domain, :now, :now, 1, :meta)
                    """
                ),
                {
                    "aid": account_id,
                    "name": name,
                    "domain": domain,
                    "now": now_str,
                    "meta": json.dumps({"notes": data.get("notes", "")}),
                },
            )
        return jsonify({"ok": True, "success": True})
    except Exception as exc:
        log.exception("add_competitor error: %s", exc)
        return jsonify({"ok": False, "success": False, "error": str(exc)}), 500


@competitive_bp.route("/api/alerts", methods=["GET"])
@login_required
def get_alerts():
    """
    GET /account/competitive/api/alerts?customer_id=...&unaddressed_only=true

    Returns competitive alerts. Falls back to demo alerts if none in DB.
    """
    _ensure_tables()
    account_id = current_account_id()
    unaddressed_only = request.args.get("unaddressed_only", "true").lower() == "true"

    db_alerts = []
    try:
        where_extra = "AND addressed = 0" if unaddressed_only else ""
        with db.engine.connect() as conn:
            rows = conn.execute(
                text(
                    f"""
                    SELECT id, competitor_name, alert_type, message, campaign,
                           severity, addressed, created_at
                    FROM competitive_alerts
                    WHERE account_id = :aid {where_extra}
                    ORDER BY created_at DESC
                    LIMIT 50
                    """
                ),
                {"aid": account_id},
            ).mappings().all()
            for row in rows:
                db_alerts.append(
                    {
                        "id": str(row["id"]),
                        "type": row["alert_type"],
                        "alert_type": row["alert_type"],
                        "severity": row["severity"] or "info",
                        "message": row["message"],
                        "description": row["message"],
                        "competitor": row["competitor_name"],
                        "competitor_domain": row["competitor_name"],
                        "campaign": row["campaign"],
                        "timestamp": str(row["created_at"]),
                        "created_at": str(row["created_at"]),
                        "addressed": bool(row["addressed"]),
                        "recommended_action": "Review competitive position in this campaign.",
                    }
                )
    except Exception as exc:
        log.warning("Could not load alerts from DB: %s", exc)

    is_demo = False
    if not db_alerts:
        # Fall back to demo alerts derived from demo competitors
        is_demo = True
        industry = _get_industry(account_id)
        competitors, _, _ = _build_demo_competitors(industry)
        db_alerts = _build_demo_alerts(competitors)

    return jsonify(
        {
            "ok": True,
            "success": True,
            "is_demo": is_demo,
            "alerts": db_alerts,
        }
    )


@competitive_bp.route("/api/mark-addressed/<alert_id>", methods=["POST"])
@login_required
def mark_addressed(alert_id: str):
    """
    POST /account/competitive/api/mark-addressed/<alert_id>

    Mark a competitive alert as addressed.
    """
    _ensure_tables()
    account_id = current_account_id()

    # Demo alert IDs are small integers – silently succeed
    try:
        int_id = int(alert_id)
    except (TypeError, ValueError):
        return jsonify({"ok": True, "success": True, "note": "demo alert – no DB update needed"})

    try:
        with db.engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE competitive_alerts SET addressed=1 "
                    "WHERE id=:id AND account_id=:aid"
                ),
                {"id": int_id, "aid": account_id},
            )
        return jsonify({"ok": True, "success": True})
    except Exception as exc:
        log.exception("mark_addressed error: %s", exc)
        return jsonify({"ok": False, "success": False, "error": str(exc)}), 500


@competitive_bp.route("/api/analyze", methods=["POST"])
@login_required
def analyze():
    """
    POST /account/competitive/api/analyze

    Re-analyze competitor landscape and refresh DB state.
    Returns a summary of what changed.
    """
    _ensure_tables()
    account_id = current_account_id()
    data = request.get_json(silent=True) or {}
    customer_id_param = data.get("customer_id", "")

    try:
        competitors = _try_real_competitors(account_id, customer_id_param)
        is_demo = competitors is None

        if is_demo:
            industry = _get_industry(account_id)
            competitors, your_share, num_threats = _build_demo_competitors(industry)
        else:
            your_share = 0.0
            num_threats = sum(1 for c in competitors if c.get("threat_level") == "high")

        # Upsert new high-threat alerts
        new_alerts = 0
        now_str = datetime.now(timezone.utc).isoformat()
        for comp in competitors:
            if comp.get("threat_level") == "high":
                try:
                    with db.engine.begin() as conn:
                        conn.execute(
                            text(
                                """
                                INSERT INTO competitive_alerts
                                    (account_id, competitor_name, alert_type, message,
                                     campaign, severity, addressed, created_at)
                                VALUES
                                    (:aid, :name, 'position_threat',
                                     :msg, :camp, 'high', 0, :now)
                                """
                            ),
                            {
                                "aid": account_id,
                                "name": comp.get("competitor_domain", ""),
                                "msg": (
                                    f"{comp.get('name', comp.get('competitor_domain'))} "
                                    f"has {comp.get('impression_share', 0):.1f}% impression share."
                                ),
                                "camp": (
                                    comp["campaigns"][0] if comp.get("campaigns") else "General"
                                ),
                                "now": now_str,
                            },
                        )
                    new_alerts += 1
                except Exception as exc:
                    log.warning("Could not insert alert for %s: %s", comp.get("name"), exc)

        return jsonify(
            {
                "ok": True,
                "success": True,
                "is_demo": is_demo,
                "competitors_found": len(competitors),
                "new_alerts": new_alerts,
                "num_threats": num_threats,
                "your_share": your_share,
            }
        )

    except Exception as exc:
        log.exception("analyze error: %s", exc)
        return jsonify({"ok": False, "success": False, "error": str(exc)}), 500
