# app/strategy/__init__.py
from __future__ import annotations

import os
import json
from typing import Optional, List, Dict, Any

import requests
from flask import (
    Blueprint,
    render_template,
    request,
    url_for,
    flash,
    session,
    redirect,
    current_app,
)
from sqlalchemy import text

from app.models_strategy import MarketingStrategy
from app import db
from app.auth.utils import login_required, is_paid_account

# (Unused but harmless shared bp; keep if other modules expect it)
bp = Blueprint("my_ai_bp", __name__, url_prefix="/account/my-ai")

strategy_bp = Blueprint("strategy_bp", __name__, template_folder="../../templates")

# ---------------- helpers ----------------

def see_other(endpoint: str, **values):
    return redirect(url_for(endpoint, **values), code=303)

def _account_id() -> Optional[int]:
    aid = session.get("account_id") or session.get("aid")
    if aid:
        try:
            return int(aid)
        except Exception:
            pass
    uid = session.get("user_id")
    if not uid:
        return None
    row = db.session.execute(
        text("SELECT account_id FROM users WHERE id=:id"),
        {"id": uid},
    ).fetchone()
    return int(row[0]) if row and row[0] is not None else None

def _csv_to_list(s: str) -> List[str]:
    return [x.strip() for x in (s or "").split(",") if x.strip()]

def _dollars_from_cents(cents: Optional[int]) -> str:
    try:
        return f"${(cents or 0) / 100:.2f}"
    except Exception:
        return "$0.00"

# ---------- Heuristic fallback (used if no API key or API error) ----------

def _heuristic_fill_gaps(
    ms: MarketingStrategy,
    *,
    depth: str = "medium",
    objective: str = "lead_gen",
    priority_channels: Optional[List[str]] = None,
) -> Dict[str, Any]:
    # ... (unchanged heuristic content) ...
    priority_channels = priority_channels or []
    updates: Dict[str, Any] = {}

    channels = (ms.channels or []).copy()
    if not channels:
        if objective in ("lead_gen", "sales"):
            channels = ["SEO", "Content", "Email", "PPC", "Retargeting"]
        elif objective == "awareness":
            channels = ["SEO", "Content", "Social (Organic)", "PR", "Video"]
        else:
            channels = ["Email", "CRM", "Loyalty", "Content", "Social (Organic)"]
    for ch in priority_channels:
        if ch not in channels:
            channels.insert(0, ch)

    goals = (ms.goals or [])
    if not goals:
        if objective == "lead_gen":
            goals = ["Increase qualified leads (MQLs) by 30% within 90 days"]
        elif objective == "sales":
            goals = ["Grow online revenue by 20% quarter-over-quarter"]
        elif objective == "awareness":
            goals = ["Double branded search volume within 120 days"]
        else:
            goals = ["Lift repeat purchase rate by 15% in 6 months"]

    positioning = ms.positioning or (
        f"{ms.business_name or 'Our brand'} delivers outcome-driven value for "
        f"{', '.join(ms.primary_keywords or ['your audience'])} with a "
        f"{ms.brand_voice or 'helpful, expert'} voice."
    )

    core_msg = (ms.messaging or {}).get("core") or (
        f"{ms.business_name or 'We'} help your audience achieve real results with "
        f"{', '.join(ms.primary_keywords or ['the right strategy'])}. Start now to see measurable impact."
    )

    primary_keywords = (ms.primary_keywords or [])
    if not primary_keywords and ms.industry:
        primary_keywords = [f"{ms.industry} services", f"best {ms.industry}", f"{ms.industry} near me"]

    competitors = (ms.competitors or [])
    if not competitors and ms.industry:
        competitors = [f"Top {ms.industry} competitor A", f"Top {ms.industry} competitor B"]

    offers = (ms.offers or []) or ["Free consultation", "First-month discount"]
    constraints = (ms.constraints or []) or ["Limited content capacity", "Dev queue for landing pages"]
    tools = (ms.tools or []) or ["GA4", "GSC", "CRM", "WordPress/Blog", "Ads (Google/Meta)"]

    kpis = (ms.kpis or [])
    if not kpis:
        if objective in ("lead_gen", "sales"):
            kpis = ["MQLs", "SQLs", "CPL", "ROAS", "Revenue"]
        elif objective == "awareness":
            kpis = ["Impressions", "Share of Voice", "Branded Search", "Website Sessions"]
        else:
            kpis = ["Repeat Purchase Rate", "LTV", "Churn", "Email CTR"]

    if depth == "light":
        timeline = [{"phase": "Phase 1 – Foundation", "duration_weeks": "4"}]
    elif depth == "full":
        timeline = [
            {"phase": "Phase 1 – Foundation", "duration_weeks": "4"},
            {"phase": "Phase 2 – Growth", "duration_weeks": "8"},
            {"phase": "Phase 3 – Scale", "duration_weeks": "12"},
        ]
    else:
        timeline = [
            {"phase": "Phase 1 – Foundation", "duration_weeks": "4"},
            {"phase": "Phase 2 – Growth", "duration_weeks": "6"},
        ]

    content_plan: List[Dict[str, Any]] = []
    if "Content" in channels or "SEO" in channels:
        kws = (primary_keywords or [])[:3]
        for kw in kws:
            content_plan.append({"type": "blog", "title": f"Definitive guide to {kw}", "cadence": "biweekly"})
        content_plan.append({"type": "pillar", "title": "Ultimate industry resource hub", "cadence": "quarterly"})
    if "Email" in channels:
        content_plan.append({"type": "email", "title": "Nurture series (3-part)", "cadence": "monthly"})
    if "PPC" in channels:
        content_plan.append({"type": "ppc", "title": "Always-on search + brand", "cadence": "ongoing"})

    target_audience = ms.target_audience or {"notes": "", "segments": []}
    if not target_audience.get("segments"):
        target_audience["segments"] = ["Primary buyers", "Influencers", "Repeat customers"]

    return dict(
        goals=goals,
        channels=channels,
        positioning=positioning,
        messaging={"core": core_msg, "by_segment": []},
        primary_keywords=primary_keywords,
        competitors=competitors,
        offers=offers,
        constraints=constraints,
        tools=tools,
        kpis=kpis,
        timeline=timeline,
        content_plan=content_plan,
        target_audience=target_audience,
    )

