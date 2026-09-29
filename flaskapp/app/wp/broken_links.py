# app/wp/broken_links.py
"""
Broken Link Scanner.

Fetches published WP posts via REST API, extracts all href links,
and HEAD-checks each one with a short timeout. Returns a structured
report grouped by post. Caps at MAX_POSTS posts and MAX_LINKS total
to keep scan time reasonable (typically 5-30 s).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

import requests

MAX_POSTS = 30
MAX_LINKS = 80
REQUEST_TIMEOUT = 6  # seconds per link
_SKIP_SCHEMES = {"mailto", "tel", "javascript", "data", "#"}

_HREF_RE = re.compile(r'<a\b[^>]*\shref=["\']([^"\']+)["\']', re.IGNORECASE)


def _extract_links(html: str, base_url: str) -> List[str]:
    raw = _HREF_RE.findall(html)
    links = []
    seen: set = set()
    for href in raw:
        href = href.strip()
        scheme = href.split(":")[0].lower() if ":" in href else ""
        if scheme in _SKIP_SCHEMES or href.startswith("#"):
            continue
        if href.startswith("//"):
            href = "https:" + href
        elif href.startswith("/"):
            parsed = urlparse(base_url)
            href = f"{parsed.scheme}://{parsed.netloc}{href}"
        elif not href.startswith("http"):
            href = urljoin(base_url, href)
        if href not in seen:
            seen.add(href)
            links.append(href)
    return links


def _check_link(url: str, session: requests.Session) -> Dict[str, Any]:
    try:
        r = session.head(url, allow_redirects=True, timeout=REQUEST_TIMEOUT)
        status = r.status_code
        return {
            "url": url,
            "status": status,
            "ok": 200 <= status < 400,
            "broken": status in (404, 410, 400),
            "redirect": status in (301, 302, 303, 307, 308),
            "error": None,
        }
    except requests.exceptions.SSLError:
        return {"url": url, "status": None, "ok": False, "broken": False,
                "redirect": False, "error": "ssl_error"}
    except requests.exceptions.ConnectionError:
        return {"url": url, "status": None, "ok": False, "broken": True,
                "redirect": False, "error": "connection_error"}
    except requests.exceptions.Timeout:
        return {"url": url, "status": None, "ok": False, "broken": False,
                "redirect": False, "error": "timeout"}
    except Exception as exc:
        return {"url": url, "status": None, "ok": False, "broken": False,
                "redirect": False, "error": str(exc)[:80]}


def scan_broken_links(
    posts: List[Dict],
    site_base_url: str,
) -> Dict[str, Any]:
    """
    Scan up to MAX_POSTS posts for broken links.
    Returns:
      {
        "posts": [{ post_id, title, url, links: [{url, status, ok, broken, ...}] }],
        "total_links": int,
        "broken_count": int,
        "posts_scanned": int,
      }
    """
    session = requests.Session()
    session.headers["User-Agent"] = "FieldSprout-LinkScanner/1.0"

    result_posts = []
    total_links = 0
    broken_count = 0
    posts_to_scan = posts[:MAX_POSTS]

    for post in posts_to_scan:
        if total_links >= MAX_LINKS:
            break
        pid = post.get("id")
        title = post.get("title", {}).get("rendered", f"Post {pid}")
        post_url = post.get("link", "")
        body = post.get("content", {}).get("rendered", "") or ""

        links = _extract_links(body, site_base_url)
        if not links:
            continue

        remaining = MAX_LINKS - total_links
        links = links[:remaining]

        checked = []
        for link in links:
            res = _check_link(link, session)
            checked.append(res)
            if res["broken"]:
                broken_count += 1
        total_links += len(checked)

        post_broken = sum(1 for c in checked if c["broken"])
        result_posts.append({
            "post_id":     pid,
            "title":       re.sub(r"<[^>]+>", "", title),
            "url":         post_url,
            "links":       checked,
            "link_count":  len(checked),
            "broken_count": post_broken,
        })

    result_posts.sort(key=lambda p: p["broken_count"], reverse=True)
    return {
        "posts":         result_posts,
        "total_links":   total_links,
        "broken_count":  broken_count,
        "posts_scanned": len(posts_to_scan),
    }
