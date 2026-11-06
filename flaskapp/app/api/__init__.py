from flask import Blueprint, request, jsonify

api_bp = Blueprint("api_bp", __name__, url_prefix="/api")


@api_bp.route("/track", methods=["POST"])
def track():
    """Client-side event logging from free tools and marketing pages."""
    try:
        data = request.get_json(silent=True) or {}
        event_type = str(data.get("event_type") or "").strip()
        if not event_type:
            return jsonify({"ok": False, "error": "event_type required"}), 400

        from app.services.event_tracker import log_event

        ip = request.headers.get("X-Forwarded-For", request.remote_addr or "")
        ip = ip.split(",")[0].strip()

        log_event(
            event_type,
            event_source=str(data.get("event_source") or "web")[:100],
            tool_name=str(data.get("tool_name") or "")[:100] or None,
            detected_trade=str(data.get("detected_trade") or "")[:100] or None,
            session_fingerprint=str(data.get("session_fingerprint") or "")[:64] or None,
            properties=data.get("properties") if isinstance(data.get("properties"), dict) else None,
            ip=ip,
            user_agent=request.headers.get("User-Agent", ""),
        )
        return jsonify({"ok": True}), 200
    except Exception:
        return jsonify({"ok": False}), 200  # never surface errors to client


@api_bp.route("/capture-email", methods=["POST"])
def capture_email():
    """Lead capture from free tool email modal."""
    try:
        data = request.get_json(silent=True) or {}
        email = str(data.get("email") or "").strip().lower()
        if not email or "@" not in email or len(email) > 254:
            return jsonify({"ok": False, "error": "valid email required"}), 400
        ip = request.headers.get("X-Forwarded-For", request.remote_addr or "")
        ip = ip.split(",")[0].strip()
        from app.services.lead_capture_service import save_lead
        save_lead(
            email=email,
            tool_name=str(data.get("tool_name") or "")[:100] or None,
            detected_trade=str(data.get("detected_trade") or "")[:100] or None,
            service_area=str(data.get("service_area") or "")[:200] or None,
            result_summary=str(data.get("result_summary") or "")[:500] or None,
            source="free_tool",
            ip=ip,
        )
        return jsonify({"ok": True}), 200
    except Exception:
        return jsonify({"ok": False}), 200
