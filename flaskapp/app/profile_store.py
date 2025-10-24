# app/profile_store.py
from flask import session

SESSION_KEY = "business_profile"

_DEFAULT = {
    "business_name": "",
    "owner_name": "",
    "email": "",
    "phone": "",
    "website": "",
    "service_area": "",
    "services": "",
    "target_customer": "",
    "brand_voice": "",
    "unique_value_prop": "",
    "hours": "",
    "call_to_action": "",
    "competitors": "",
}

def get_profile():
    """Return the dict stored in session (with defaults)."""
    data = session.get(SESSION_KEY) or {}
    # merge defaults so templates always have keys
    return {**_DEFAULT, **data}

def save_profile(data: dict):
    """Persist to session."""
    profile = get_profile()
    profile.update({k: (v or "").strip() for k, v in data.items() if k in _DEFAULT})
    session[SESSION_KEY] = profile
    session.modified = True
    return profile

def profile_as_prompt_block() -> str:
    """Human-readable block to prepend to AI prompts."""
    p = get_profile()
    lines = []
    if p["business_name"]:
        lines.append(f"Business: {p['business_name']}")
    if p["unique_value_prop"]:
        lines.append(f"Unique Value: {p['unique_value_prop']}")
    if p["services"]:
        lines.append(f"Services: {p['services']}")
    if p["service_area"]:
        lines.append(f"Service Area: {p['service_area']}")
    if p["target_customer"]:
        lines.append(f"Target Customer: {p['target_customer']}")
    if p["brand_voice"]:
        lines.append(f"Brand Voice: {p['brand_voice']}")
    if p["hours"]:
        lines.append(f"Hours: {p['hours']}")
    if p["website"]:
        lines.append(f"Website: {p['website']}")
    if p["competitors"]:
        lines.append(f"Competitors: {p['competitors']}")
    if p["call_to_action"]:
        lines.append(f"Preferred CTA: {p['call_to_action']}")

    block = "\n".join(lines).strip()
    if not block:
        return ""  # nothing set yet
    return (
        "You are a marketing assistant for a local home-services SMB.\n"
        "Use the following business profile context in all outputs:\n"
        + block + "\n"
        "Tailor tone and examples to this business."
    )
