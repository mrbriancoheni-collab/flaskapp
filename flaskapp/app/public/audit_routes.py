# app/public/audit_routes.py
"""
Unified free-tool audit entry point.

Routes:
  GET  /free-tools/audit      — audit landing page
  POST /api/audit/analyze     — URL analysis API (no auth required)

NOTE: No hard rate limiting implemented here — production deployments should
add flask-limiter decorators or a reverse-proxy rate limit on /api/audit/analyze
to prevent abuse (URL scraping of arbitrary sites).
"""
from __future__ import annotations

import ipaddress
import logging
import re
from urllib.parse import urlparse

from flask import jsonify, render_template, request

from app.public import public_bp

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy import of website_analyzer — built in parallel; graceful if absent
# ---------------------------------------------------------------------------
try:
    from app.services.website_analyzer import analyze_website as _analyze_website  # noqa: F401
    _ANALYZER_AVAILABLE = True
except ImportError:
    _ANALYZER_AVAILABLE = False
    logger.warning("app.services.website_analyzer not found — audit analyze endpoint will return 503")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PRIVATE_NETS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]


def _is_private_host(hostname: str) -> bool:
    """Return True if hostname resolves to a private/loopback address."""
    try:
        addr = ipaddress.ip_address(hostname)
        return any(addr in net for net in _PRIVATE_NETS)
    except ValueError:
        # hostname is a domain name — check for localhost variants
        return hostname.lower() in ("localhost", "0.0.0.0")


def _validate_url(url: str) -> tuple[bool, str]:
    """
    Validate that a URL is safe to fetch.
    Returns (ok, error_message).
    """
    if not url:
        return False, "URL is required."

    # Normalise — prepend https:// if missing scheme
    if not re.match(r"^https?://", url, re.IGNORECASE):
        url = "https://" + url

    try:
        parsed = urlparse(url)
    except Exception:
        return False, "Invalid URL."

    if parsed.scheme not in ("http", "https"):
        return False, "URL must start with http:// or https://."

    host = parsed.hostname or ""
    if not host:
        return False, "URL has no hostname."

    if _is_private_host(host):
        return False, "Cannot audit private or internal addresses."

    return True, url  # second value is the normalised URL


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@public_bp.route("/free-tools/audit", methods=["GET"], endpoint="free_tools_audit")
def free_tools_audit():
    return render_template("audit.html")


@public_bp.route("/api/audit/analyze", methods=["POST"], endpoint="audit_analyze_api")
def audit_analyze_api():
    """
    Accept a website URL, scrape it, run Claude analysis, return structured
    business data as JSON.

    Request body (JSON or form): { url: "https://example.com" }
    Response: { success: true, data: { business_name, trade, services[], service_area, usps[], phone } }
            | { success: false, error: "..." }
    """
    # Parse input — accept JSON or form
    if request.is_json:
        body = request.get_json(silent=True) or {}
        raw_url = body.get("url", "")
    else:
        raw_url = request.form.get("url", "")

    raw_url = (raw_url or "").strip()

    ok, result = _validate_url(raw_url)
    if not ok:
        return jsonify({"success": False, "error": result}), 400

    normalized_url = result  # _validate_url returns normalised URL on success

    if not _ANALYZER_AVAILABLE:
        return jsonify({
            "success": False,
            "error": "Analysis temporarily unavailable. Use the manual form below to see your benchmarks."
        }), 503

    try:
        from app.services.website_analyzer import analyze_website
        data = analyze_website(normalized_url)
        if not data:
            return jsonify({
                "success": False,
                "error": "Couldn't reach that website. Check the URL and try again."
            }), 422
        return jsonify({"success": True, "data": data})
    except ImportError:
        return jsonify({
            "success": False,
            "error": "Analysis temporarily unavailable."
        }), 503
    except Exception as exc:
        logger.exception("audit_analyze_api error for %s: %s", normalized_url, exc)
        return jsonify({
            "success": False,
            "error": "Couldn't reach that website. Check the URL and try again."
        }), 422
