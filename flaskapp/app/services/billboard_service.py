"""
Billboard Ads service layer.

Provides inventory browsing, campaign management, cost estimation,
and AI creative generation for the OOH billboard platform.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Optional

from sqlalchemy import text

from app import db

log = logging.getLogger(__name__)

_PLACEHOLDER_COLORS = {
    "green": "#1A5C35",
    "blue": "#1E5FA8",
    "amber": "#D97706",
    "slate": "#475569",
}

_AI_SYSTEM_PROMPT = """You are an expert out-of-home (OOH) advertising copywriter specializing in trade contractor businesses (HVAC, plumbing, electrical, roofing, pest control, landscaping).

Generate billboard copy that follows the 7-word rule and is impossible to misread at 70 mph.

Return ONLY valid JSON with this exact structure:
{
  "headline": "...",
  "subtext": "...",
  "cta": "...",
  "design_tip": "..."
}

STRICT RULES:
- headline: maximum 7 words, bold and punchy, no punctuation except exclamation mark
- subtext: maximum 10 words, one supporting benefit or trust signal
- cta: maximum 5 words — phone number format "Call 555-0100" or simple URL "GetRevForge.com"
- design_tip: one sentence about color, contrast, or layout specific to this copy
- Use title case for headline
- Include the city or area in headline or subtext when possible
- Focus on the top emotional driver: peace of mind, speed, price, or trust"""


def _row_to_dict(row) -> dict:
    if row is None:
        return {}
    if hasattr(row, "_mapping"):
        return dict(row._mapping)
    return dict(row)


def get_cities() -> list[dict]:
    rows = db.session.execute(
        text("SELECT DISTINCT city, state FROM billboard_locations WHERE active = 1 ORDER BY state, city")
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_locations(
    city: str | None = None,
    state: str | None = None,
    screen_type: str | None = None,
    max_cpp: float | None = None,
) -> list[dict]:
    clauses = ["active = 1"]
    params: dict[str, Any] = {}

    if city:
        clauses.append("city = :city")
        params["city"] = city
    if state:
        clauses.append("state = :state")
        params["state"] = state
    if screen_type:
        clauses.append("screen_type = :screen_type")
        params["screen_type"] = screen_type
    if max_cpp is not None:
        clauses.append("cpp <= :max_cpp")
        params["max_cpp"] = max_cpp

    where = " AND ".join(clauses)
    rows = db.session.execute(
        text(f"SELECT * FROM billboard_locations WHERE {where} ORDER BY city, name"),
        params,
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_location(location_id: int) -> dict:
    row = db.session.execute(
        text("SELECT * FROM billboard_locations WHERE id = :id AND active = 1"),
        {"id": location_id},
    ).fetchone()
    return _row_to_dict(row)


def estimate_campaign_cost(location_ids: list[int], days: int) -> dict:
    if not location_ids or days <= 0:
        return {"total_cost": 0, "total_plays": 0, "total_impressions": 0, "breakdown": []}

    placeholders = ", ".join(str(int(i)) for i in location_ids)
    rows = db.session.execute(
        text(f"SELECT id, name, city, state, cpp, plays_per_day, screen_type FROM billboard_locations WHERE id IN ({placeholders}) AND active = 1")
    ).fetchall()

    breakdown = []
    total_cost = 0.0
    total_plays = 0
    for r in rows:
        d = _row_to_dict(r)
        ppd = int(d.get("plays_per_day") or 1)
        cpp = float(d.get("cpp") or 1.0)
        total_loc_plays = ppd * days
        cost = round(total_loc_plays * cpp, 2)
        impressions = int(total_loc_plays * 1.8)
        total_cost += cost
        total_plays += total_loc_plays
        breakdown.append({
            "location_id": d["id"],
            "name": d["name"],
            "city": d["city"],
            "state": d["state"],
            "screen_type": d["screen_type"],
            "plays": total_loc_plays,
            "impressions": impressions,
            "cost": cost,
        })

    return {
        "total_cost": round(total_cost, 2),
        "total_plays": total_plays,
        "total_impressions": int(total_plays * 1.8),
        "days": days,
        "breakdown": breakdown,
    }


def create_campaign(
    account_id: int,
    name: str,
    objective: str,
    start_date: str,
    end_date: str,
    location_ids: list[int],
    creative_headline: str,
    creative_subtext: str,
    creative_cta: str,
    creative_type: str = "ai_generated",
) -> int:
    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()
    days = (end - start).days + 1

    estimate = estimate_campaign_cost(location_ids, days)
    total_budget = estimate["total_cost"]

    result = db.session.execute(
        text("""
            INSERT INTO billboard_campaigns
              (account_id, name, objective, status, start_date, end_date,
               total_budget, creative_headline, creative_subtext, creative_cta, creative_type)
            VALUES
              (:account_id, :name, :objective, 'active', :start_date, :end_date,
               :total_budget, :headline, :subtext, :cta, :creative_type)
        """),
        {
            "account_id": account_id,
            "name": name,
            "objective": objective,
            "start_date": start_date,
            "end_date": end_date,
            "total_budget": total_budget,
            "headline": creative_headline[:100],
            "subtext": creative_subtext[:200],
            "cta": creative_cta[:60],
            "creative_type": creative_type,
        },
    )
    campaign_id = result.lastrowid

    loc_rows = db.session.execute(
        text(f"SELECT id, cpp, plays_per_day FROM billboard_locations WHERE id IN ({', '.join(str(int(i)) for i in location_ids)})"),
    ).fetchall()
    loc_map = {r["id"]: _row_to_dict(r) for r in loc_rows}

    for loc_id in location_ids:
        loc = loc_map.get(int(loc_id))
        if not loc:
            continue
        ppd = int(loc.get("plays_per_day") or 480)
        cpp = float(loc.get("cpp") or 1.0)
        total_plays = ppd * days
        cost = round(total_plays * cpp, 2)
        db.session.execute(
            text("""
                INSERT INTO billboard_campaign_locations
                  (campaign_id, location_id, plays_per_day, cpp, campaign_days,
                   estimated_total_plays, estimated_impressions, estimated_cost)
                VALUES
                  (:campaign_id, :location_id, :ppd, :cpp, :days,
                   :total_plays, :impressions, :cost)
            """),
            {
                "campaign_id": campaign_id,
                "location_id": int(loc_id),
                "ppd": ppd,
                "cpp": cpp,
                "days": days,
                "total_plays": total_plays,
                "impressions": int(total_plays * 1.8),
                "cost": cost,
            },
        )

    db.session.commit()
    return campaign_id


def get_campaigns(account_id: int) -> list[dict]:
    rows = db.session.execute(
        text("""
            SELECT c.*,
                   COUNT(cl.id) AS screen_count
            FROM billboard_campaigns c
            LEFT JOIN billboard_campaign_locations cl ON cl.campaign_id = c.id
            WHERE c.account_id = :aid
            GROUP BY c.id
            ORDER BY c.created_at DESC
        """),
        {"aid": account_id},
    ).fetchall()

    campaigns = []
    today = date.today()
    for r in rows:
        c = _row_to_dict(r)
        c = _enrich_campaign(c, today)
        campaigns.append(c)
    return campaigns


def get_campaign(campaign_id: int, account_id: int) -> dict | None:
    row = db.session.execute(
        text("SELECT * FROM billboard_campaigns WHERE id = :cid AND account_id = :aid"),
        {"cid": campaign_id, "aid": account_id},
    ).fetchone()
    if not row:
        return None

    c = _row_to_dict(row)

    loc_rows = db.session.execute(
        text("""
            SELECT cl.*, bl.name, bl.city, bl.state, bl.screen_type, bl.size,
                   bl.traffic_daily, bl.impressions_weekly, bl.image_placeholder, bl.facing
            FROM billboard_campaign_locations cl
            JOIN billboard_locations bl ON bl.id = cl.location_id
            WHERE cl.campaign_id = :cid
            ORDER BY bl.city, bl.name
        """),
        {"cid": campaign_id},
    ).fetchall()

    c["locations"] = [_row_to_dict(r) for r in loc_rows]
    today = date.today()
    c = _enrich_campaign(c, today)
    return c


def _enrich_campaign(c: dict, today: date) -> dict:
    start = c.get("start_date")
    end = c.get("end_date")

    if isinstance(start, str):
        try:
            start = datetime.strptime(start, "%Y-%m-%d").date()
        except Exception:
            start = None
    if isinstance(end, str):
        try:
            end = datetime.strptime(end, "%Y-%m-%d").date()
        except Exception:
            end = None

    if start and end:
        c["days_total"] = (end - start).days + 1
        if c.get("status") == "active" and start <= today:
            days_elapsed = (min(today, end) - start).days + 1
            c["days_elapsed"] = days_elapsed
            c["days_remaining"] = max(0, (end - today).days)
        else:
            c["days_elapsed"] = 0
            c["days_remaining"] = max(0, (end - today).days) if end else 0
    else:
        c["days_total"] = 0
        c["days_elapsed"] = 0
        c["days_remaining"] = 0

    # Simulated delivery
    if c.get("status") == "active" and c.get("days_elapsed", 0) > 0:
        # Pull plays_per_day sum from locations if available
        locations = c.get("locations", [])
        if locations:
            total_ppd = sum(int(loc.get("plays_per_day") or 480) for loc in locations)
        else:
            total_ppd = 480
        plays_delivered = total_ppd * c["days_elapsed"]
        c["plays_delivered_sim"] = plays_delivered
        c["impressions_delivered_sim"] = int(plays_delivered * 1.8)
    else:
        c["plays_delivered_sim"] = 0
        c["impressions_delivered_sim"] = 0

    return c


def update_campaign_status(campaign_id: int, account_id: int, status: str) -> bool:
    allowed = {"active", "paused", "cancelled", "completed"}
    if status not in allowed:
        return False
    result = db.session.execute(
        text("UPDATE billboard_campaigns SET status = :status WHERE id = :cid AND account_id = :aid"),
        {"status": status, "cid": campaign_id, "aid": account_id},
    )
    db.session.commit()
    return result.rowcount > 0


def generate_ai_copy(
    trade: str,
    location: str,
    usp_list: list[str],
    tone: str,
) -> dict:
    usp_text = "\n".join(f"- {u}" for u in usp_list if u.strip())
    user_prompt = f"""Generate billboard copy for this trade contractor:

Trade/industry: {trade}
City/service area: {location}
Tone: {tone}
Unique selling points:
{usp_text if usp_text else '- Licensed & Insured\n- Same-day service\n- Free estimates'}

Remember: headline max 7 words, subtext max 10 words, CTA max 5 words. Return only the JSON object."""

    try:
        from app.services.ai_client import generate_json
        result = generate_json(
            system_prompt=_AI_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            max_tokens=400,
            temperature=0.75,
            prefer_provider="anthropic",
        )
        if result and isinstance(result.get("headline"), str):
            return {
                "headline": result.get("headline", "")[:100],
                "subtext": result.get("subtext", "")[:200],
                "cta": result.get("cta", "")[:60],
                "design_tip": result.get("design_tip", ""),
                "fallback": False,
            }
    except Exception as e:
        log.warning("Billboard AI copy generation failed: %s", e)

    # Fallback
    return {
        "headline": f"{trade} You Can Trust",
        "subtext": f"Serving {location} — Licensed & Insured",
        "cta": "Call for Free Quote",
        "design_tip": "Use high contrast (white text on dark green) for maximum readability at highway speeds.",
        "fallback": True,
    }