# ---------- ChatGPT (OpenAI) integration ----------

def _openai_api_key() -> Optional[str]:
    # Safe access to current_app.config; works even if app ctx isn’t present
    key = os.getenv("OPENAI_API_KEY")
    if key:
        return key
    try:
        return (getattr(current_app, "config", {}) or {}).get("OPENAI_API_KEY")
    except Exception:
        return None

def _llm_chat(messages: List[Dict[str, str]], model: Optional[str] = None, temperature: float = 0.4) -> Optional[str]:
    api_key = _openai_api_key()
    if not api_key:
        return None
    try:
        configured_model = (getattr(current_app, "config", {}) or {}).get("OPENAI_MODEL")
    except Exception:
        configured_model = None
    model = model or configured_model or "gpt-4o-mini"

    try:
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "temperature": temperature,
                "messages": messages,
                "response_format": {"type": "json_object"},
            },
            timeout=60,
        )
        if resp.status_code >= 400:
            current_app.logger.error("OpenAI API error %s: %s", resp.status_code, resp.text[:500])
            return None
        data = resp.json()
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        current_app.logger.exception("OpenAI request failed: %s", e)
        return None

def _strategy_to_context(ms_like: Any) -> Dict[str, Any]:
    # ... (unchanged) ...
    get = lambda k, default=None: getattr(ms_like, k, None) if hasattr(ms_like, k) else ms_like.get(k, default)
    messaging = get("messaging") or {}
    target_audience = get("target_audience") or {}
    return {
        "name": get("name"),
        "business_name": get("business_name"),
        "website": get("website"),
        "industry": get("industry"),
        "brand_voice": get("brand_voice"),
        "locations": get("locations") or [],
        "pov_ids": get("pov_ids") or [],
        "goals": [(g.get("goal") if isinstance(g, dict) else g) for g in (get("goals") or [])],
        "positioning": get("positioning") or "",
        "messaging_core": messaging.get("core", ""),
        "audience_notes": target_audience.get("notes", ""),
        "audience_segments": target_audience.get("segments", []),
        "primary_keywords": get("primary_keywords") or [],
        "extra_keywords": get("extra_keywords") or [],
        "channels": get("channels") or [],
        "competitors": [(c.get("name") if isinstance(c, dict) else c) for c in (get("competitors") or [])],
        "offers": get("offers") or [],
        "constraints": get("constraints") or [],
        "tools": get("tools") or [],
        "kpis": get("kpis") or [],
        "budget": (get("budget_cents") or 0) / 100.0,
        "timeline": get("timeline") or [],
        "content_plan": get("content_plan") or [],
    }

