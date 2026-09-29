# app/wp/tech_seo.py
"""
Technical SEO audit engine.

Checks (grouped by category):

  Crawlability  — HTTPS redirect, robots.txt analysis, XML sitemap
  Page Health   — homepage status + response time, redirect chains,
                  broken internal links, mixed content
  Performance   — Google PageSpeed Insights (desktop + mobile),
                  Core Web Vitals (LCP, CLS, INP/TBT)
  Security      — HTTPS enforcement, HSTS header, X-Frame-Options

PageSpeed Insights is called without an API key by default (100 req/day
free quota). Pass `psi_api_key` to lift the limit.

Dependencies: requests, beautifulsoup4 — both already in requirements.
"""
from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _check(category: str, label: str, status: str,
           detail: str, fix: str = "", data: Optional[Dict] = None) -> Dict:
    return {
        "category": category,
        "label":    label,
        "status":   status,   # "pass" | "warn" | "fail" | "skip"
        "detail":   detail,
        "fix":      fix,
        "data":     data or {},
    }


def _safe_get(url: str, timeout: int = 10, allow_redirects: bool = True,
              method: str = "GET") -> Optional[Any]:
    """Return (response, elapsed_ms) or (None, None) on error."""
    import requests
    try:
        t0 = time.monotonic()
        fn = requests.head if method == "HEAD" else requests.get
        r = fn(
            url, timeout=timeout,
            allow_redirects=allow_redirects,
            headers={"User-Agent": "Mozilla/5.0 (compatible; TechSEOBot/1.0)"},
        )
        return r, int((time.monotonic() - t0) * 1000)
    except Exception:
        return None, None


