# app/public/lsa_estimator.py
"""
Public (no-login) Local Services Ads lead-cost estimator.

A visitor picks their trade, monthly budget, and market size and gets an
estimated cost per lead, monthly lead volume, and projected booked jobs /
revenue — all from benchmark data, no API or account connection required.

This stays relevant after Google's Aug 2026 migration of LSA into Google Ads:
LSA keeps the same pay-per-lead billing and Search+Maps reach, so per-lead
economics still apply — the tool doubles as migration-readiness education.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from flask import render_template, request

from . import public_bp

# Benchmark pay-per-lead cost ranges (USD) for Local Services Ads by trade.
# Ranges are national averages; the market multiplier adjusts for metro size.
LSA_LEAD_COST = {
    "hvac":            (25, 50),
    "plumbing":        (25, 55),
    "electrical":      (25, 50),
    "roofing":         (40, 90),
    "garage_door":     (15, 35),
    "locksmith":       (20, 40),
    "landscaping":     (20, 45),
    "pest_control":    (20, 40),
    "house_cleaning":  (15, 35),
    "pool_service":    (20, 45),
    "solar":           (60, 150),
    "water_damage":    (45, 110),
    "appliance_repair":(15, 35),
    "window_cleaning": (15, 30),
    "tree_service":    (25, 55),
}

TRADE_LABELS = {
    "hvac": "HVAC", "plumbing": "Plumbing", "electrical": "Electrical",
    "roofing": "Roofing", "garage_door": "Garage Door", "locksmith": "Locksmith",
    "landscaping": "Landscaping", "pest_control": "Pest Control",
    "house_cleaning": "House Cleaning", "pool_service": "Pool Service",
    "solar": "Solar", "water_damage": "Water Damage / Restoration",
    "appliance_repair": "Appliance Repair", "window_cleaning": "Window Cleaning",
    "tree_service": "Tree Service",
}

# Market-size multiplier on lead cost (bigger metros = more competition).
MARKET_MULTIPLIER = {
    "major":    1.25,   # top-20 metro
    "mid":      1.0,    # mid-size city
    "small":    0.8,    # small city / rural
}
MARKET_LABELS = {"major": "Major metro (top 20)", "mid": "Mid-size city", "small": "Small city / rural"}

# Typical booking rate on LSA leads (they're high-intent phone/message leads).
DEFAULT_BOOKING_RATE = 0.35


def estimate(trade: str, budget: float, market: str,
             avg_job_value: float, booking_rate: float) -> Optional[Dict[str, Any]]:
    """Compute an LSA lead/ROI estimate. Returns None for an unknown trade."""
    base = LSA_LEAD_COST.get(trade)
    if not base:
        return None
    mult = MARKET_MULTIPLIER.get(market, 1.0)
    low_cost = round(base[0] * mult, 2)
    high_cost = round(base[1] * mult, 2)
    mid_cost = round((low_cost + high_cost) / 2, 2)

    budget = max(float(budget or 0), 0)
    # More leads at the low end of cost, fewer at the high end.
    leads_high = int(budget // low_cost) if low_cost else 0
    leads_low = int(budget // high_cost) if high_cost else 0
    leads_mid = int(budget // mid_cost) if mid_cost else 0

    booking_rate = min(max(booking_rate or DEFAULT_BOOKING_RATE, 0.05), 0.95)
    jobs_mid = int(leads_mid * booking_rate)
    revenue_mid = round(jobs_mid * max(float(avg_job_value or 0), 0), 2)
    cost_per_job = round(budget / jobs_mid, 2) if jobs_mid else None
    roas = round(revenue_mid / budget, 1) if budget else None

    return {
        "trade_label": TRADE_LABELS.get(trade, trade),
        "market_label": MARKET_LABELS.get(market, market),
        "cost_per_lead_low": low_cost,
        "cost_per_lead_high": high_cost,
        "cost_per_lead_mid": mid_cost,
        "leads_low": leads_low,
        "leads_high": leads_high,
        "leads_mid": leads_mid,
        "booking_rate_pct": int(booking_rate * 100),
        "jobs_mid": jobs_mid,
        "revenue_mid": revenue_mid,
        "cost_per_job": cost_per_job,
        "roas": roas,
        "budget": round(budget, 2),
        "avg_job_value": round(float(avg_job_value or 0), 2),
    }


def _trade_options() -> List[Dict[str, str]]:
    return [{"value": k, "label": v} for k, v in TRADE_LABELS.items()]


@public_bp.route("/lsa-estimator", methods=["GET", "POST"], endpoint="lsa_estimator")
def lsa_estimator():
    ctx: Dict[str, Any] = {
        "result": None,
        "error": None,
        "trades": _trade_options(),
        "markets": [{"value": k, "label": MARKET_LABELS[k]} for k in ("major", "mid", "small")],
        "form": {"trade": "", "budget": "1500", "market": "mid",
                 "avg_job_value": "500", "booking_rate": "35"},
    }

    if request.method == "POST":
        f = ctx["form"]
        f["trade"] = (request.form.get("trade") or "").strip()
        f["budget"] = (request.form.get("budget") or "").strip()
        f["market"] = (request.form.get("market") or "mid").strip()
        f["avg_job_value"] = (request.form.get("avg_job_value") or "").strip()
        f["booking_rate"] = (request.form.get("booking_rate") or "").strip()

        try:
            budget = float(f["budget"] or 0)
            avg_job = float(f["avg_job_value"] or 0)
            booking = float(f["booking_rate"] or 35) / 100.0
        except ValueError:
            budget, avg_job, booking = 0, 0, DEFAULT_BOOKING_RATE

        if not f["trade"]:
            ctx["error"] = "Choose your trade to run the estimate."
        elif budget <= 0:
            ctx["error"] = "Enter a monthly budget greater than zero."
        else:
            res = estimate(f["trade"], budget, f["market"], avg_job, booking)
            if not res:
                ctx["error"] = "That trade isn't recognized — pick one from the list."
            else:
                ctx["result"] = res

    return render_template("public/lsa_estimator.html", **ctx)
