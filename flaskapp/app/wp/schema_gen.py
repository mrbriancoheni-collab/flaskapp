# app/wp/schema_gen.py
"""
Schema Markup Generator — Phase 3.

Auto-detects and generates JSON-LD structured data from WordPress post
content or any public URL.  Supports:

  Article        — every post/page
  FAQPage        — Q&A headings / explicit FAQ sections
  HowTo          — numbered step lists
  BreadcrumbList — built from category hierarchy
  LocalBusiness  — when business info is supplied

Injection: appends JSON-LD as a Gutenberg HTML block (or plain <script>
for classic editor posts) to the WordPress post via the REST API.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple


# ─────────────────────────────────────────────────────────────────────────────
# HTML fetching / parsing helpers
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_html(url: str) -> Optional[Tuple[str, str]]:
    """Return (html, final_url) or (None, None)."""
    import requests
    try:
        r = requests.get(
            url, timeout=15,
            headers={"User-Agent": "Mozilla/5.0 (compatible; SchemaBot/1.0)",
                     "Accept": "text/html"},
            allow_redirects=True,
        )
        r.raise_for_status()
        return r.text, r.url
    except Exception:
        return None, None


def _meta(soup: Any, name: str) -> str:
    el = (soup.find("meta", attrs={"name": re.compile(name, re.I)}) or
          soup.find("meta", attrs={"property": re.compile(name, re.I)}))
    return (el.get("content", "") if el else "").strip()


# ─────────────────────────────────────────────────────────────────────────────
# Content analysis — FAQ extraction
# ─────────────────────────────────────────────────────────────────────────────

_QUESTION_RE = re.compile(
    r"^(what|how|why|when|where|who|which|can|do|does|is|are|should|will)\b",
    re.I,
)


def _extract_faq(soup: Any) -> List[Dict[str, str]]:
    """
    Find question headings (H2/H3 ending in '?' or starting with a
    question word) and collect the following paragraph(s) as the answer.
    Returns [{q, a}, …].
    """
    pairs: List[Dict[str, str]] = []
    for tag in soup.find_all(["h2", "h3"]):
        text = tag.get_text(strip=True)
        if not (text.endswith("?") or _QUESTION_RE.match(text)):
            continue
        answer_parts: List[str] = []
        for sib in tag.find_next_siblings():
            if sib.name in ("h2", "h3", "h4"):
                break
            if sib.name in ("p", "ul", "ol"):
                answer_parts.append(sib.get_text(separator=" ", strip=True))
                if len(answer_parts) >= 3:
                    break
        if answer_parts:
            pairs.append({"q": text, "a": " ".join(answer_parts)})
    return pairs[:10]  # cap at 10 Q&As


# ─────────────────────────────────────────────────────────────────────────────
# Content analysis — HowTo step extraction
# ─────────────────────────────────────────────────────────────────────────────

def _extract_howto_steps(soup: Any) -> List[Dict[str, str]]:
    """
    Find the first <ol> with 3+ items and treat each <li> as a HowToStep.
    Falls back to scanning for strong/bold-prefixed list items.
    Returns [{name, text}, …].
    """
    for ol in soup.find_all("ol"):
        items = ol.find_all("li", recursive=False)
        if len(items) < 3:
            continue
        steps: List[Dict[str, str]] = []
        for li in items:
            full = li.get_text(separator=" ", strip=True)
            # If the item has a bold/strong lead, use it as the step name
            strong = li.find(["strong", "b"])
            if strong:
                name = strong.get_text(strip=True).rstrip(":.—-").strip()
                text = full
            else:
                # First 8 words as name
                words = full.split()
                name = " ".join(words[:8])
                text = full
            steps.append({"name": name, "text": text})
        return steps[:12]
    return []


# ─────────────────────────────────────────────────────────────────────────────
# Schema builders
# ─────────────────────────────────────────────────────────────────────────────

def _build_article(title: str, url: str, author: str,
                   date_published: str, date_modified: str,
                   image_url: str, description: str) -> Dict:
    obj: Dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": title[:110] if title else "",
        "url": url,
    }
    if author:
        obj["author"] = {"@type": "Person", "name": author}
    if date_published:
        obj["datePublished"] = date_published
    if date_modified:
        obj["dateModified"] = date_modified
    if image_url:
        obj["image"] = image_url
    if description:
        obj["description"] = description[:250]
    return obj


def _build_faq(pairs: List[Dict[str, str]]) -> Dict:
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": p["q"],
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": p["a"],
                },
            }
            for p in pairs
        ],
    }


def _build_howto(title: str, description: str,
                 steps: List[Dict[str, str]]) -> Dict:
    return {
        "@context": "https://schema.org",
        "@type": "HowTo",
        "name": title,
        "description": description[:250] if description else "",
        "step": [
            {
                "@type": "HowToStep",
                "name": s["name"],
                "text": s["text"],
            }
            for s in steps
        ],
    }


def _build_breadcrumb(items: List[Dict[str, str]]) -> Dict:
    """items = [{name, url}, …] in order from root to current."""
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": i + 1,
                "name": item["name"],
                "item": item["url"],
            }
            for i, item in enumerate(items)
        ],
    }


def _build_local_business(name: str, url: str, phone: str,
                           address: str, business_type: str = "LocalBusiness") -> Dict:
    obj: Dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": business_type or "LocalBusiness",
        "name": name,
        "url": url,
    }
    if phone:
        obj["telephone"] = phone
    if address:
        obj["address"] = {
            "@type": "PostalAddress",
            "streetAddress": address,
        }
    return obj


# ─────────────────────────────────────────────────────────────────────────────
# WordPress injection
# ─────────────────────────────────────────────────────────────────────────────

def _is_gutenberg(content: str) -> bool:
    return "<!-- wp:" in (content or "")


def inject_schema_into_post(
    wp_client: Any,
    post_id: int,
    schemas: List[Dict],
    replace_existing: bool = False,
) -> Dict[str, Any]:
    """
    Fetch `post_id` via `wp_client`, append the JSON-LD, and save.
    Returns {ok, post_id, link, error}.
    """
    try:
        post = wp_client.get_post(post_id)
    except Exception as exc:
        return {"ok": False, "error": f"Could not fetch post {post_id}: {exc}"}

    content = post.get("content", {}).get("rendered", "") or ""

    # Build the combined script block
    combined = json.dumps(schemas if len(schemas) > 1 else schemas[0],
                          indent=2, ensure_ascii=False)
    if len(schemas) > 1:
        # Multiple schemas → wrap in array for single <script> tag
        json_str = combined
    else:
        json_str = combined

    script_block = f'<script type="application/ld+json">\n{json_str}\n</script>'

    if _is_gutenberg(content):
        block = (f"\n<!-- wp:html -->\n{script_block}\n<!-- /wp:html -->")
    else:
        block = f"\n{script_block}"

    # Strip existing injected schema if replacing
    MARKER_RE = re.compile(
        r"(?:<!-- wp:html -->\n?)?<script[^>]+application/ld\+json[^>]*>.*?</script>\n?(?:<!-- /wp:html -->\n?)?",
        re.DOTALL,
    )
    if replace_existing:
        content = MARKER_RE.sub("", content).strip()

    # Don't double-inject
    if "application/ld+json" in content and not replace_existing:
        return {
            "ok": False,
            "error": "Post already contains JSON-LD schema. "
                     "Use 'Replace existing schema' to overwrite.",
        }

    new_content = content + block

    try:
        res = wp_client.create_or_update_post(
            post_id=post_id,
            title=post["title"]["rendered"],
            html=new_content,
            status=post.get("status", "publish"),
        )
        return {"ok": True, "post_id": post_id, "link": res.get("link", ""), "error": None}
    except Exception as exc:
        return {"ok": False, "error": f"Could not save post: {exc}"}


# ─────────────────────────────────────────────────────────────────────────────
# Public entry-point
# ─────────────────────────────────────────────────────────────────────────────

def generate_from_url(
    url: str,
    *,
    # manual overrides (all optional — auto-detected if blank)
    override_title: str = "",
    override_author: str = "",
    override_description: str = "",
    override_date_published: str = "",
    override_date_modified: str = "",
    override_image_url: str = "",
    # schema type selection
    include_article: bool = True,
    include_faq: bool = True,        # auto-skipped if no Q&As found
    include_howto: bool = True,       # auto-skipped if no steps found
    include_breadcrumb: bool = False,
    breadcrumb_items: Optional[List[Dict]] = None,
    # LocalBusiness
    include_local_business: bool = False,
    business_name: str = "",
    business_phone: str = "",
    business_address: str = "",
    business_type: str = "LocalBusiness",
) -> Dict[str, Any]:
    """
    Fetch *url*, analyse the content, and generate JSON-LD schemas.

    Returns:
        {
          url, title, description,
          detected_types: [str],
          schemas: [dict],          # raw schema objects
          combined_json: str,       # formatted JSON-LD for the <script> tag
          faq_pairs: [{q, a}],
          howto_steps: [{name, text}],
          error: None | str
        }
    """
    from bs4 import BeautifulSoup

    result: Dict[str, Any] = {
        "url": url,
        "title": override_title,
        "description": override_description,
        "detected_types": [],
        "schemas": [],
        "combined_json": "",
        "faq_pairs": [],
        "howto_steps": [],
        "error": None,
    }

    html, final_url = _fetch_html(url)
    if not html:
        result["error"] = f"Could not fetch {url}"
        return result

    soup = BeautifulSoup(html, "html.parser")

    # ── auto-extract metadata ──────────────────────────────────────────────
    title = override_title or (
        (soup.find("title") or soup.new_tag("x")).get_text(strip=True)
        or _meta(soup, "og:title")
    )
    description = override_description or (
        _meta(soup, "description") or _meta(soup, "og:description")
    )
    author = override_author or _meta(soup, "author")
    date_pub  = override_date_published  or _meta(soup, "article:published_time") or _meta(soup, "datePublished")
    date_mod  = override_date_modified   or _meta(soup, "article:modified_time")  or _meta(soup, "dateModified")
    image_url = override_image_url       or _meta(soup, "og:image")

    # If no og:image, take first <img> with a non-tiny src
    if not image_url:
        for img in soup.find_all("img", src=True):
            src = img["src"]
            if src.startswith("http") and not any(
                x in src.lower() for x in ["icon", "logo", "pixel", "1x1", "blank"]
            ):
                image_url = src
                break

    result["title"] = title
    result["description"] = description

    # ── content analysis ───────────────────────────────────────────────────
    faq_pairs    = _extract_faq(soup)
    howto_steps  = _extract_howto_steps(soup)
    result["faq_pairs"]   = faq_pairs
    result["howto_steps"] = howto_steps

    schemas: List[Dict] = []

    # Article
    if include_article:
        schemas.append(_build_article(title, final_url, author,
                                      date_pub, date_mod, image_url, description))
        result["detected_types"].append("Article")

    # FAQPage
    if include_faq and faq_pairs:
        schemas.append(_build_faq(faq_pairs))
        result["detected_types"].append("FAQPage")

    # HowTo
    if include_howto and howto_steps:
        schemas.append(_build_howto(title, description, howto_steps))
        result["detected_types"].append("HowTo")

    # BreadcrumbList
    if include_breadcrumb and breadcrumb_items:
        schemas.append(_build_breadcrumb(breadcrumb_items))
        result["detected_types"].append("BreadcrumbList")

    # LocalBusiness
    if include_local_business and business_name:
        schemas.append(_build_local_business(
            business_name, final_url, business_phone,
            business_address, business_type,
        ))
        result["detected_types"].append("LocalBusiness")

    result["schemas"] = schemas

    # Combined JSON-LD — use a @graph if multiple schemas
    if len(schemas) > 1:
        combined_obj = {
            "@context": "https://schema.org",
            "@graph": [{k: v for k, v in s.items() if k != "@context"}
                       for s in schemas],
        }
    elif schemas:
        combined_obj = schemas[0]
    else:
        combined_obj = {}

    result["combined_json"] = json.dumps(combined_obj, indent=2, ensure_ascii=False)
    return result


def generate_from_wp_post(
    wp_client: Any,
    post_id: int,
    **kwargs,
) -> Dict[str, Any]:
    """
    Fetch post from WordPress REST API, then run generate_from_url on its
    content (rendered as HTML).  Overrides like override_title are forwarded.
    """
    try:
        post = wp_client.get_post(post_id)
    except Exception as exc:
        return {"error": f"Could not fetch post {post_id}: {exc}",
                "url": "", "title": "", "description": "", "schemas": [],
                "detected_types": [], "combined_json": "",
                "faq_pairs": [], "howto_steps": []}

    link = post.get("link", "")
    title_raw = post.get("title", {}).get("rendered", "")
    excerpt_raw = post.get("excerpt", {}).get("rendered", "")
    date_pub = post.get("date", "")
    date_mod = post.get("modified", "")

    # Author from _embedded if available
    author_name = ""
    embedded = post.get("_embedded", {})
    authors = embedded.get("author", [])
    if authors:
        author_name = authors[0].get("name", "")

    # Featured image
    featured_url = ""
    media = embedded.get("wp:featuredmedia", [])
    if media:
        featured_url = (media[0].get("source_url") or
                        media[0].get("media_details", {})
                        .get("sizes", {}).get("full", {}).get("source_url", ""))

    # Strip HTML from excerpt for description
    from bs4 import BeautifulSoup as BS
    desc_plain = BS(excerpt_raw, "html.parser").get_text(strip=True)

    # Build a stand-alone HTML page from post content and run analysis
    content_html = post.get("content", {}).get("rendered", "")
    full_html = (f"<html><head><title>{title_raw}</title></head>"
                 f"<body>{content_html}</body></html>")

    # Write to a temp-URL-style analysis by injecting into generate_from_url
    # via a data: URI approach isn't practical — instead analyse the soup directly
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(full_html, "html.parser")

    faq_pairs   = _extract_faq(soup)
    howto_steps = _extract_howto_steps(soup)

    # Merge kwargs overrides
    o_title  = kwargs.get("override_title", "")  or title_raw
    o_author = kwargs.get("override_author", "") or author_name
    o_desc   = kwargs.get("override_description", "") or desc_plain
    o_dpub   = kwargs.get("override_date_published", "") or date_pub
    o_dmod   = kwargs.get("override_date_modified", "")  or date_mod
    o_img    = kwargs.get("override_image_url", "") or featured_url

    schemas: List[Dict] = []
    detected: List[str] = []

    if kwargs.get("include_article", True):
        schemas.append(_build_article(o_title, link, o_author, o_dpub, o_dmod, o_img, o_desc))
        detected.append("Article")

    if kwargs.get("include_faq", True) and faq_pairs:
        schemas.append(_build_faq(faq_pairs))
        detected.append("FAQPage")

    if kwargs.get("include_howto", True) and howto_steps:
        schemas.append(_build_howto(o_title, o_desc, howto_steps))
        detected.append("HowTo")

    bci = kwargs.get("breadcrumb_items")
    if kwargs.get("include_breadcrumb", False) and bci:
        schemas.append(_build_breadcrumb(bci))
        detected.append("BreadcrumbList")

    if kwargs.get("include_local_business", False) and kwargs.get("business_name", ""):
        schemas.append(_build_local_business(
            kwargs["business_name"], link,
            kwargs.get("business_phone", ""),
            kwargs.get("business_address", ""),
            kwargs.get("business_type", "LocalBusiness"),
        ))
        detected.append("LocalBusiness")

    if len(schemas) > 1:
        combined_obj: Dict = {
            "@context": "https://schema.org",
            "@graph": [{k: v for k, v in s.items() if k != "@context"}
                       for s in schemas],
        }
    elif schemas:
        combined_obj = schemas[0]
    else:
        combined_obj = {}

    return {
        "url": link,
        "post_id": post_id,
        "title": o_title,
        "description": o_desc,
        "detected_types": detected,
        "schemas": schemas,
        "combined_json": json.dumps(combined_obj, indent=2, ensure_ascii=False),
        "faq_pairs": faq_pairs,
        "howto_steps": howto_steps,
        "error": None,
    }