def _build_section_schema(section: str) -> Dict[str, Any]:
    # ... (unchanged) ...
    s = section.lower()
    if s == "goals":
        return {"goals": ["string", "..."]}
    if s == "positioning":
        return {"positioning": "string"}
    if s == "messaging":
        return {"messaging": {"core": "string", "by_segment": []}}
    if s == "audience":
        return {"target_audience": {"notes": "string", "segments": ["string", "..."]}}
    if s == "channels":
        return {"channels": ["string", "..."]}
    if s == "keywords":
        return {"primary_keywords": ["string", "..."], "extra_keywords": ["string", "..."]}
    if s == "competitors":
        return {"competitors": [{"name": "string"}, "..."]}
    if s == "offers":
        return {"offers": ["string", "..."]}
    if s == "constraints":
        return {"constraints": ["string", "..."]}
    if s == "tools":
        return {"tools": ["string", "..."]}
    if s == "kpis":
        return {"kpis": ["string", "..."]}
    if s == "timeline":
        return {"timeline": [{"phase": "string", "duration_weeks": "string"}, "..."]}
    if s == "content_plan" or s == "campaigns" or s == "campaign":
        return {"content_plan": [{"type": "string", "title": "string", "cadence": "string"}, "..."]}
    return {
        "goals": ["string", "..."],
        "positioning": "string",
        "messaging": {"core": "string", "by_segment": []},
        "target_audience": {"notes": "string", "segments": ["string", "..."]},
        "channels": ["string", "..."],
        "primary_keywords": ["string", "..."],
        "extra_keywords": ["string", "..."],
        "competitors": [{"name": "string"}, "..."],
        "offers": ["string", "..."],
        "constraints": ["string", "..."],
        "tools": ["string", "..."],
        "kpis": ["string", "..."],
        "timeline": [{"phase": "string", "duration_weeks": "string"}, "..."],
        "content_plan": [{"type": "string", "title": "string", "cadence": "string"}, "..."],
    }

def _ai_fill_with_chatgpt(
    ms_like: Any,
    *,
    section: Optional[str],
    depth: str,
    objective: str,
    priority_channels: Optional[List[str]],
) -> Optional[Dict[str, Any]]:
    schema_hint = _build_section_schema(section or "full")
    ctx = _strategy_to_context(ms_like)
    priority_channels = priority_channels or []

    sys = (
        "You are a senior marketing strategist. Create concise, practical, ROI-focused suggestions. "
        "Return ONLY valid JSON matching the requested fields; do not include explanations."
    )
    user = {
        "task": "Generate/complete a marketing strategy section" if section else "Generate/complete a full marketing strategy",
        "section": section or "full",
        "objective": objective,
        "depth": depth,
        "priority_channels": priority_channels,
        "schema": schema_hint,
        "context": ctx,
        "instructions": [
            "Use the business context as primary source of truth.",
            "If something is missing, infer reasonable defaults for the industry and objective.",
            "Keep language clear and specific. Avoid generic fluff.",
            "For goals, make them measurable and time-bound.",
            "For channels, include only the top channels likely to perform.",
            "For timeline, include 2-3 phases with duration_weeks as strings.",
            "For keywords, produce intent-rich queries related to the industry.",
        ],
    }
    messages = [{"role": "system", "content": sys}, {"role": "user", "content": json.dumps(user)}]

    out = _llm_chat(messages, temperature=0.4)
    if not out:
        return None
    try:
        return json.loads(out)
    except Exception:
        try:
            start = out.find("{"); end = out.rfind("}")
            if start != -1 and end != -1 and end > start:
                return json.loads(out[start:end+1])
        except Exception:
            current_app.logger.error("Failed to parse ChatGPT JSON: %s", out[:500])
            return None

def _normalize_updates_dict(upd: Dict[str, Any]) -> Dict[str, Any]:
    # ... (unchanged) ...
    norm = dict(upd or {})
    if "goals" in norm:
        g = []
        for x in norm["goals"] or []:
            if isinstance(x, str):
                g.append({"goal": x})
            elif isinstance(x, dict):
                g.append({"goal": x.get("goal", "")})
        norm["goals"] = g
    if "competitors" in norm:
        c = []
        for x in norm["competitors"] or []:
            if isinstance(x, str):
                c.append({"name": x})
            elif isinstance(x, dict):
                c.append({"name": x.get("name", "")})
        norm["competitors"] = c
    if "target_audience" in norm and isinstance(norm["target_audience"], dict):
        ta = norm["target_audience"]
        if "segments" in ta and isinstance(ta["segments"], str):
            ta["segments"] = _csv_to_list(ta["segments"])
        norm["target_audience"] = ta
    for k in ("primary_keywords", "extra_keywords", "channels", "offers", "constraints", "tools", "kpis"):
        if k in norm and isinstance(norm[k], str):
            norm[k] = _csv_to_list(norm[k])
    return norm

