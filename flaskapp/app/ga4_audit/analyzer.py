"""GA4 audit logic — Admin API calls and check scoring."""
import requests

ADMIN_BASE = "https://analyticsadmin.googleapis.com/v1beta"


def _get(access_token, url):
    try:
        r = requests.get(
            url,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


def list_properties(access_token):
    """Return list of {account_name, property_id, display_name} dicts."""
    data = _get(access_token, f"{ADMIN_BASE}/accountSummaries")
    if not data:
        return []
    results = []
    for acct in data.get("accountSummaries", []):
        acct_name = acct.get("displayName", "")
        for prop in acct.get("propertySummaries", []):
            pid = prop.get("property", "").replace("properties/", "")
            results.append({
                "property_id": pid,
                "display_name": prop.get("displayName", pid),
                "account_name": acct_name,
                "resource": prop.get("property", ""),
            })
    return results


def _fetch_streams(access_token, pid):
    data = _get(access_token, f"{ADMIN_BASE}/properties/{pid}/dataStreams")
    return data.get("dataStreams", []) if data else []


def _fetch_em(access_token, pid, stream_id):
    return _get(access_token, f"{ADMIN_BASE}/properties/{pid}/dataStreams/{stream_id}/enhancedMeasurementSettings")


def _fetch_key_events(access_token, pid):
    data = _get(access_token, f"{ADMIN_BASE}/properties/{pid}/keyEvents")
    if data is not None:
        return data.get("keyEvents", [])
    data = _get(access_token, f"{ADMIN_BASE}/properties/{pid}/conversionEvents")
    return data.get("conversionEvents", []) if data else []


def _fetch_ads_links(access_token, pid):
    data = _get(access_token, f"{ADMIN_BASE}/properties/{pid}/googleAdsLinks")
    return data.get("googleAdsLinks", []) if data else []


def _fetch_retention(access_token, pid):
    return _get(access_token, f"{ADMIN_BASE}/properties/{pid}/dataRetentionSettings")


def _fetch_attribution(access_token, pid):
    return _get(access_token, f"{ADMIN_BASE}/properties/{pid}/attributionSettings")


def _fetch_custom_dims(access_token, pid):
    data = _get(access_token, f"{ADMIN_BASE}/properties/{pid}/customDimensions")
    return data.get("customDimensions", []) if data else []


def _fetch_audiences(access_token, pid):
    data = _get(access_token, f"{ADMIN_BASE}/properties/{pid}/audiences")
    return data.get("audiences", []) if data else []


def _fetch_filters(access_token, pid):
    data = _get(access_token, f"{ADMIN_BASE}/properties/{pid}/dataFilters")
    return data.get("dataFilters", []) if data else []


def _check(id_, name, category, severity, score, max_score, status, message, detail, fix=None, extra=None):
    return {
        "id": id_,
        "name": name,
        "category": category,
        "severity": severity,
        "score": score,
        "max_score": max_score,
        "status": status,
        "message": message,
        "detail": detail,
        "fix": fix,
        "extra": extra or {},
    }


def run_audit(access_token, property_id):
    pid = str(property_id).replace("properties/", "")

    prop = _get(access_token, f"{ADMIN_BASE}/properties/{pid}")
    streams = _fetch_streams(access_token, pid)
    key_events = _fetch_key_events(access_token, pid)
    ads_links = _fetch_ads_links(access_token, pid)
    retention = _fetch_retention(access_token, pid)
    attribution = _fetch_attribution(access_token, pid)
    custom_dims = _fetch_custom_dims(access_token, pid)
    audiences = _fetch_audiences(access_token, pid)
    filters = _fetch_filters(access_token, pid)

    web_streams = [s for s in streams if s.get("type") == "WEB_DATA_STREAM"]

    em_list = []
    for s in web_streams:
        sid = s["name"].split("/")[-1]
        em = _fetch_em(access_token, pid, sid)
        if em:
            em_list.append(em)

    checks = []

    # ── CRITICAL (10 pts each) ───────────────────────────────────────────────

    # 1. Web data stream
    has_mid = any(s.get("webStreamData", {}).get("measurementId") for s in web_streams)
    if web_streams and has_mid:
        mid = web_streams[0]["webStreamData"].get("measurementId", "")
        checks.append(_check(
            "web_streams", "Web Data Stream", "data_collection", "critical",
            10, 10, "pass",
            f"{len(web_streams)} web stream(s) configured (Measurement ID: {mid})",
            "Your property has a properly configured web data stream — GA4 can receive website data.",
        ))
    elif web_streams:
        checks.append(_check(
            "web_streams", "Web Data Stream", "data_collection", "critical",
            5, 10, "warning",
            "Web stream exists but Measurement ID is missing",
            "A web data stream was found but no Measurement ID (G-XXXXXXX) is visible. Data collection may be incomplete.",
            "Verify the stream configuration and ensure the Measurement ID is implemented on your website.",
        ))
    else:
        checks.append(_check(
            "web_streams", "Web Data Stream", "data_collection", "critical",
            0, 10, "fail",
            "No web data streams configured",
            "Your GA4 property has no web data streams. Without a stream, no website data is collected.",
            "Create a web data stream: Admin → Data Streams → Add stream → Web. Add the Measurement ID (G-XXXXXXX) to your site.",
        ))

    # 2. Enhanced Measurement
    em_on = sum(1 for em in em_list if em.get("streamEnabled"))
    em_total = len(em_list)
    if em_total == 0:
        checks.append(_check(
            "enhanced_measurement", "Enhanced Measurement", "data_collection", "critical",
            0, 10, "fail",
            "Enhanced measurement settings not found",
            "Could not retrieve enhanced measurement settings — ensure a web data stream exists.",
            "Enable enhanced measurement: Admin → Data Streams → [stream] → Enhanced Measurement → toggle on.",
        ))
    elif em_on == em_total:
        checks.append(_check(
            "enhanced_measurement", "Enhanced Measurement", "data_collection", "critical",
            10, 10, "pass",
            f"Enhanced measurement enabled on all {em_total} stream(s)",
            "Automatic tracking of page views, scrolls, outbound clicks, site search, and file downloads is active.",
        ))
    elif em_on > 0:
        checks.append(_check(
            "enhanced_measurement", "Enhanced Measurement", "data_collection", "critical",
            5, 10, "warning",
            f"Enhanced measurement enabled on {em_on} of {em_total} streams",
            f"{em_total - em_on} stream(s) have enhanced measurement disabled — those streams miss automatic event collection.",
            "Enable enhanced measurement on all streams: Admin → Data Streams → [stream] → Enhanced Measurement → toggle on.",
        ))
    else:
        checks.append(_check(
            "enhanced_measurement", "Enhanced Measurement", "data_collection", "critical",
            0, 10, "fail",
            "Enhanced measurement disabled on all streams",
            "You're missing automatic tracking of scrolls, outbound clicks, form interactions, site search, and file downloads.",
            "Enable enhanced measurement: Admin → Data Streams → [stream] → Enhanced Measurement → toggle on.",
        ))

    # 3. Key Events
    n_events = len(key_events)
    event_names = [
        e.get("eventName") or e.get("name", "").split("/")[-1]
        for e in key_events
    ]
    if n_events >= 3:
        checks.append(_check(
            "key_events", "Key Events (Conversions)", "conversion_setup", "critical",
            10, 10, "pass",
            f"{n_events} key events configured",
            f"Good conversion coverage: {', '.join(event_names[:5])}{'…' if n_events > 5 else ''}",
            extra={"event_names": event_names},
        ))
    elif n_events >= 1:
        checks.append(_check(
            "key_events", "Key Events (Conversions)", "conversion_setup", "critical",
            7, 10, "warning",
            f"Only {n_events} key event(s) configured",
            f"You have key events ({', '.join(event_names)}) but most businesses need 3+ to measure the full funnel.",
            "Add key events: Admin → Key Events → Create. Consider: generate_lead, schedule, purchase, contact, sign_up.",
            extra={"event_names": event_names},
        ))
    else:
        checks.append(_check(
            "key_events", "Key Events (Conversions)", "conversion_setup", "critical",
            0, 10, "fail",
            "No key events configured",
            "Without key events GA4 can't report which channels and campaigns drive real business outcomes.",
            "Create key events: Admin → Key Events → Create. Start with your most important action (purchase, lead form, phone call).",
        ))

    # 4. Data Retention
    ret_val = (retention or {}).get("eventDataRetention", "")
    if ret_val == "FOURTEEN_MONTHS":
        checks.append(_check(
            "data_retention", "Data Retention", "data_quality", "critical",
            10, 10, "pass",
            "Data retention set to 14 months (maximum)",
            "Historical data is preserved for the maximum 14 months, enabling reliable year-over-year analysis.",
        ))
    elif ret_val and ret_val != "TWO_MONTHS":
        readable = ret_val.replace("_", " ").lower()
        checks.append(_check(
            "data_retention", "Data Retention", "data_quality", "critical",
            5, 10, "warning",
            f"Data retention: {readable}",
            "Not at the maximum 14 months — older data will be deleted, limiting historical analysis.",
            "Set to 14 months: Admin → Data Settings → Data Retention → Event data retention → 14 months.",
        ))
    else:
        checks.append(_check(
            "data_retention", "Data Retention", "data_quality", "critical",
            0, 10, "fail",
            "Data retention is at the 2-month default",
            "Data beyond 2 months is deleted. Year-over-year comparisons and long-term trend analysis are not possible.",
            "Change immediately: Admin → Data Settings → Data Retention → Event data retention → 14 months → Save.",
        ))

    # 5. Google Ads Linked
    n_links = len(ads_links)
    if n_links >= 1:
        checks.append(_check(
            "google_ads_linked", "Google Ads Linked", "conversion_setup", "critical",
            10, 10, "pass",
            f"{n_links} Google Ads account(s) linked",
            "Conversion import, remarketing audiences, and cross-platform attribution are available.",
        ))
    else:
        checks.append(_check(
            "google_ads_linked", "Google Ads Linked", "conversion_setup", "critical",
            0, 10, "fail",
            "No Google Ads accounts linked",
            "You can't import GA4 conversions to Google Ads, share remarketing audiences, or get cross-platform attribution.",
            "Link Google Ads: Admin → Google Ads Links → Link. Requires admin access to both accounts.",
        ))

    # 6. Attribution Model
    attr_model = (attribution or {}).get("reportingAttributionModel", "")
    if "DATA_DRIVEN" in attr_model:
        checks.append(_check(
            "attribution", "Attribution Model", "conversion_setup", "critical",
            10, 10, "pass",
            "Data-driven attribution active",
            "Machine learning assigns conversion credit across all touchpoints — the most accurate available model.",
        ))
    elif attr_model and "LAST_CLICK" not in attr_model and attr_model not in ("", "REPORTING_ATTRIBUTION_MODEL_UNSPECIFIED"):
        checks.append(_check(
            "attribution", "Attribution Model", "conversion_setup", "critical",
            7, 10, "warning",
            f"Non-default model: {attr_model.replace('REPORTING_ATTRIBUTION_MODEL_', '').replace('_', ' ').title()}",
            "You're using a custom attribution model. Consider upgrading to data-driven for the most accurate results.",
            "Switch: Admin → Attribution Settings → Reporting attribution model → Data-driven.",
        ))
    elif "LAST_CLICK" in attr_model:
        checks.append(_check(
            "attribution", "Attribution Model", "conversion_setup", "critical",
            3, 10, "warning",
            "Last-click attribution model in use",
            "Last-click gives 100% credit to the final touchpoint and undervalues top-of-funnel channels (display, social, organic).",
            "Switch to data-driven: Admin → Attribution Settings → Reporting attribution model → Data-driven.",
        ))
    else:
        checks.append(_check(
            "attribution", "Attribution Model", "conversion_setup", "critical",
            5, 10, "warning",
            "Attribution settings not retrieved",
            "Could not read attribution settings. Verify your GA4 property admin permissions.",
            "Review: Admin → Attribution Settings and configure your reporting attribution model.",
        ))

    # ── MODERATE (5 pts each) ────────────────────────────────────────────────

    # 7. Internal Traffic Filter
    active_filters = [f for f in filters if f.get("state") == "ACTIVE"]
    int_filters = [
        f for f in active_filters
        if "INTERNAL" in f.get("filterType", "").upper()
        or "DEVELOPER" in f.get("filterType", "").upper()
        or "internal" in f.get("displayName", "").lower()
    ]
    if int_filters:
        checks.append(_check(
            "internal_filter", "Internal Traffic Filter", "data_quality", "moderate",
            5, 5, "pass",
            f"Internal traffic filter active: '{int_filters[0].get('displayName', 'filter')}'",
            "Your own office and developer traffic is excluded from reports.",
        ))
    elif active_filters:
        checks.append(_check(
            "internal_filter", "Internal Traffic Filter", "data_quality", "moderate",
            2, 5, "warning",
            "Filters exist but no internal traffic filter found",
            "Active filters were found but none specifically exclude internal/developer traffic, which may inflate metrics.",
            "Add: Admin → Data Settings → Data Filters → Create Filter → Internal Traffic → enter your office IP range.",
        ))
    else:
        checks.append(_check(
            "internal_filter", "Internal Traffic Filter", "data_quality", "moderate",
            0, 5, "fail",
            "No internal traffic filter configured",
            "Traffic from your own team inflates session counts and distorts conversion rates in reports.",
            "Create filter: Admin → Data Settings → Data Filters → Create Filter → Internal Traffic → add your IP address.",
        ))

    # 8. Custom Dimensions
    n_dims = len(custom_dims)
    if n_dims >= 2:
        checks.append(_check(
            "custom_dims", "Custom Dimensions", "technical_health", "moderate",
            5, 5, "pass",
            f"{n_dims} custom dimension(s) defined",
            f"Custom dimensions enable richer segmentation beyond GA4 defaults: {', '.join(d.get('displayName','') for d in custom_dims[:3])}{'…' if n_dims > 3 else ''}",
        ))
    elif n_dims == 1:
        checks.append(_check(
            "custom_dims", "Custom Dimensions", "technical_health", "moderate",
            2, 5, "warning",
            "Only 1 custom dimension defined",
            "One custom dimension found. Consider adding more to capture user properties like subscription tier, customer type, or content category.",
            "Add dimensions: Admin → Custom Definitions → Custom Dimensions → Create.",
        ))
    else:
        checks.append(_check(
            "custom_dims", "Custom Dimensions", "technical_health", "moderate",
            0, 5, "fail",
            "No custom dimensions configured",
            "Custom dimensions capture business-specific data (user role, plan, segment) unavailable in default GA4 reports.",
            "Create: Admin → Custom Definitions → Custom Dimensions → Create. Start with user-level properties most relevant to your business.",
        ))

    # 9–11. Enhanced Measurement specifics
    scroll_on = any(em.get("scrollsEnabled") for em in em_list)
    outbound_on = any(em.get("outboundClicksEnabled") for em in em_list)
    forms_on = any(em.get("formInteractionsEnabled") for em in em_list)

    checks.append(_check(
        "em_scroll", "Scroll Depth Tracking", "data_collection", "moderate",
        5 if scroll_on else 0, 5,
        "pass" if scroll_on else "fail",
        "Scroll depth tracking enabled" if scroll_on else "Scroll tracking disabled",
        "Scroll events measure content engagement and identify where users stop reading." if scroll_on
        else "You can't measure how far users scroll on key pages — a signal of content engagement.",
        None if scroll_on else "Enable: Admin → Data Streams → [stream] → Enhanced Measurement → Scrolls.",
    ))

    checks.append(_check(
        "em_outbound", "Outbound Click Tracking", "data_collection", "moderate",
        5 if outbound_on else 0, 5,
        "pass" if outbound_on else "fail",
        "Outbound click tracking enabled" if outbound_on else "Outbound click tracking disabled",
        "Clicks to external sites (partner pages, booking tools, etc.) are captured." if outbound_on
        else "When users click to external sites, those clicks aren't captured in GA4.",
        None if outbound_on else "Enable: Admin → Data Streams → [stream] → Enhanced Measurement → Outbound Clicks.",
    ))

    checks.append(_check(
        "em_forms", "Form Interaction Tracking", "data_collection", "moderate",
        5 if forms_on else 0, 5,
        "pass" if forms_on else "fail",
        "Form interaction tracking enabled" if forms_on else "Form interaction tracking disabled",
        "Form starts and submissions are tracked — you can measure form abandonment and lead funnel health." if forms_on
        else "Form interactions (start, submit, abandon) are not tracked. Lead form drop-off is invisible.",
        None if forms_on else "Enable: Admin → Data Streams → [stream] → Enhanced Measurement → Form Interactions.",
    ))

    # 12. Conversion event breadth
    has_purchase = any("purchase" in (e.get("eventName") or "").lower() for e in key_events)
    has_lead = any(
        any(kw in (e.get("eventName") or "").lower() for kw in ["lead", "contact", "form", "inquiry", "signup", "sign_up", "schedule"])
        for e in key_events
    )
    breadth = sum([has_purchase, has_lead, n_events >= 3])
    if breadth >= 2:
        checks.append(_check(
            "conversion_breadth", "Conversion Event Coverage", "conversion_setup", "moderate",
            5, 5, "pass",
            "Good conversion event coverage across funnel stages",
            f"Key events cover multiple stages: {'purchase events found, ' if has_purchase else ''}{'lead capture events found' if has_lead else ''}.",
        ))
    elif n_events >= 1:
        checks.append(_check(
            "conversion_breadth", "Conversion Event Coverage", "conversion_setup", "moderate",
            2, 5, "warning",
            "Partial conversion funnel coverage",
            f"You have {n_events} key event(s) but may be missing {'purchase' if not has_purchase else 'lead capture'} events.",
            "Add events for each funnel stage: purchase/revenue (bottom), generate_lead/contact (mid), scroll/video_play (top).",
        ))
    else:
        checks.append(_check(
            "conversion_breadth", "Conversion Event Coverage", "conversion_setup", "moderate",
            0, 5, "fail",
            "No conversion funnel coverage",
            "No key events mean no funnel measurement — you can't see which channels drive valuable actions.",
            "Create key events covering each stage: Admin → Key Events → Create.",
        ))

    # 13. Industry Category
    industry = (prop or {}).get("industryCategory", "")
    if industry and industry not in ("INDUSTRY_CATEGORY_UNSPECIFIED", ""):
        readable = industry.replace("INDUSTRY_CATEGORY_", "").replace("_", " ").title()
        checks.append(_check(
            "industry_category", "Industry Category", "technical_health", "moderate",
            5, 5, "pass",
            f"Industry category set: {readable}",
            "Industry benchmarking is enabled — GA4 can compare your performance to similar businesses.",
        ))
    else:
        checks.append(_check(
            "industry_category", "Industry Category", "technical_health", "moderate",
            0, 5, "fail",
            "Industry category not set",
            "Without an industry category, GA4 can't show how your metrics compare to peers in your sector.",
            "Set it: Admin → Property Settings → Industry Category → select your industry.",
        ))

    # 14. Audiences
    default_names = {"All Users", "Purchasers"}
    custom_auds = [a for a in audiences if a.get("displayName") not in default_names]
    n_auds = len(custom_auds)
    if n_auds >= 2:
        checks.append(_check(
            "audiences", "Remarketing Audiences", "technical_health", "moderate",
            5, 5, "pass",
            f"{n_auds} custom audience(s) defined",
            f"Audiences for remarketing: {', '.join(a.get('displayName','') for a in custom_auds[:3])}{'…' if n_auds > 3 else ''}",
        ))
    elif n_auds == 1:
        checks.append(_check(
            "audiences", "Remarketing Audiences", "technical_health", "moderate",
            2, 5, "warning",
            "Only 1 custom audience defined",
            "One custom audience found. More precise audiences improve remarketing ROI in Google Ads.",
            "Build audiences: Admin → Audiences → New Audience. Create segments for high-intent visitors and cart abandoners.",
        ))
    else:
        checks.append(_check(
            "audiences", "Remarketing Audiences", "technical_health", "moderate",
            0, 5, "fail",
            "No custom remarketing audiences",
            "Without audiences, you can't run targeted remarketing campaigns in Google Ads to re-engage past visitors.",
            "Create audiences: Admin → Audiences → New Audience. Start with 'All visitors last 30 days'.",
        ))

    # ── Totals ───────────────────────────────────────────────────────────────
    total = sum(c["score"] for c in checks)
    max_total = sum(c["max_score"] for c in checks)
    pct = round((total / max_total) * 100) if max_total else 0

    cats = {}
    cat_labels = {
        "data_collection": "Data Collection",
        "conversion_setup": "Conversion Setup",
        "data_quality": "Data Quality",
        "technical_health": "Technical Health",
    }
    for c in checks:
        cat = c["category"]
        cats.setdefault(cat, {"label": cat_labels.get(cat, cat), "score": 0, "max_score": 0})
        cats[cat]["score"] += c["score"]
        cats[cat]["max_score"] += c["max_score"]
    for v in cats.values():
        v["pct"] = round((v["score"] / v["max_score"]) * 100) if v["max_score"] else 0

    issues = [c for c in checks if c["status"] in ("fail", "warning")]
    critical_issues = [c for c in issues if c["severity"] == "critical"]

    prop_name = (prop or {}).get("displayName", f"Property {pid}")
    tz = (prop or {}).get("timeZone", "")

    return {
        "property_id": pid,
        "property_name": prop_name,
        "time_zone": tz,
        "overall_score": pct,
        "overall_grade": _grade(pct),
        "checks": checks,
        "categories": cats,
        "issues_count": len(issues),
        "critical_issues_count": len(critical_issues),
        "passes_count": len([c for c in checks if c["status"] == "pass"]),
        "total_checks": len(checks),
        "stream_count": len(web_streams),
        "key_event_count": n_events,
        "ads_linked": len(ads_links) > 0,
    }


def _grade(score):
    if score >= 90: return "A+"
    if score >= 80: return "A"
    if score >= 70: return "B+"
    if score >= 60: return "B"
    if score >= 50: return "C+"
    if score >= 40: return "C"
    if score >= 30: return "D"
    return "F"


DEMO_RESULT = {
    "property_id": "demo",
    "property_name": "Demo Business Website",
    "time_zone": "America/New_York",
    "overall_score": 52,
    "overall_grade": "C+",
    "issues_count": 8,
    "critical_issues_count": 3,
    "passes_count": 6,
    "total_checks": 14,
    "stream_count": 1,
    "key_event_count": 1,
    "ads_linked": False,
    "categories": {
        "data_collection": {"label": "Data Collection", "score": 25, "max_score": 30, "pct": 83},
        "conversion_setup": {"label": "Conversion Setup", "score": 10, "max_score": 30, "pct": 33},
        "data_quality": {"label": "Data Quality", "score": 5, "max_score": 15, "pct": 33},
        "technical_health": {"label": "Technical Health", "score": 12, "max_score": 20, "pct": 60},
    },
    "checks": [
        {"id": "web_streams", "name": "Web Data Stream", "category": "data_collection", "severity": "critical", "score": 10, "max_score": 10, "status": "pass", "message": "1 web stream configured (Measurement ID: G-ABC1234567)", "detail": "Your property has a properly configured web data stream.", "fix": None},
        {"id": "enhanced_measurement", "name": "Enhanced Measurement", "category": "data_collection", "severity": "critical", "score": 10, "max_score": 10, "status": "pass", "message": "Enhanced measurement enabled on all 1 stream(s)", "detail": "Automatic tracking of page views, scrolls, outbound clicks, and more is active.", "fix": None},
        {"id": "key_events", "name": "Key Events (Conversions)", "category": "conversion_setup", "severity": "critical", "score": 7, "max_score": 10, "status": "warning", "message": "Only 1 key event configured", "detail": "You have 1 key event but most businesses need 3+ to measure the full funnel.", "fix": "Add key events: Admin → Key Events → Create. Consider: generate_lead, schedule, contact."},
        {"id": "data_retention", "name": "Data Retention", "category": "data_quality", "severity": "critical", "score": 0, "max_score": 10, "status": "fail", "message": "Data retention is at the 2-month default", "detail": "Data beyond 2 months is deleted. Year-over-year analysis is not possible.", "fix": "Admin → Data Settings → Data Retention → 14 months → Save."},
        {"id": "google_ads_linked", "name": "Google Ads Linked", "category": "conversion_setup", "severity": "critical", "score": 0, "max_score": 10, "status": "fail", "message": "No Google Ads accounts linked", "detail": "No conversion import, remarketing audiences, or cross-platform attribution available.", "fix": "Admin → Google Ads Links → Link."},
        {"id": "attribution", "name": "Attribution Model", "category": "conversion_setup", "severity": "critical", "score": 3, "max_score": 10, "status": "warning", "message": "Last-click attribution model in use", "detail": "Last-click undervalues top-of-funnel channels and distorts budget decisions.", "fix": "Admin → Attribution Settings → Data-driven."},
        {"id": "internal_filter", "name": "Internal Traffic Filter", "category": "data_quality", "severity": "moderate", "score": 5, "max_score": 5, "status": "pass", "message": "Internal traffic filter active", "detail": "Your office and developer traffic is excluded from reports.", "fix": None},
        {"id": "custom_dims", "name": "Custom Dimensions", "category": "technical_health", "severity": "moderate", "score": 2, "max_score": 5, "status": "warning", "message": "Only 1 custom dimension defined", "detail": "One custom dimension found. Consider adding more for richer segmentation.", "fix": "Admin → Custom Definitions → Custom Dimensions → Create."},
        {"id": "em_scroll", "name": "Scroll Depth Tracking", "category": "data_collection", "severity": "moderate", "score": 5, "max_score": 5, "status": "pass", "message": "Scroll depth tracking enabled", "detail": "Scroll events measure content engagement.", "fix": None},
        {"id": "em_outbound", "name": "Outbound Click Tracking", "category": "data_collection", "severity": "moderate", "score": 0, "max_score": 5, "status": "fail", "message": "Outbound click tracking disabled", "detail": "Clicks to external sites are not captured in GA4.", "fix": "Admin → Data Streams → [stream] → Enhanced Measurement → Outbound Clicks."},
        {"id": "em_forms", "name": "Form Interaction Tracking", "category": "data_collection", "severity": "moderate", "score": 0, "max_score": 5, "status": "fail", "message": "Form interaction tracking disabled", "detail": "Form starts and abandons are not tracked — lead funnel drop-off is invisible.", "fix": "Admin → Data Streams → [stream] → Enhanced Measurement → Form Interactions."},
        {"id": "conversion_breadth", "name": "Conversion Event Coverage", "category": "conversion_setup", "severity": "moderate", "score": 0, "max_score": 5, "status": "fail", "message": "Partial conversion funnel coverage", "detail": "Only 1 key event doesn't cover the full customer journey.", "fix": "Add events for each funnel stage: Admin → Key Events → Create."},
        {"id": "industry_category", "name": "Industry Category", "category": "technical_health", "severity": "moderate", "score": 5, "max_score": 5, "status": "pass", "message": "Industry category set: Finance", "detail": "Industry benchmarking is enabled.", "fix": None},
        {"id": "audiences", "name": "Remarketing Audiences", "category": "technical_health", "severity": "moderate", "score": 5, "max_score": 5, "status": "pass", "message": "3 custom audiences defined", "detail": "Audiences available for Google Ads remarketing.", "fix": None},
    ],
}
