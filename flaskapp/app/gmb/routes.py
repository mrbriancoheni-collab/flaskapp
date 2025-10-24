from __future__ import annotations

from typing import Any, Dict, Optional, List
from flask import (
    render_template, redirect, url_for, current_app, request, abort, flash
)
from . import gmb_bp
from .service import ai_optimize_profile
from .auth import require_gmb_connection_optional, require_gmb_connection


# ---- tiny in-memory helpers (replace with DB/real APIs) ----
def is_connected() -> bool:
    return bool(current_app.config.get("GMB_CONNECTED", False))

def get_profile() -> Optional[Dict[str, Any]]:
    return current_app.config.get("GMB_PROFILE")

def set_profile(profile: Dict[str, Any]) -> None:
    current_app.config["GMB_PROFILE"] = profile

def set_connected(flag: bool) -> None:
    current_app.config["GMB_CONNECTED"] = flag

def set_suggestions(sug: Optional[Dict[str, Any]]) -> None:
    current_app.config["_GMB_SUGGESTIONS"] = sug

def get_suggestions() -> Optional[Dict[str, Any]]:
    return current_app.config.get("_GMB_SUGGESTIONS")


# ---- sample profile shown when not connected ----
SAMPLE_PROFILE: Dict[str, Any] = {
    "name": "Clean Finish Cleaning Service",
    "primary_category": "House Cleaning Service",
    "additional_categories": ["Janitorial Service", "Window Cleaning Service"],
    "description": "Eco-friendly, high-quality residential and commercial cleaning serving Greater Sacramento. Transparent pricing, vetted pros, and a 100% happiness guarantee.",
    "phone": "(916) 555-0198",
    "website": "https://cleanfinish.example.com",
    "address": "8213 Northam Dr, Antelope, CA 95843",
    "service_areas": ["Sacramento", "Roseville", "Citrus Heights", "Elk Grove"],
    "hours_text": "Mon–Fri: 8:00 AM – 6:00 PM\nSat: 9:00 AM – 2:00 PM\nSun: Closed",
    "attributes": ["Eco-friendly", "Women-led", "Locally owned"],
}


# ------------------------- UI PAGES -------------------------

@gmb_bp.get("/")
def index():
    connected = is_connected()
    profile = get_profile() if connected else None
    return render_template(
        "gmb/index.html",
        connected=connected,
        profile=profile,
        sample_profile=SAMPLE_PROFILE,
        suggestions=get_suggestions(),
    )


# --------------------- ACTION ENDPOINTS ---------------------

@gmb_bp.get("/optimize")
def optimize_profile():
    # Allow optimizer to run against real profile when connected, else sample
    connected = is_connected()
    base = get_profile() if connected else SAMPLE_PROFILE
    suggestions = ai_optimize_profile(base)
    set_suggestions(suggestions)
    return redirect(url_for("gmb_bp.index"))


@gmb_bp.post("/update")
def update_profile():
    require_gmb_connection()  # 401/redirect if not connected
    # Parse form -> dict
    def parse_csv(name: str) -> List[str]:
        raw = (request.form.get(name) or "").strip()
        return [s.strip() for s in raw.split(",") if s.strip()]

    payload = {
        "name": request.form.get("name") or "",
        "primary_category": request.form.get("primary_category") or "",
        "additional_categories": parse_csv("additional_categories"),
        "description": request.form.get("description") or "",
        "phone": request.form.get("phone") or "",
        "website": request.form.get("website") or "",
        "address": request.form.get("address") or "",
        "service_areas": parse_csv("service_areas"),
        "hours_text": request.form.get("hours") or "",
        "attributes": parse_csv("attributes"),
    }
    # TODO: push to Google Business Profile API here.
    set_profile(payload)
    flash("Profile saved.", "success")
    return redirect(url_for("gmb_bp.index"))


# ---------------------- CONNECTION FLOW ---------------------

@gmb_bp.get("/start")
def start():
    # Kick off OAuth in real life. Here we just flip the flag for demo.
    set_connected(True)
    # Seed a minimal profile on first connect if empty
    if not get_profile():
        set_profile(dict(SAMPLE_PROFILE))
    flash("Connected to Google Business (demo).", "success")
    return redirect(url_for("gmb_bp.index"))


@gmb_bp.post("/disconnect")
def disconnect():
    require_gmb_connection_optional()
    set_connected(False)
    set_profile(None)
    set_suggestions(None)
    flash("Disconnected Google Business.", "info")
    return redirect(url_for("gmb_bp.index"))


# ---------------------- NAV TARGETS (stubs) ----------------------

@gmb_bp.get("/reviews")
def reviews():
    # Replace with a real reviews UI
    return "Reviews UI (stub)."

@gmb_bp.get("/ai-responses")
def ai_responses():
    return "AI review responses UI (stub)."

@gmb_bp.get("/requests-email")
def requests_email():
    return "Review request emails UI (stub)."

@gmb_bp.get("/photos")
def photos():
    return "Photos UI (stub)."
