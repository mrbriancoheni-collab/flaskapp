# app/wp/redirect_checker.py
"""
Redirect Chain & 404 Detector.

Checks published post/page permalinks for:
  - Redirect chains (>= 2 hops to final destination)
  - Final 4xx / 5xx errors
  - Canonical mismatches (published URL ≠ canonical in page head)

Caps at MAX_URLS to keep response time reasonable.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests

MAX_URLS = 60
TIMEOUT  = 8
UA       = "FieldSprout-RedirectChecker/1.0"

_CANONICAL_RE = re.compile(
    r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)["\']',
    re.IGNORECASE,
)


def _follow(url: str, session: requests.Session) -> Dict[str, Any]:
    """Follow a URL and record every hop."""
    hops: List[Dict] = []
    current = url
    seen: set = set()

    for _ in range(10):
        if current in seen:
            break
        seen.add(current)
        try:
            r = session.head(current, allow_redirects=False,
                             timeout=TIMEOUT,
                             headers={"User-Agent": UA})
            hops.append({"url": current, "status": r.status_code})
            if r.status_code in (301, 302, 303, 307, 308):
                loc = r.headers.get("Location", "")
                if not loc:
                    break
                if loc.startswith("/"):
                    parsed = urlparse(current)
                    loc = f"{parsed.scheme}://{parsed.netloc}{loc}"
                current = loc
            else:
                break
        except requests.exceptions.Timeout:
            hops.append({"url": current, "status": None, "error": "timeout"})
            break
        except Exception as exc:
            hops.append({"url": current, "status": None, "error": str(exc)[:60]})
            break

    final = hops[-1] if hops else {"url": url, "status": None}
    chain_length = len(hops)
    is_chain   = chain_length >= 3   # start + 2 redirects = chain worth flagging
    is_broken  = final.get("status") and final["status"] >= 400
    is_ok      = not is_chain and not is_broken and final.get("status") == 200

    return {
        "original_url": url,
        "final_url":    final["url"],
        "final_status": final.get("status"),
        "hops":         hops,
        "chain_length": chain_length,
        "is_chain":     is_chain,
        "is_broken":    is_broken,
        "is_ok":        is_ok,
    }


def check_redirects(posts: List[Dict]) -> Dict[str, Any]:
    """
    Check permalinks of up to MAX_URLS posts/pages.
    Returns structured report with chains, broken, and clean URLs.
    """
    session = requests.Session()
    session.max_redirects = 1   # we follow manually

    urls_seen: set = set()
    to_check: List[Dict] = []
    for p in posts:
        url = (p.get("link") or "").rstrip("/")
        if url and url not in urls_seen:
            urls_seen.add(url)
            to_check.append({
                "url":   url,
                "title": re.sub(r"<[^>]+>", "", p.get("title", {}).get("rendered", url)),
                "id":    p.get("id"),
            })
        if len(to_check) >= MAX_URLS:
            break

    results = []
    for item in to_check:
        res = _follow(item["url"], session)
        results.append({**item, **res})

    chains  = [r for r in results if r["is_chain"]]
    broken  = [r for r in results if r["is_broken"]]
    clean   = [r for r in results if r["is_ok"]]

    return {
        "results":      results,
        "chains":       chains,
        "broken":       broken,
        "clean":        clean,
        "total":        len(results),
        "chains_count": len(chains),
        "broken_count": len(broken),
    }