def _render_strategy_html(ms: MarketingStrategy) -> str:
    # Build HTML safely with list + join to avoid syntax issues
    def to_goal_text(x):
        return x.get("goal") if isinstance(x, dict) else str(x)
    def to_comp_name(x):
        return x.get("name") if isinstance(x, dict) else str(x)
    def li(items):
        return "".join(f"<li>{i}</li>" for i in (items or []))
    def csv(items):
        return ", ".join(items or [])

    goals_list = [to_goal_text(g) for g in (ms.goals or [])]
    competitors_list = [to_comp_name(c) for c in (ms.competitors or [])]
    core_msg = (ms.messaging or {}).get("core", "") or "-"
    positioning_text = (ms.positioning or "")
    positioning_html = positioning_text.replace("\n", "<br>")
    ta_notes = (ms.target_audience or {}).get("notes", "") or "-"
    ta_segments = csv((ms.target_audience or {}).get("segments") or [])
    pov_ids_csv = csv([str(x) for x in (ms.pov_ids or [])])
    primary_kw_csv = csv(ms.primary_keywords or [])
    extra_kw_csv = csv(ms.extra_keywords or [])
    budget_dollars = _dollars_from_cents(ms.budget_cents)

    if isinstance(ms.timeline, list):
        timeline_str = ", ".join(
            f"{(p.get('phase') if isinstance(p, dict) else str(p))} ({(p.get('duration_weeks') if isinstance(p, dict) else '-') } wks)"
            for p in (ms.timeline or [])
        )
    else:
        timeline_str = str(ms.timeline or "-")

    parts: List[str] = []
    parts.append(
        "<section>"
        "<h2>Company Overview</h2>"
        f"<p><strong>Business:</strong> {ms.business_name or '-'}<br>"
        f"<strong>Website:</strong> {ms.website or '-'}<br>"
        f"<strong>Industry:</strong> {ms.industry or '-'}<br>"
        f"<strong>Locations:</strong> {csv(ms.locations) or '-'}</p>"
        "</section>"
    )
    parts.append("<section><h2>Goals</h2><ul>{}</ul></section>".format(li(goals_list)))
    parts.append("<section><h2>Positioning & Value Proposition</h2><p>{}</p></section>".format(positioning_html or "-"))
    parts.append("<section><h2>Target Audience</h2><p>{}</p><p><strong>Segments:</strong> {}</p></section>".format(ta_notes, ta_segments or "-"))
    parts.append("<section><h2>POVs (Angles)</h2><p>Selected POV IDs: {}</p></section>".format(pov_ids_csv or "-"))
    parts.append("<section><h2>Messaging</h2><p><strong>Core Message:</strong> {}</p></section>".format(core_msg))
    parts.append("<section><h2>Keywords</h2><p><strong>Primary:</strong> {}</p><p><strong>Additional:</strong> {}</p></section>".format(primary_kw_csv or "-", extra_kw_csv or "-"))
    parts.append("<section><h2>Channels & Tactics</h2><ul>{}</ul></section>".format(li(ms.channels or [])))
    parts.append("<section><h2>Competitors</h2><ul>{}</ul></section>".format(li(competitors_list)))
    parts.append("<section><h2>Offers</h2><ul>{}</ul></section>".format(li(ms.offers or [])))
    parts.append("<section><h2>Constraints</h2><ul>{}</ul></section>".format(li(ms.constraints or [])))
    parts.append("<section><h2>Tools / Stack</h2><ul>{}</ul></section>".format(li(ms.tools or [])))
    parts.append(
        "<section><h2>Budget & Timeline</h2>"
        f"<p><strong>Monthly Budget:</strong> {budget_dollars}</p>"
        f"<p><strong>Timeline:</strong> {timeline_str}</p></section>"
    )
    parts.append("<section><h2>KPIs</h2><ul>{}</ul></section>".format(li(ms.kpis or [])))

    # Campaigns / Content Plan (only if present)
    if isinstance(ms.content_plan, list) and ms.content_plan:
        def li_content(items):
            out = []
            for x in items:
                if isinstance(x, dict):
                    t = x.get("type", "item")
                    title = x.get("title", "")
                    cad = x.get("cadence", "")
                    out.append(f"<li><strong>{t.title()}</strong>: {title} <em>({cad})</em></li>")
                else:
                    out.append(f"<li>{x}</li>")
            return "".join(out)
        parts.append("<section><h2>Campaigns / Content Plan</h2><ul>{}</ul></section>".format(li_content(ms.content_plan)))

    return "".join(parts)

