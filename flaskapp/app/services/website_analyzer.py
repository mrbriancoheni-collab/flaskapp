"""
Website analyzer service.

Fetches a contractor's website and uses Claude Haiku to extract structured
business information: trade type, services, service area, USPs.
"""
from __future__ import annotations

import ipaddress
import json
import logging
import os
import re
import socket
from typing import Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (compatible; RevForge/1.0; +https://getrevforge.io)"
)

_VALID_TRADES = {
    "hvac", "plumbing", "electrical", "roofing", "pest_control",
    "landscaping", "garage_door", "pool_service", "solar", "painting",
    "cleaning", "general_contracting", "flooring", "concrete", "fencing",
    "irrigation", "lawn_care", "restoration", "windows_doors", "other",
}


# ---------------------------------------------------------------------------
# SSRF guard
# ---------------------------------------------------------------------------

def _is_safe_url(url: str) -> bool:
    """Return True only for public http/https URLs (reject internal IPs)."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        hostname = parsed.hostname
        if not hostname:
            return False
        # Resolve to IP
        try:
            ip = ipaddress.ip_address(socket.gethostbyname(hostname))
        except (socket.gaierror, ValueError):
            return False
        # Reject private / loopback / link-local / reserved ranges
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return False
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Page fetching
# ---------------------------------------------------------------------------

def fetch_page_text(url: str, timeout: int = 12) -> tuple[Optional[str], Optional[str]]:
    """
    Fetch a URL and return (clean_text, error).

    clean_text is stripped of scripts/styles, truncated to 4000 chars.
    error is a human-readable string on failure, None on success.
    """
    if not _is_safe_url(url):
        return None, "URL is not a valid public web address."

    try:
        resp = requests.get(
            url,
            headers={"User-Agent": _USER_AGENT},
            timeout=timeout,
            allow_redirects=True,
        )
        resp.raise_for_status()
    except requests.exceptions.Timeout:
        return None, "Request timed out."
    except requests.exceptions.TooManyRedirects:
        return None, "Too many redirects."
    except requests.exceptions.RequestException as e:
        return None, f"Could not reach that URL: {e}"

    soup = BeautifulSoup(resp.text, "html.parser")

    # Remove noise elements
    for tag in soup(["script", "style", "noscript", "header", "nav", "footer",
                     "form", "button", "svg", "img"]):
        tag.decompose()

    text = soup.get_text(separator=" ", strip=True)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text[:4000], None


# ---------------------------------------------------------------------------
# Claude analysis
# ---------------------------------------------------------------------------

_ANALYSIS_PROMPT = """You are analyzing a home-services contractor's website text.
Extract the following as JSON (keys exactly as shown, no extra keys):

{
  "business_name": "string or null",
  "trade": "one of: hvac|plumbing|electrical|roofing|pest_control|landscaping|garage_door|pool_service|solar|painting|cleaning|general_contracting|flooring|concrete|fencing|irrigation|lawn_care|restoration|windows_doors|other",
  "services": ["up to 8 specific services they offer"],
  "service_area": "city or region string, e.g. 'Denver, CO'",
  "usps": ["2-4 key differentiators like '24/7 Emergency Service'"],
  "phone": "phone number string or null"
}

Return ONLY valid JSON. No prose, no markdown fences."""


def analyze_website(url: str) -> tuple[Optional[dict], Optional[str]]:
    """
    Analyze a website URL and return (data_dict, error).

    data_dict contains: business_name, trade, services, service_area, usps, phone.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None, "API key not configured."

    page_text, fetch_error = fetch_page_text(url)
    if fetch_error:
        return None, fetch_error
    if not page_text:
        return None, "Page returned no readable content."

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-haiku-5-5",
            max_tokens=600,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"{_ANALYSIS_PROMPT}\n\nWebsite text:\n{page_text}"
                    ),
                }
            ],
        )
        raw = message.content[0].text.strip()
    except Exception as e:
        logger.warning("Claude API call failed: %s", e)
        return None, f"Analysis failed: {e}"

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Try to extract JSON block if model added any prose
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
            except json.JSONDecodeError:
                return None, "Could not parse analysis response."
        else:
            return None, "Could not parse analysis response."

    # Normalise trade
    trade = str(data.get("trade", "other")).lower().replace("-", "_")
    if trade not in _VALID_TRADES:
        trade = "other"
    data["trade"] = trade

    # Ensure lists
    data["services"] = list(data.get("services") or [])[:8]
    data["usps"] = list(data.get("usps") or [])[:4]

    return data, None
