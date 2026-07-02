# app/seo/eeat.py
"""
E-E-A-T (Experience, Expertise, Authoritativeness, Trustworthiness) Checker.

Fetches a page + homepage and audits for the trust/authority signals
Google's quality rater guidelines look for. Returns a scored checklist
grouped by E-E-A-T dimension.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

import requests

_TIMEOUT = 10
_UA = "FieldSprout-EEATChecker/1.0"

_REVIEW_TERMS = re.compile(
    r"\b(review|testimonial|rating|star|rated|trust|satisfied|happy|recommend)\b",
    re.IGNORECASE,
)
_CREDENTIAL_TERMS = re.compile(
    r"\b(certif|licens|accredit|award|member|associat|insur|bonded|BBB|NATE|EPA|"
    r"years? (of )?experience|years? in business|founded)\b",
    re.IGNORECASE,
)
_AUTHOR_TERMS = re.compile(
    r"\b(author|written by|by [A-Z][a-z]+|about the author|bio|expert)\b",
    re.IGNORECASE,
)
_SOCIAL_RE = re.compile(
    r"(facebook\.com|twitter\.com|x\.com|linkedin\.com|instagram\.com|youtube\.com)",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_PHONE_RE = re.compile(r"(\+?1[-.\s]?)?(\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4})")
_SCHEMA_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)


def _fetch(url: str) -> Optional[str]:
    try:
        r = requests.get(url, timeout=_TIMEOUT, headers={"User-Agent": _UA},
                         allow_redirects=True)
        r.raise_for_status()
        return r.text
    except Exception:
        return None


def _strip(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html)


def _link_exists(html: str, pattern: str) -> bool:
    return bool(re.search(pattern, html, re.IGNORECASE))


def _check(dimension: str, label: str, status: str, detail: str, fix: str = "") -> Dict:
    return {"dimension": dimension, "label": label,
            "status": status, "detail": detail, "fix": fix}


def audit_eeat(page_url: str) -> Dict[str, Any]:
    """
    Audit `page_url` for E-E-A-T signals.
    Also fetches the homepage for site-level checks.
    Returns {checks, score, error}.
    """
    parsed = urlparse(page_url)
    home_url = f"{parsed.scheme}://{parsed.netloc}"

    page_html = _fetch(page_url)
    if not page_html:
        return {"checks": [], "score": 0, "error": f"Could not fetch {page_url}"}

    home_html = _fetch(home_url) if home_url != page_url else page_html
    if not home_html:
        home_html = page_html

    page_text = _strip(page_html)
    home_text = _strip(home_html)
    checks: List[Dict] = []

    # ── Experience ────────────────────────────────────────────────────────────
    has_testimonials = bool(_REVIEW_TERMS.search(page_text) or
                            _REVIEW_TERMS.search(home_text))
    checks.append(_check(
        "Experience", "Customer Reviews / Testimonials",
        "pass" if has_testimonials else "warn",
        "Review or testimonial content detected." if has_testimonials
        else "No reviews or testimonials found.",
        "" if has_testimonials else
        "Add customer testimonials, star ratings, or a reviews section to demonstrate real-world experience.",
    ))

    has_credentials = bool(_CREDENTIAL_TERMS.search(page_text) or
                           _CREDENTIAL_TERMS.search(home_text))
    checks.append(_check(
        "Experience", "Years of Experience / Credentials",
        "pass" if has_credentials else "warn",
        "Experience or credential language found." if has_credentials
        else "No years-in-business or certification language detected.",
        "" if has_credentials else
        "Mention years of experience, certifications (NATE, EPA, etc.), licensing and insurance.",
    ))

    # ── Expertise ─────────────────────────────────────────────────────────────
    has_author = bool(_AUTHOR_TERMS.search(page_html))
    checks.append(_check(
        "Expertise", "Author / Expert Attribution",
        "pass" if has_author else "warn",
        "Author or expert byline detected on page." if has_author
        else "No author bio or byline found on this page.",
        "" if has_author else
        "Add an author byline with credentials to every blog post and service page.",
    ))

    import json as _json
    schemas = []
    for m in _SCHEMA_RE.finditer(home_html):
        try:
            obj = _json.loads(m.group(1))
            schemas.extend(obj if isinstance(obj, list) else [obj])
            if isinstance(obj, dict) and "@graph" in obj:
                schemas.extend(obj["@graph"])
        except Exception:
            pass
    person_or_org = any(
        s.get("@type") in ("Person", "Organization", "LocalBusiness") for s in schemas
    )
    checks.append(_check(
        "Expertise", "Person/Organization Schema",
        "pass" if person_or_org else "warn",
        "Person or Organization schema found." if person_or_org
        else "No Person or Organization schema on homepage.",
        "" if person_or_org else
        "Add an Organization (or Person) schema to your homepage with name, URL, logo, and contact info.",
    ))

    # ── Authoritativeness ─────────────────────────────────────────────────────
    has_about = _link_exists(home_html, r'href=["\'][^"\']*about[^"\']*["\']')
    checks.append(_check(
        "Authoritativeness", "About Page",
        "pass" if has_about else "fail",
        "About page link found in navigation." if has_about
        else "No link to an About page detected.",
        "" if has_about else
        "Create an About page describing who you are, your team, history, and qualifications.",
    ))

    has_social = bool(_SOCIAL_RE.search(home_html))
    checks.append(_check(
        "Authoritativeness", "Social Media Profiles Linked",
        "pass" if has_social else "warn",
        "Social media links found." if has_social
        else "No social media profile links detected.",
        "" if has_social else
        "Link to your Facebook, Google Business Profile, or other social accounts in the footer.",
    ))

    # External links as a proxy for citations/authority
    ext_links = re.findall(
        rf'href=["\'](https?://(?!{re.escape(parsed.netloc)})[^"\']+)["\']',
        page_html, re.IGNORECASE,
    )
    has_outbound = len(ext_links) >= 2
    checks.append(_check(
        "Authoritativeness", "Outbound Authority Links",
        "pass" if has_outbound else "warn",
        f"Found {len(ext_links)} outbound link(s) to external sources." if ext_links
        else "No outbound links to external authoritative sources.",
        "" if has_outbound else
        "Link to authoritative external sources (manufacturer sites, trade associations, government resources).",
    ))

    # ── Trustworthiness ───────────────────────────────────────────────────────
    is_https = parsed.scheme == "https"
    checks.append(_check(
        "Trust", "HTTPS / SSL",
        "pass" if is_https else "fail",
        "Site uses HTTPS." if is_https else "Site is not using HTTPS.",
        "" if is_https else "Install an SSL certificate immediately — browsers flag HTTP sites as 'Not Secure'.",
    ))

    has_contact = _link_exists(home_html, r'href=["\'][^"\']*contact[^"\']*["\']')
    checks.append(_check(
        "Trust", "Contact Page",
        "pass" if has_contact else "fail",
        "Contact page link found." if has_contact else "No contact page link detected.",
        "" if has_contact else "Add a Contact page with phone, email, address, and a contact form.",
    ))

    has_phone = bool(_PHONE_RE.search(home_text))
    has_email = bool(_EMAIL_RE.search(home_text))
    checks.append(_check(
        "Trust", "Phone / Email Visible",
        "pass" if (has_phone or has_email) else "fail",
        f"Contact info found: phone={has_phone}, email={has_email}.",
        "" if (has_phone or has_email) else
        "Display your phone number and email prominently — at minimum in the header and footer.",
    ))

    has_privacy = _link_exists(home_html, r'href=["\'][^"\']*privacy[^"\']*["\']')
    checks.append(_check(
        "Trust", "Privacy Policy",
        "pass" if has_privacy else "warn",
        "Privacy policy link found." if has_privacy else "No privacy policy link detected.",
        "" if has_privacy else
        "Add a privacy policy page — required for GDPR/CCPA and trusted by Google.",
    ))

    has_terms = _link_exists(home_html, r'href=["\'][^"\']*terms[^"\']*["\']')
    checks.append(_check(
        "Trust", "Terms of Service / Disclaimer",
        "pass" if has_terms else "warn",
        "Terms page link found." if has_terms else "No terms or disclaimer link detected.",
        "" if has_terms else
        "Add a Terms of Service or disclaimer page for additional trust signals.",
    ))

    # ── Score ─────────────────────────────────────────────────────────────────
    weights = {"pass": 2, "warn": 1, "fail": 0}
    score = round(sum(weights[c["status"]] for c in checks) / (len(checks) * 2) * 100)

    by_dimension: Dict[str, List] = {}
    for c in checks:
        by_dimension.setdefault(c["dimension"], []).append(c)

    return {
        "checks":       checks,
        "by_dimension": by_dimension,
        "score":        score,
        "error":        None,
    }