def _apply_section_update(ms: MarketingStrategy, section: str, updates: Dict[str, Any]):
    # ... (unchanged) ...
    upd = _normalize_updates_dict(updates or {})
    s = section.lower()
    if s == "goals" and "goals" in upd:
        ms.goals = upd["goals"]
    elif s == "positioning" and "positioning" in upd:
        ms.positioning = upd["positioning"]
    elif s == "messaging" and "messaging" in upd:
        ms.messaging = upd["messaging"]
    elif s == "audience" and "target_audience" in upd:
        ms.target_audience = upd["target_audience"]
    elif s == "channels" and "channels" in upd:
        ms.channels = upd["channels"]
    elif s == "keywords":
        if "primary_keywords" in upd:
            ms.primary_keywords = upd["primary_keywords"]
        if "extra_keywords" in upd:
            ms.extra_keywords = upd["extra_keywords"]
    elif s == "competitors" and "competitors" in upd:
        ms.competitors = upd["competitors"]
    elif s == "offers" and "offers" in upd:
        ms.offers = upd["offers"]
    elif s == "constraints" and "constraints" in upd:
        ms.constraints = upd["constraints"]
    elif s == "tools" and "tools" in upd:
        ms.tools = upd["tools"]
    elif s == "kpis" and "kpis" in upd:
        ms.kpis = upd["kpis"]
    elif s == "timeline" and "timeline" in upd:
        ms.timeline = upd["timeline"]
    elif s == "content_plan" and "content_plan" in upd:
        ms.content_plan = upd["content_plan"]

def _merge_form_into_dict(form) -> Dict[str, Any]:
    # ... (unchanged) ...
    csv = _csv_to_list
    return {
        "name": form.get("name") or "",
        "business_name": form.get("business_name") or "",
        "website": form.get("website") or "",
        "industry": form.get("industry") or "",
        "locations": csv(form.get("locations")),
        "pov_ids": [int(x) for x in csv(form.get("pov_ids")) if str(x).isdigit()],
        "goals": csv(form.get("goals")),
        "positioning": form.get("positioning") or "",
        "messaging": {"core": form.get("message_core") or "", "by_segment": []},
        "brand_voice": form.get("brand_voice") or "",
        "audience_notes": form.get("audience_notes") or "",
        "audience_segments": csv(form.get("audience_segments")),
        "primary_keywords": csv(form.get("primary_keywords")),
        "extra_keywords": csv(form.get("extra_keywords")),
        "channels": csv(form.get("channels")),
        "competitors": csv(form.get("competitors")),
        "offers": csv(form.get("offers")),
        "constraints": csv(form.get("constraints")),
        "tools": csv(form.get("tools")),
        "kpis": csv(form.get("kpis")),
        "budget": form.get("budget") or "",
        "phase1_weeks": form.get("phase1_weeks") or "4",
    }