def _normalise(url: str) -> str:
    """Ensure url has a scheme."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url.rstrip("/")


# ─────────────────────────────────────────────────────────────────────────────
# Individual checks
# ─────────────────────────────────────────────────────────────────────────────

def _chk_https(base: str, parsed: Any) -> Dict:
    cat = "Security"
    if parsed.scheme == "https":
        # Confirm http:// version redirects to https://
        http_url = "http://" + parsed.netloc + (parsed.path or "/")
        resp, _ = _safe_get(http_url, allow_redirects=True)
        if resp and resp.url.startswith("https://"):
            return _check(cat, "HTTPS Redirect", "pass",
                          "HTTP correctly redirects to HTTPS.")
        elif resp:
            return _check(cat, "HTTPS Redirect", "warn",
                          f"HTTP version returned {resp.status_code} without HTTPS redirect.",
                          "Set up a permanent 301 redirect from http:// to https:// at the server level.")
        else:
            return _check(cat, "HTTPS Redirect", "skip",
                          "Could not reach HTTP version to verify redirect.")
    else:
        resp, _ = _safe_get(base, allow_redirects=True)
        if resp and resp.url.startswith("https://"):
            return _check(cat, "HTTPS Redirect", "warn",
                          "Site eventually reaches HTTPS but is configured with http:// base URL.",
                          "Update WordPress Site URL to https:// in Settings → General.")
        return _check(cat, "HTTPS Redirect", "fail",
                      "Site is not using HTTPS.",
                      "Install an SSL certificate and force HTTPS. Most hosts provide free SSL via Let's Encrypt.")


def _chk_hsts(base: str) -> Dict:
    cat = "Security"
    resp, _ = _safe_get(base)
    if not resp:
        return _check(cat, "HSTS Header", "skip", "Could not fetch site to check headers.")
    hsts = resp.headers.get("Strict-Transport-Security", "")
    if hsts:
        max_age = re.search(r"max-age=(\d+)", hsts)
        age_days = int(max_age.group(1)) // 86400 if max_age else 0
        if age_days >= 180:
            return _check(cat, "HSTS Header", "pass",
                          f"HSTS present (max-age={age_days} days).")
        return _check(cat, "HSTS Header", "warn",
                      f"HSTS present but max-age only {age_days} days.",
                      "Set max-age to at least 180 days (15552000 seconds).")
    return _check(cat, "HSTS Header", "warn",
                  "No HSTS header found.",
                  "Add 'Strict-Transport-Security: max-age=31536000; includeSubDomains' "
                  "to your server response headers.")


def _chk_robots(base: str) -> Dict:
    cat = "Crawlability"
    robots_url = base + "/robots.txt"
    resp, _ = _safe_get(robots_url)
    if not resp or resp.status_code != 200:
        return _check(cat, "Robots.txt", "warn",
                      "No robots.txt found (or not accessible).",
                      "Create a robots.txt at the domain root. "
                      "WordPress generates one automatically when Search Engine Visibility is enabled.",
                      data={"url": robots_url})

    text = resp.text
    lines = [l.strip() for l in text.splitlines()]

    # Check for blanket block
    disallow_all = any(
        l.lower() == "disallow: /" for l in lines
        if not l.startswith("#")
    )

    # Check for sitemap declaration
    sitemap_in_robots = any(l.lower().startswith("sitemap:") for l in lines)

    # Suspicious disallows for wp-json / wp-content
    suspect = [l for l in lines
               if l.lower().startswith("disallow:") and
               any(p in l.lower() for p in ["/wp-json", "/?", "/feed"])]

    if disallow_all:
        return _check(cat, "Robots.txt", "fail",
                      "Robots.txt has 'Disallow: /' — your entire site is blocked from indexing!",
                      "In WordPress: go to Settings → Reading and uncheck 'Discourage search engines'. "
                      "Then verify robots.txt no longer contains 'Disallow: /'.",
                      data={"url": robots_url, "sitemap_listed": sitemap_in_robots})

    if suspect:
        return _check(cat, "Robots.txt", "warn",
                      f"Robots.txt disallows potentially important paths: {', '.join(suspect[:3])}",
                      "Review these disallow rules — blocking /wp-json can break integrations, "
                      "blocking /feed can hurt RSS subscribers.",
                      data={"url": robots_url, "sitemap_listed": sitemap_in_robots,
                            "suspect_rules": suspect})

    return _check(cat, "Robots.txt", "pass",
                  "Robots.txt present with no critical blocking rules." +
                  (" Sitemap declared." if sitemap_in_robots else " No sitemap declaration found."),
                  "" if sitemap_in_robots else
                  "Add 'Sitemap: https://yourdomain.com/sitemap.xml' to robots.txt.",
                  data={"url": robots_url, "sitemap_listed": sitemap_in_robots})


def _chk_sitemap(base: str) -> Dict:
    cat = "Crawlability"
    candidates = [
        base + "/sitemap.xml",
        base + "/sitemap_index.xml",
        base + "/wp-sitemap.xml",
    ]
    found_url = None
    for url in candidates:
        r, _ = _safe_get(url)
        if r and r.status_code == 200 and "xml" in r.headers.get("content-type", "").lower():
            found_url = url
            text = r.text
            break
        elif r and r.status_code == 200 and ("<urlset" in (r.text or "")[:500] or "<sitemapindex" in (r.text or "")[:500]):
            found_url = url
            text = r.text
            break

    if not found_url:
        return _check(cat, "XML Sitemap", "fail",
                      "No XML sitemap found at common WordPress paths.",
                      "Install Yoast SEO or RankMath to auto-generate a sitemap, "
                      "or enable the WordPress core sitemap (Settings → Reading).",
                      data={"checked": candidates})

    # Count URLs
    url_count = text.count("<url>") + text.count("<sitemap>")
    is_index  = "<sitemapindex" in text[:500]

    if url_count == 0:
        return _check(cat, "XML Sitemap", "warn",
                      f"Sitemap found at {found_url} but appears empty.",
                      "Regenerate the sitemap via your SEO plugin. "
                      "Check that posts/pages are not set to noindex.",
                      data={"url": found_url, "is_index": is_index})

    return _check(cat, "XML Sitemap", "pass",
                  f"{'Sitemap index' if is_index else 'Sitemap'} found with {url_count} "
                  f"{'child sitemap(s)' if is_index else 'URL(s)'}.",
                  data={"url": found_url, "url_count": url_count, "is_index": is_index})


def _chk_homepage(base: str) -> Dict:
    cat = "Page Health"
    resp, ms = _safe_get(base)
    if not resp:
        return _check(cat, "Homepage Status", "fail",
                      "Homepage did not respond.",
                      "Check your server is running and the URL is correct.")

    hops = len(resp.history)
    final = resp.url

    if resp.status_code != 200:
        return _check(cat, "Homepage Status", "fail",
                      f"Homepage returned HTTP {resp.status_code}.",
                      "Investigate the server error. Check error logs and WordPress health checks.",
                      data={"status_code": resp.status_code, "elapsed_ms": ms})

    detail = f"200 OK in {ms}ms"
    if hops:
        detail += f" (via {hops} redirect{'s' if hops > 1 else ''})"
    if hops > 1:
        return _check(cat, "Homepage Status", "warn", detail,
                      f"Homepage goes through {hops} redirects before landing. "
                      "Reduce to 1 redirect max — chains add latency and dilute link equity.",
                      data={"status_code": 200, "elapsed_ms": ms, "hops": hops,
                            "final_url": final})

    speed_status = "pass" if ms < 1500 else ("warn" if ms < 3000 else "fail")
    fix = ("" if speed_status == "pass" else
           "Server response time is high. Check hosting, enable caching (WP Super Cache / W3 Total Cache), "
           "and use a CDN." if speed_status == "warn" else
           "Very slow server response. Upgrade hosting, enable OPcache, and profile database queries.")

    return _check(cat, "Homepage Status", speed_status, detail, fix,
                  data={"status_code": 200, "elapsed_ms": ms, "hops": hops,
                        "final_url": final})


def _chk_broken_links(base: str) -> Dict:
    """Crawl homepage and HEAD-check up to 20 internal links."""
    import requests
    from bs4 import BeautifulSoup
    cat = "Page Health"

    resp, _ = _safe_get(base)
    if not resp or resp.status_code != 200:
        return _check(cat, "Broken Internal Links", "skip",
                      "Could not fetch homepage to check links.")

    soup = BeautifulSoup(resp.text, "html.parser")
    domain = urlparse(base).netloc

    hrefs = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith("/") and not href.startswith("//"):
            hrefs.append(urljoin(base, href))
        elif domain in href and href.startswith("http"):
            hrefs.append(href)

    # Dedupe and cap at 20
    seen: set = set()
    unique = []
    for h in hrefs:
        norm = h.rstrip("/")
        if norm not in seen and len(unique) < 20:
            seen.add(norm)
            unique.append(h)

    if not unique:
        return _check(cat, "Broken Internal Links", "skip",
                      "No internal links found on homepage to check.")

    broken, redirected, ok = [], [], []
    for url in unique:
        r, _ = _safe_get(url, timeout=8, method="HEAD")
        if r is None:
            broken.append({"url": url, "status": "timeout"})
        elif r.status_code >= 400:
            broken.append({"url": url, "status": r.status_code})
        elif r.status_code >= 300:
            redirected.append({"url": url, "status": r.status_code,
                               "location": r.headers.get("Location", "")})
        else:
            ok.append(url)

    if broken:
        ex = broken[:3]
        detail = (f"{len(broken)} broken link(s) found in {len(unique)} checked. "
                  f"Examples: {', '.join(b['url'].replace(base,'') for b in ex)}")
        return _check(cat, "Broken Internal Links", "fail" if len(broken) >= 3 else "warn",
                      detail,
                      "Fix or redirect these broken URLs. Use a redirect plugin (Redirection) "
                      "or update the links in WordPress.",
                      data={"checked": len(unique), "broken": broken[:10],
                            "redirected": len(redirected), "ok": len(ok)})

    detail = f"All {len(unique)} internal links checked — none broken."
    if redirected:
        detail += f" {len(redirected)} redirect(s) found."
    return _check(cat, "Broken Internal Links", "pass", detail,
                  data={"checked": len(unique), "broken": [],
                        "redirected": len(redirected), "ok": len(ok)})


def _chk_mixed_content(base: str) -> Dict:
    cat = "Security"
    if not base.startswith("https://"):
        return _check(cat, "Mixed Content", "skip",
                      "Site is not on HTTPS — fix HTTPS first.")

    import requests
    from bs4 import BeautifulSoup

    resp, _ = _safe_get(base)
    if not resp:
        return _check(cat, "Mixed Content", "skip", "Could not fetch homepage.")

    soup = BeautifulSoup(resp.text, "html.parser")
    http_assets = []
    for tag, attr in [("img", "src"), ("script", "src"), ("link", "href"),
                      ("iframe", "src"), ("source", "src")]:
        for el in soup.find_all(tag, **{attr: True}):
            val = el[attr]
            if val.startswith("http://"):
                http_assets.append(val[:80])

    if not http_assets:
        return _check(cat, "Mixed Content", "pass",
                      "No HTTP assets found on homepage — no mixed content detected.")

    return _check(cat, "Mixed Content", "warn",
                  f"{len(http_assets)} HTTP asset(s) on an HTTPS page.",
                  "Update asset URLs to https:// or use protocol-relative URLs (//).",
                  data={"examples": http_assets[:5]})


def _chk_viewport(base: str) -> Dict:
    """Check viewport meta tag for mobile-readiness."""
    import requests
    from bs4 import BeautifulSoup
    cat = "Performance"

    resp, _ = _safe_get(base)
    if not resp:
        return _check(cat, "Viewport Meta Tag", "skip", "Could not fetch page.")

    soup = BeautifulSoup(resp.text, "html.parser")
    vp = soup.find("meta", attrs={"name": re.compile(r"viewport", re.I)})
    if vp and "width=device-width" in (vp.get("content", "")):
        return _check(cat, "Viewport Meta Tag", "pass",
                      "Viewport meta tag correctly set for responsive display.")
    elif vp:
        return _check(cat, "Viewport Meta Tag", "warn",
                      f"Viewport tag present but content may be misconfigured: \"{vp.get('content','')}\"",
                      "Set to: <meta name='viewport' content='width=device-width, initial-scale=1'>")
    return _check(cat, "Viewport Meta Tag", "fail",
                  "No viewport meta tag found.",
                  "Add <meta name='viewport' content='width=device-width, initial-scale=1'> "
                  "inside <head>. Without it, mobile browsers render at desktop width.")


def _chk_pagespeed(base: str, psi_api_key: Optional[str]) -> List[Dict]:
    """
    Call PageSpeed Insights API for both desktop and mobile.
    Returns a list of check dicts (performance, CWV).
    Gracefully skips if the API is unreachable.
    """
    import requests as req

    checks: List[Dict] = []
    cat = "Performance"

    def _psi(strategy: str) -> Optional[Dict]:
        params: Dict[str, str] = {"url": base, "strategy": strategy}
        if psi_api_key:
            params["key"] = psi_api_key
        try:
            r = req.get(
                "https://www.googleapis.com/pagespeedonline/v5/runPagespeed",
                params=params,
                timeout=30,
            )
            if r.status_code == 200:
                return r.json()
            return None
        except Exception:
            return None

    def _score_label(s: float) -> tuple:
        """Return (status, label) for a 0-1 score."""
        if s >= 0.9:
            return "pass", f"{int(s*100)}/100"
        if s >= 0.5:
            return "warn", f"{int(s*100)}/100"
        return "fail", f"{int(s*100)}/100"

    def _lcp_status(val_ms: float) -> str:
        if val_ms <= 2500: return "pass"
        if val_ms <= 4000: return "warn"
        return "fail"

    def _cls_status(val: float) -> str:
        if val <= 0.1: return "pass"
        if val <= 0.25: return "warn"
        return "fail"

    def _inp_status(val_ms: float) -> str:
        if val_ms <= 200: return "pass"
        if val_ms <= 500: return "warn"
        return "fail"

    for strategy in ("desktop", "mobile"):
        data = _psi(strategy)
        if not data:
            checks.append(_check(cat, f"PageSpeed ({strategy.title()})", "skip",
                                  "PageSpeed Insights API did not respond.",
                                  "Add a GOOGLE_PSI_API_KEY env var for reliable results."))
            continue

        lh   = data.get("lighthouseResult", {})
        cats = lh.get("categories", {})
        perf = cats.get("performance", {}).get("score", 0) or 0
        audits = lh.get("audits", {})

        status, label = _score_label(perf)
        fix = ("" if status == "pass" else
               "Focus on image optimisation, JavaScript deferral, and server response time." if status == "warn" else
               "Critical performance issues. Prioritise: eliminate render-blocking resources, "
               "compress images, enable server-side caching, and consider a CDN.")

        # Extract key metrics
        def _ms(audit_id: str) -> Optional[float]:
            a = audits.get(audit_id, {})
            return a.get("numericValue")

        def _display(audit_id: str) -> str:
            return audits.get(audit_id, {}).get("displayValue", "n/a")

        lcp_ms  = _ms("largest-contentful-paint")
        cls_val = _ms("cumulative-layout-shift")
        tbt_ms  = _ms("total-blocking-time")
        fcp_ms  = _ms("first-contentful-paint")
        si_ms   = _ms("speed-index")

        metric_data = {
            "score":        int(perf * 100),
            "strategy":     strategy,
            "lcp":          {"ms": lcp_ms, "display": _display("largest-contentful-paint")},
            "cls":          {"val": cls_val, "display": _display("cumulative-layout-shift")},
            "tbt":          {"ms": tbt_ms, "display": _display("total-blocking-time")},
            "fcp":          {"ms": fcp_ms, "display": _display("first-contentful-paint")},
            "speed_index":  {"ms": si_ms, "display": _display("speed-index")},
        }

        # Field data (real-user metrics) if available
        le = data.get("loadingExperience", {})
        le_metrics = le.get("metrics", {})
        if le_metrics:
            metric_data["field_lcp"]  = le_metrics.get("LARGEST_CONTENTFUL_PAINT_MS", {})
            metric_data["field_cls"]  = le_metrics.get("CUMULATIVE_LAYOUT_SHIFT_SCORE", {})
            metric_data["field_inp"]  = le_metrics.get("INTERACTION_TO_NEXT_PAINT", {})
            metric_data["field_cat"]  = le.get("overall_category", "")

        checks.append(_check(cat, f"PageSpeed Score ({strategy.title()})", status,
                             f"{strategy.title()} performance score: {label}", fix,
                             data=metric_data))

        # Core Web Vitals (only report once for mobile as that's what Google uses)
        if strategy == "mobile":
            if lcp_ms is not None:
                lcp_s = _lcp_status(lcp_ms)
                lcp_fix = ("" if lcp_s == "pass" else
                           "Improve LCP by optimising your hero image (compress, use WebP, preload) "
                           "and reducing server response time.")
                checks.append(_check(cat, "Core Web Vital: LCP",
                                     lcp_s,
                                     f"Largest Contentful Paint: {_display('largest-contentful-paint')} "
                                     f"(good < 2.5s)",
                                     lcp_fix,
                                     data={"ms": lcp_ms, "threshold_good": 2500,
                                           "threshold_warn": 4000}))

            if cls_val is not None:
                cls_s = _cls_status(cls_val)
                cls_fix = ("" if cls_s == "pass" else
                           "Fix layout shifts by adding explicit width/height to images and embeds, "
                           "and avoid inserting content above existing content after page load.")
                checks.append(_check(cat, "Core Web Vital: CLS",
                                     cls_s,
                                     f"Cumulative Layout Shift: {_display('cumulative-layout-shift')} "
                                     f"(good < 0.1)",
                                     cls_fix,
                                     data={"val": cls_val, "threshold_good": 0.1,
                                           "threshold_warn": 0.25}))

            if tbt_ms is not None:
                inp_s = _inp_status(tbt_ms)
                inp_fix = ("" if inp_s == "pass" else
                           "Reduce Total Blocking Time by deferring non-critical JavaScript, "
                           "splitting long tasks, and removing unused JS/CSS.")
                checks.append(_check(cat, "Core Web Vital: TBT/INP",
                                     inp_s,
                                     f"Total Blocking Time: {_display('total-blocking-time')} "
                                     f"(proxy for INP; good < 200ms)",
                                     inp_fix,
                                     data={"ms": tbt_ms, "threshold_good": 200,
                                           "threshold_warn": 500}))

    return checks


# ─────────────────────────────────────────────────────────────────────────────
# Public entry-point
# ─────────────────────────────────────────────────────────────────────────────

def run_technical_audit(base_url: str,
                        psi_api_key: Optional[str] = None) -> Dict[str, Any]:
    """
    Run a full technical SEO audit against *base_url*.

    Returns:
        {
          url, health_score (0-100),
          checks,           # list of check dicts
          by_category,      # dict: category → list of checks
          summary,          # {pass, warn, fail, skip} counts
          priority_fixes,   # top failing/warning items with a fix
          psi_available,    # bool
          error             # None on success
        }
    """
    base_url = _normalise(base_url)
    parsed   = urlparse(base_url)

    result: Dict[str, Any] = {
        "url":           base_url,
        "health_score":  0,
        "checks":        [],
        "by_category":   {},
        "summary":       {"pass": 0, "warn": 0, "fail": 0, "skip": 0},
        "priority_fixes": [],
        "psi_available": False,
        "error":         None,
    }

    # Quick connectivity check
    resp, _ = _safe_get(base_url, timeout=8)
    if resp is None:
        result["error"] = f"Could not reach {base_url}. Check the URL and try again."
        return result

    checks: List[Dict] = []

    # ── Crawlability ──────────────────────────────────────────────────────────
    checks.append(_chk_https(base_url, parsed))
    checks.append(_chk_robots(base_url))
    checks.append(_chk_sitemap(base_url))

    # ── Page Health ───────────────────────────────────────────────────────────
    checks.append(_chk_homepage(base_url))
    checks.append(_chk_broken_links(base_url))
    checks.append(_chk_mixed_content(base_url))

    # ── Security ──────────────────────────────────────────────────────────────
    checks.append(_chk_hsts(base_url))

    # ── Performance / CWV ────────────────────────────────────────────────────
    checks.append(_chk_viewport(base_url))
    psi_checks = _chk_pagespeed(base_url, psi_api_key)
    checks.extend(psi_checks)
    result["psi_available"] = any(c["status"] != "skip" for c in psi_checks)

    # ── Scoring ───────────────────────────────────────────────────────────────
    # Weight: fail = 0, warn = 0.5, pass = 1 of each check's max contribution.
    # Skip checks are excluded from the denominator.
    scored = [c for c in checks if c["status"] != "skip"]
    if scored:
        weights = {"pass": 1.0, "warn": 0.5, "fail": 0.0}
        total = sum(weights.get(c["status"], 0) for c in scored)
        result["health_score"] = round(total / len(scored) * 100)

    # ── Summaries ────────────────────────────────────────────────────────────
    for c in checks:
        result["summary"][c["status"]] = result["summary"].get(c["status"], 0) + 1

    # Group by category
    by_cat: Dict[str, List] = {}
    for c in checks:
        by_cat.setdefault(c["category"], []).append(c)
    result["by_category"] = by_cat

    # Priority fixes — fails first, then warns, max 8
    fails = [c for c in checks if c["status"] == "fail" and c["fix"]]
    warns = [c for c in checks if c["status"] == "warn" and c["fix"]]
    result["priority_fixes"] = (fails + warns)[:8]

    result["checks"] = checks
    return result