def _apply_updates_to_form_values(vf: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
    # ... (unchanged) ...
    upd = _normalize_updates_dict(updates or {})
    if "goals" in upd:
        vf["goals"] = [g["goal"] for g in upd["goals"]]
    if "positioning" in upd:
        vf["positioning"] = upd["positioning"]
    if "messaging" in upd:
        vf["messaging"]["core"] = upd["messaging"].get("core", vf["messaging"]["core"])
    if "target_audience" in upd:
        ta = upd["target_audience"]
        vf["audience_notes"] = ta.get("notes", vf.get("audience_notes", ""))
        vf["audience_segments"] = ta.get("segments", vf.get("audience_segments", []))
    if "channels" in upd:
        vf["channels"] = upd["channels"]
    if "primary_keywords" in upd:
        vf["primary_keywords"] = upd["primary_keywords"]
    if "extra_keywords" in upd:
        vf["extra_keywords"] = upd["extra_keywords"]
    if "competitors" in upd:
        vf["competitors"] = [c["name"] for c in upd["competitors"]]
    if "offers" in upd:
        vf["offers"] = upd["offers"]
    if "constraints" in upd:
        vf["constraints"] = upd["constraints"]
    if "tools" in upd:
        vf["tools"] = upd["tools"]
    if "kpis" in upd:
        vf["kpis"] = upd["kpis"]
    if "timeline" in upd:
        phases = []
        for p in upd["timeline"]:
            if isinstance(p, dict):
                phases.append(f"{p.get('phase','Phase')} ({p.get('duration_weeks','-')} wks)")
            else:
                phases.append(str(p))
        vf["timeline_note"] = ", ".join(phases)
    if "content_plan" in upd:
        vf["content_plan_note"] = "; ".join(
            [f"{x.get('type','item')}: {x.get('title','')}" if isinstance(x, dict) else str(x) for x in upd["content_plan"]]
        )
    return vf

# ---------------- pages ----------------

@strategy_bp.route("/", methods=["GET"], endpoint="index")
@login_required
def index():
    aid = _account_id()
    q = MarketingStrategy.query
    if aid:
        q = q.filter_by(account_id=aid)
    items = q.order_by(MarketingStrategy.updated_at.desc()).all()
    return render_template("strategy/index.html", items=items)

@strategy_bp.route("/new", methods=["GET"], endpoint="new")
@login_required
def new():
    vf = {
        "name": "",
        "business_name": "",
        "website": "",
        "industry": "",
        "locations": [],
        "pov_ids": [],
        "goals": [],
        "positioning": "",
        "messaging": {"core": "", "by_segment": []},
        "brand_voice": "",
        "audience_notes": "",
        "audience_segments": [],
        "primary_keywords": [],
        "extra_keywords": [],
        "channels": [],
        "competitors": [],
        "offers": [],
        "constraints": [],
        "tools": [],
        "kpis": [],
        "budget": "",
        "phase1_weeks": "4",
        "timeline_note": "",
        "content_plan_note": "",
    }
    return render_template("strategy/new.html", vf=vf)

@strategy_bp.route("/new/ai", methods=["POST"], endpoint="ai_new")
@login_required
def ai_new():
    """
    AI assist on the New page (no DB record yet). Paid users only.
    If OPENAI_API_KEY is missing or the API fails, we fall back to the heuristic.
    """
    if not is_paid_account():
        flash("AI features are available on paid plans. Upgrade to continue.", "warning")
        return see_other("strategy_bp.new")

    vf = _merge_form_into_dict(request.form)
    depth = (request.form.get("ai_depth") or "medium").lower()
    objective_label = (request.form.get("ai_objective") or "Lead Generation").strip().lower()
    objective_map = {"awareness": "awareness", "lead generation": "lead_gen", "sales": "sales", "retention": "retention"}
    objective = objective_map.get(objective_label, "lead_gen")
    prio = _csv_to_list(request.form.get("ai_priority_channels"))
    section = (request.form.get("section") or "").strip().lower()

    # Normalize "campaigns" to "content_plan" for generation on the new page too
    if section in ("campaigns", "campaign", "content", "content_plan"):
        section = "content_plan"

    # Build transient ms-like object
    ms_like = {
        "name": vf["name"],
        "business_name": vf["business_name"],
        "website": vf["website"],
        "industry": vf["industry"],
        "brand_voice": vf["brand_voice"],
        "locations": vf["locations"],
        "pov_ids": vf["pov_ids"],
        "goals": vf["goals"],
        "positioning": vf["positioning"],
        "messaging": vf["messaging"],
        "target_audience": {"notes": vf["audience_notes"], "segments": vf["audience_segments"]},
        "primary_keywords": vf["primary_keywords"],
        "extra_keywords": vf["extra_keywords"],
        "channels": vf["channels"],
        "competitors": vf["competitors"],
        "offers": vf["offers"],
        "constraints": vf["constraints"],
        "tools": vf["tools"],
        "kpis": vf["kpis"],
        "budget_cents": int(float(vf["budget"] or 0) * 100) if str(vf["budget"]).strip() else 0,
        "timeline": [],
        "content_plan": [],
    }

    # Try LLM first if key is present; otherwise heuristic
    updates = None
    if _openai_api_key():
        updates = _ai_fill_with_chatgpt(ms_like, section=section or None, depth=depth, objective=objective, priority_channels=prio)
    if not updates:
        mock_ms = MarketingStrategy(
            name=vf["name"], business_name=vf["business_name"], website=vf["website"], industry=vf["industry"],
            brand_voice=vf["brand_voice"],
        )
        mock_ms.locations = vf["locations"]; mock_ms.pov_ids = vf["pov_ids"]; mock_ms.goals = vf["goals"]
        mock_ms.positioning = vf["positioning"]; mock_ms.messaging = vf["messaging"]
        mock_ms.target_audience = {"notes": vf["audience_notes"], "segments": vf["audience_segments"]}
        mock_ms.primary_keywords = vf["primary_keywords"]; mock_ms.extra_keywords = vf["extra_keywords"]
        mock_ms.channels = vf["channels"]; mock_ms.competitors = [{"name": c} for c in vf["competitors"]]
        mock_ms.offers = vf["offers"]; mock_ms.constraints = vf["constraints"]; mock_ms.tools = vf["tools"]
        mock_ms.kpis = vf["kpis"]; mock_ms.budget_cents = int(float(vf["budget"] or 0) * 100) if str(vf["budget"]).strip() else 0
        mock_ms.timeline = []; mock_ms.content_plan = []
        updates = _heuristic_fill_gaps(mock_ms, depth=depth, objective=objective, priority_channels=prio)

    vf = _apply_updates_to_form_values(vf, updates)
    flash("AI suggestions added to the form. Review and click Save to create the strategy.", "success")
    return render_template("strategy/new.html", vf=vf)

@strategy_bp.route("/create", methods=["POST"], endpoint="create")
@login_required
def create():
    aid = _account_id()
    form = request.form

    ms = MarketingStrategy(
        account_id=aid,
        name=form.get("name") or "Marketing Strategy",
        business_name=form.get("business_name") or None,
        website=form.get("website") or None,
        industry=form.get("industry") or None,
        locations=_csv_to_list(form.get("locations")),
        pov_ids=[int(x) for x in _csv_to_list(form.get("pov_ids")) if str(x).isdigit()],
        target_audience={"notes": form.get("audience_notes") or "", "segments": _csv_to_list(form.get("audience_segments"))},
        personas=None,

        goals=[{"goal": g} for g in _csv_to_list(form.get("goals"))],
        positioning=form.get("positioning") or "",
        messaging={"core": form.get("message_core") or "", "by_segment": []},
        brand_voice=form.get("brand_voice") or "",
        competitors=[{"name": n} for n in _csv_to_list(form.get("competitors"))],
        primary_keywords=_csv_to_list(form.get("primary_keywords")),
        extra_keywords=_csv_to_list(form.get("extra_keywords")),

        channels=_csv_to_list(form.get("channels")),
        content_plan=[],  # start with zero campaigns; AI can populate later
        offers=_csv_to_list(form.get("offers")),
        constraints=_csv_to_list(form.get("constraints")),
        tools=_csv_to_list(form.get("tools")),
        budget_cents=int(float(form.get("budget", "0") or 0) * 100) if (form.get("budget") or "").strip() else 0,
        timeline=[{"phase": "Phase 1 – Foundation", "duration_weeks": form.get("phase1_weeks") or "4"}],
        kpis=_csv_to_list(form.get("kpis")),
        strategy_html=None,
    )

    db.session.add(ms)
    db.session.commit()

    # Optional AI on create (full document) — paid gate
    if (form.get("use_ai_full") or "").strip():
        if not is_paid_account():
            flash("AI features are available on paid plans. Strategy created without AI assist.", "warning")
            return see_other("strategy_bp.edit", strategy_id=ms.id)

        depth = (form.get("ai_depth") or "medium").lower()
        objective_label = (form.get("ai_objective") or "Lead Generation").strip().lower()
        objective_map = {"awareness": "awareness", "lead generation": "lead_gen", "sales": "sales", "retention": "retention"}
        objective = objective_map.get(objective_label, "lead_gen")
        prio = _csv_to_list(form.get("ai_priority_channels"))

        updates = None
        if _openai_api_key():
            updates = _ai_fill_with_chatgpt(ms, section=None, depth=depth, objective=objective, priority_channels=prio)
        if not updates:
            updates = _heuristic_fill_gaps(ms, depth=depth, objective=objective, priority_channels=prio)

        updates = _normalize_updates_dict(updates)
        for k, v in updates.items():
            setattr(ms, k, v)

        ms.strategy_html = _render_strategy_html(ms)
        db.session.commit()
        flash("Strategy created with AI Assist.", "success")
    else:
        flash("Strategy shell created. You can edit sections below.", "success")

    return see_other("strategy_bp.edit", strategy_id=ms.id)

@strategy_bp.route("/<int:strategy_id>", methods=["GET"], endpoint="edit")
@login_required
def edit(strategy_id: int):
    ms = MarketingStrategy.query.get_or_404(strategy_id)
    return render_template("strategy/edit.html", ms=ms)

@strategy_bp.route("/<int:strategy_id>/save", methods=["POST"], endpoint="save")
@login_required
def save(strategy_id: int):
    ms = MarketingStrategy.query.get_or_404(strategy_id)
    data = request.form

    # Basic
    ms.name = data.get("name") or ms.name
    ms.business_name = data.get("business_name") or None
    ms.website = data.get("website") or None
    ms.industry = data.get("industry") or None
    ms.brand_voice = data.get("brand_voice") or ""

    # Lists / CSV
    csv = _csv_to_list
    ms.locations = csv(data.get("locations"))
    ms.primary_keywords = csv(data.get("primary_keywords"))
    ms.extra_keywords = csv(data.get("extra_keywords"))
    ms.channels = csv(data.get("channels"))
    ms.offers = csv(data.get("offers"))
    ms.constraints = csv(data.get("constraints"))
    ms.tools = csv(data.get("tools"))
    ms.kpis = csv(data.get("kpis"))
    ms.competitors = [{"name": n} for n in csv(data.get("competitors"))]

    # Goals
    goals_arr = [g for g in request.form.getlist("goals[]") if g.strip()]
    ms.goals = [{"goal": g.strip()} for g in goals_arr] if goals_arr else [{"goal": g} for g in csv(data.get("goals"))]

    ms.positioning = data.get("positioning") or ""
    ms.messaging = {"core": data.get("message_core") or "", "by_segment": []}

    # POV IDs
    if "pov_ids" in request.form:
        ms.pov_ids = [int(x) for x in csv(request.form.get("pov_ids")) if str(x).isdigit()]
    else:
        pov_ids_multi = request.form.getlist("pov_ids")
        ms.pov_ids = [int(x) for x in pov_ids_multi if str(x).isdigit()]

    # Audience
    ms.target_audience = {"notes": data.get("audience_notes") or "", "segments": csv(data.get("audience_segments"))}

    # Strategy doc
    ms.strategy_html = data.get("strategy_html") or ms.strategy_html

    # Budget
    try:
        ms.budget_cents = int(float(data.get("budget", "0") or 0) * 100)
    except Exception:
        pass

    db.session.commit()
    flash("Saved.", "success")
    return see_other("strategy_bp.edit", strategy_id=ms.id)

@strategy_bp.route("/<int:strategy_id>/generate", methods=["POST"], endpoint="generate")
@login_required
def generate(strategy_id: int):
    """
    AI Assist via ChatGPT. If 'section' is provided, only that section is updated.
    Otherwise, fills the whole strategy and renders strategy_html.
    Paid users only. Falls back to heuristic if API unavailable.
    """
    if not is_paid_account():
        flash("AI features are available on paid plans. Upgrade to continue.", "warning")
        return see_other("strategy_bp.edit", strategy_id=strategy_id)

    ms = MarketingStrategy.query.get_or_404(strategy_id)

    depth = (request.form.get("ai_depth") or "medium").lower()
    objective_label = (request.form.get("ai_objective") or "Lead Generation").strip().lower()
    objective_map = {"awareness": "awareness", "lead generation": "lead_gen", "sales": "sales", "retention": "retention"}
    objective = objective_map.get(objective_label, "lead_gen")
    prio = _csv_to_list(request.form.get("ai_priority_channels"))
    section = (request.form.get("section") or "").strip().lower()

    # Treat these as requests to generate campaigns:
    if section in ("campaigns", "campaign", "content", "content_plan"):
        section = "content_plan"

    updates = None
    if _openai_api_key():
        updates = _ai_fill_with_chatgpt(ms, section=section or None, depth=depth, objective=objective, priority_channels=prio)
    if not updates:
        updates = _heuristic_fill_gaps(ms, depth=depth, objective=objective, priority_channels=prio)

    updates = _normalize_updates_dict(updates)

    if section:
        _apply_section_update(ms, section, updates)
        ms.strategy_html = _render_strategy_html(ms)
        db.session.commit()
        flash(f"AI suggestions applied to {section}.", "success")
        return see_other("strategy_bp.edit", strategy_id=ms.id)

    for k, v in updates.items():
        setattr(ms, k, v)
    ms.strategy_html = _render_strategy_html(ms)
    db.session.commit()
    flash("AI suggestions applied to the full strategy.", "success")
    return see_other("strategy_bp.edit", strategy_id=ms.id)
