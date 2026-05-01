# app/wp/seo_audit.py
"""
On-page SEO + AEO (Answer Engine Optimization) audit engine.

SEO checks  — title, meta description, H1/headings, content length,
              keyword density, image alts, internal links, readability,
              canonical, structured data.

AEO checks  — direct-answer structure, FAQ content, question-based headings,
              paragraph conciseness, AEO schema, list/step content,
              entity & freshness signals.

No extra dependencies beyond requests + beautifulsoup4 (already in requirements).
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List
from urllib.parse import urlparse


# ──────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────────

def _syllables(word: str) -> int:
    word = word.lower().strip(".,!?;:-\"'()")
    if len(word) <= 3:
        return 1
    count = len(re.findall(r"[aeiou]+", word))
    if word.endswith("e"):
        count = max(1, count - 1)
    return max(1, count)


def _reading_ease(text: str) -> float:
    """Approximate Flesch Reading Ease (0–100; higher = easier)."""
    sentences = [s.strip() for s in re.split(r"[.!?]+", text) if s.strip()]
    words = re.findall(r"\b\w+\b", text)
    if not sentences or not words:
        return 50.0
    asl = len(words) / len(sentences)
    asw = sum(_syllables(w) for w in words) / len(words)
    return max(0.0, min(100.0, 206.835 - 1.015 * asl - 84.6 * asw))


def _word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))


def _kw_density(text: str, keyword: str) -> float:
    if not keyword:
        return 0.0
    words = re.findall(r"\b\w+\b", text.lower())
    if not words:
        return 0.0
    kw_words = len(keyword.lower().split())
    hits = len(re.findall(re.escape(keyword.lower()), text.lower()))
    return (hits * kw_words) / len(words) * 100


def _check(label: str, status: str, score: int, max_score: int,
           detail: str, fix: str = "") -> Dict:
    return {
        "label": label,
        "status": status,      # "pass" | "warn" | "fail"
        "score": score,
        "max_score": max_score,
        "detail": detail,
        "fix": fix,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Public entry-point
# ──────────────────────────────────────────────────────────────────────────────

def audit_url(url: str, target_keyword: str = "") -> Dict[str, Any]:
    """
    Fetch *url* and run the full SEO + AEO audit.

    Returns:
        {
          url, target_keyword,
          seo_score (0-100), aeo_score (0-100),
          seo_checks, aeo_checks,   # list of check dicts
          priority_fixes,           # top 6 failing/warning fixes
          error                     # None on success
        }
    """
    import requests
    from bs4 import BeautifulSoup

    result: Dict[str, Any] = {
        "url": url,
        "target_keyword": target_keyword.strip(),
        "seo_score": 0,
        "aeo_score": 0,
        "seo_checks": [],
        "aeo_checks": [],
        "priority_fixes": [],
        "error": None,
    }

    # ── fetch ──────────────────────────────────────────────────────────────────
    try:
        resp = requests.get(
            url,
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0 (compatible; SEOAuditBot/1.0)",
                     "Accept": "text/html"},
            allow_redirects=True,
        )
        resp.raise_for_status()
        html, final_url = resp.text, resp.url
    except Exception as exc:
        result["error"] = f"Could not fetch URL: {exc}"
        return result

    soup = BeautifulSoup(html, "html.parser")
    kw = target_keyword.strip().lower()
    domain = urlparse(final_url).netloc

    # ── extract elements ───────────────────────────────────────────────────────
    title_tag   = soup.find("title")
    title_text  = title_tag.get_text(strip=True) if title_tag else ""

    meta_el     = soup.find("meta", attrs={"name": re.compile(r"description", re.I)})
    meta_text   = (meta_el.get("content", "") if meta_el else "").strip()

    canonical   = soup.find("link", attrs={"rel": "canonical"})
    canon_href  = (canonical.get("href", "") if canonical else "").strip()

    h1s = soup.find_all("h1")
    h2s = soup.find_all("h2")
    h3s = soup.find_all("h3")

    # Strip nav/footer/aside before extracting body text
    for tag in soup.find_all(["nav", "footer", "aside", "script", "style"]):
        tag.decompose()

    body_text  = soup.get_text(separator=" ", strip=True)
    body_lower = body_text.lower()
    paragraphs = soup.find_all("p")
    imgs       = soup.find_all("img")
    all_links  = soup.find_all("a", href=True)
    internal_links = [
        a for a in all_links
        if domain in a["href"]
        or (a["href"].startswith("/") and not a["href"].startswith("//"))
    ]
    lists = soup.find_all(["ul", "ol"])

    # JSON-LD schema types
    schema_types: List[str] = []
    for s in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            obj = json.loads(s.string or "")
            t = obj.get("@type") or ""
            schema_types.extend(t if isinstance(t, list) else [t])
        except Exception:
            pass

    # ══════════════════════════════════════════════════════════════════════════
    # SEO CHECKS  (max ≈ 85 pts, normalised to 0-100)
    # ══════════════════════════════════════════════════════════════════════════
    seo: List[Dict] = []

    # 1. Title tag ──────────────────────────────────────────────────── 15 pts
    tlen = len(title_text)
    if not title_text:
        c = _check("Title Tag", "fail", 0, 15, "No <title> tag found.",
                   "Add a title tag with 50–60 characters that includes your target keyword.")
    elif tlen < 30:
        c = _check("Title Tag", "warn", 6, 15,
                   f"Title too short ({tlen} chars): \"{title_text}\"",
                   "Expand the title to 50–60 characters.")
    elif tlen > 65:
        c = _check("Title Tag", "warn", 8, 15,
                   f"Title may be truncated in SERPs ({tlen} chars): \"{title_text}\"",
                   "Shorten to under 60 characters.")
    else:
        kw_hit = kw and kw in title_text.lower()
        score  = 15 if (not kw or kw_hit) else 12
        c = _check("Title Tag", "pass", score, 15,
                   f"{tlen} chars: \"{title_text}\"" + (" ✓ keyword present" if kw_hit else ""),
                   f"Add '{target_keyword}' to the title." if score < 15 else "")
    seo.append(c)

    # 2. Meta description ──────────────────────────────────────────── 10 pts
    mlen = len(meta_text)
    if not meta_text:
        c = _check("Meta Description", "fail", 0, 10, "No meta description found.",
                   "Add a meta description of 150–160 characters with a call-to-action and keyword.")
    elif mlen < 100:
        c = _check("Meta Description", "warn", 4, 10,
                   f"Too short ({mlen} chars).",
                   "Expand to 150–160 characters with a clear CTA.")
    elif mlen > 165:
        c = _check("Meta Description", "warn", 6, 10,
                   f"May be truncated ({mlen} chars).",
                   "Shorten to under 160 characters.")
    else:
        kw_hit = kw and kw in meta_text.lower()
        score  = 10 if (not kw or kw_hit) else 8
        c = _check("Meta Description", "pass", score, 10,
                   f"{mlen} chars" + (" ✓ keyword present" if kw_hit else ""),
                   f"Include '{target_keyword}' in the meta description." if score < 10 else "")
    seo.append(c)

    # 3. H1 structure ─────────────────────────────────────────────── 10 pts
    h1_count = len(h1s)
    h1_text  = h1s[0].get_text(strip=True) if h1s else ""
    if h1_count == 0:
        c = _check("H1 Heading", "fail", 0, 10, "No H1 heading found.",
                   "Add a single H1 that includes your target keyword.")
    elif h1_count > 1:
        c = _check("H1 Heading", "warn", 5, 10,
                   f"{h1_count} H1 tags found — only one is recommended.",
                   "Remove duplicate H1s; keep the one containing your primary keyword.")
    else:
        kw_hit = kw and kw in h1_text.lower()
        score  = 10 if (not kw or kw_hit) else 7
        c = _check("H1 Heading", "pass", score, 10,
                   f"\"{h1_text[:80]}\"" + (" ✓ keyword present" if kw_hit else ""),
                   f"Include '{target_keyword}' in your H1." if score < 10 else "")
    seo.append(c)

    # 4. Heading hierarchy ────────────────────────────────────────────  5 pts
    if h2s:
        c = _check("Heading Structure", "pass", 5, 5,
                   f"{len(h2s)} H2s, {len(h3s)} H3s — good content hierarchy.", "")
    else:
        c = _check("Heading Structure", "warn", 2, 5,
                   "No H2 subheadings found.",
                   "Break content into sections with H2/H3 subheadings.")
    seo.append(c)

    # 5. Content length ───────────────────────────────────────────── 10 pts
    wc = _word_count(body_text)
    if wc < 300:
        c = _check("Content Length", "fail", 0, 10,
                   f"Very thin content ({wc} words) — most pages need 800+ to rank.",
                   "Expand to at least 800 words with helpful how-to content, FAQs, and examples.")
    elif wc < 600:
        c = _check("Content Length", "warn", 5, 10,
                   f"Short content ({wc} words) — aim for 800+.",
                   "Add how-to sections, FAQs, or case studies to reach 800+ words.")
    elif wc < 1000:
        c = _check("Content Length", "pass", 8, 10,
                   f"{wc} words — adequate depth.",
                   "Consider expanding to 1,000+ words for competitive topics.")
    else:
        c = _check("Content Length", "pass", 10, 10,
                   f"{wc} words — strong content depth.", "")
    seo.append(c)

    # 6. Keyword density ──────────────────────────────────────────────  5 pts
    if not kw:
        c = _check("Keyword Density", "pass", 5, 5,
                   "Enter a target keyword above for density analysis.", "")
    else:
        density = _kw_density(body_text, kw)
        if density < 0.5:
            c = _check("Keyword Density", "warn", 2, 5,
                       f"Density {density:.1f}% — too low.",
                       f"Mention '{target_keyword}' more naturally (aim for 1–3%).")
        elif density > 3.5:
            c = _check("Keyword Density", "warn", 2, 5,
                       f"Density {density:.1f}% — possible over-optimisation.",
                       "Use synonyms and related terms to vary the language.")
        else:
            c = _check("Keyword Density", "pass", 5, 5,
                       f"Density {density:.1f}% — optimal range.", "")
    seo.append(c)

    # 7. Image alt text ───────────────────────────────────────────────  5 pts
    missing_alts = [i for i in imgs if not i.get("alt", "").strip()]
    if not imgs:
        c = _check("Image Alt Text", "pass", 5, 5, "No images on page.", "")
    elif not missing_alts:
        c = _check("Image Alt Text", "pass", 5, 5,
                   f"All {len(imgs)} images have alt text.", "")
    else:
        pct = len(missing_alts) / len(imgs) * 100
        if pct > 50:
            c = _check("Image Alt Text", "fail", 0, 5,
                       f"{len(missing_alts)}/{len(imgs)} images missing alt text.",
                       "Add descriptive alt text to all images; include keyword where natural.")
        else:
            c = _check("Image Alt Text", "warn", 3, 5,
                       f"{len(missing_alts)}/{len(imgs)} images missing alt text.",
                       "Add alt text to remaining images.")
    seo.append(c)

    # 8. Internal links ───────────────────────────────────────────────  5 pts
    il = len(internal_links)
    if il < 2:
        c = _check("Internal Links", "warn", 2, 5,
                   f"Only {il} internal link(s).",
                   "Add 3–5 internal links to related pages to distribute link equity.")
    elif il < 5:
        c = _check("Internal Links", "pass", 4, 5,
                   f"{il} internal links.", "")
    else:
        c = _check("Internal Links", "pass", 5, 5,
                   f"{il} internal links — solid link structure.", "")
    seo.append(c)

    # 9. Readability ──────────────────────────────────────────────────  5 pts
    ease = _reading_ease(body_text)
    if ease >= 60:
        c = _check("Readability", "pass", 5, 5,
                   f"Flesch score {ease:.0f}/100 — easy to read.", "")
    elif ease >= 40:
        c = _check("Readability", "warn", 3, 5,
                   f"Flesch score {ease:.0f}/100 — moderately difficult.",
                   "Shorten sentences and use simpler words. Aim for grade-8 reading level.")
    else:
        c = _check("Readability", "warn", 1, 5,
                   f"Flesch score {ease:.0f}/100 — hard to read.",
                   "Significantly simplify language. Break long sentences into two.")
    seo.append(c)

    # 10. Canonical tag ────────────────────────────────────────────────  5 pts
    if not canon_href:
        c = _check("Canonical Tag", "warn", 2, 5,
                   "No canonical tag.",
                   "Add <link rel='canonical' href='[this-url]'> to prevent duplicate-content issues.")
    elif canon_href in (final_url, url):
        c = _check("Canonical Tag", "pass", 5, 5,
                   f"Self-referencing canonical present.", "")
    else:
        c = _check("Canonical Tag", "warn", 3, 5,
                   f"Canonical → {canon_href[:70]}",
                   "Verify this canonical redirect is intentional.")
    seo.append(c)

    # 11. Structured data ─────────────────────────────────────────────  5 pts
    if schema_types:
        c = _check("Structured Data", "pass", 5, 5,
                   f"Schema found: {', '.join(schema_types[:4])}", "")
    else:
        c = _check("Structured Data", "fail", 0, 5,
                   "No JSON-LD structured data found.",
                   "Add Article, FAQPage, or LocalBusiness schema to improve rich-results eligibility.")
    seo.append(c)

    seo_total = sum(c["score"] for c in seo)
    seo_max   = sum(c["max_score"] for c in seo)
    seo_score = round(seo_total / seo_max * 100) if seo_max else 0

    # ══════════════════════════════════════════════════════════════════════════
    # AEO CHECKS  (Answer Engine Optimisation — max 100 pts)
    # Targets: Google AI Overviews, ChatGPT, Perplexity, featured snippets
    # ══════════════════════════════════════════════════════════════════════════
    aeo: List[Dict] = []

    # A1. Direct-answer structure ─────────────────────────────────── 20 pts
    # A clear, concise answer or definition in the first ~120 words
    first_paras = [p.get_text(strip=True) for p in paragraphs[:3]]
    intro_text  = " ".join(first_paras)
    intro_wc    = _word_count(intro_text)
    has_def     = bool(re.search(
        r"\b(is|are|means|refers to|defined as|can be described)\b",
        intro_text, re.I))
    short_intro = 20 < intro_wc < 130

    if has_def and short_intro:
        c = _check("Direct Answer Structure", "pass", 20, 20,
                   "Page opens with a concise definition or direct answer — ideal for AI overviews.", "")
    elif has_def or short_intro:
        c = _check("Direct Answer Structure", "warn", 12, 20,
                   "Partial direct-answer structure detected.",
                   "Open with a 40–80 word paragraph that directly answers the main query. "
                   "Start: '[Topic] is…' or 'To [do X], you need to…'")
    else:
        c = _check("Direct Answer Structure", "fail", 0, 20,
                   "No direct answer or definition near the top of the page.",
                   "Add a clear 40–80 word answer in the first paragraph. "
                   "AI engines extract this for featured snippets and overviews.")
    aeo.append(c)

    # A2. FAQ content ─────────────────────────────────────────────── 20 pts
    faq_schema      = any("FAQ" in t or "QAPage" in t for t in schema_types)
    q_headings_list = [h.get_text(strip=True)
                       for h in (h2s + h3s) if "?" in h.get_text()]
    n_qh = len(q_headings_list)

    if faq_schema and n_qh >= 3:
        c = _check("FAQ Content", "pass", 20, 20,
                   f"FAQPage schema + {n_qh} question headings — excellent for People Also Ask.", "")
    elif faq_schema or n_qh >= 3:
        detail = "FAQPage schema present." if faq_schema else f"{n_qh} question headings found."
        fix    = ("Add question-style H2/H3s to complement the schema."
                  if faq_schema else "Add FAQPage JSON-LD schema to the question headings.")
        c = _check("FAQ Content", "pass", 14, 20, detail, fix)
    elif n_qh >= 1:
        c = _check("FAQ Content", "warn", 8, 20,
                   f"{n_qh} question heading(s) — limited FAQ structure.",
                   "Add a dedicated FAQ section with 3–5 question H2s plus FAQPage schema.")
    else:
        c = _check("FAQ Content", "fail", 0, 20,
                   "No FAQ content or question-style headings found.",
                   "Add a FAQ section — this is the highest-impact AEO improvement available.")
    aeo.append(c)

    # A3. Question-based headings ─────────────────────────────────── 15 pts
    all_htext = [h.get_text(strip=True) for h in (h2s + h3s)]
    q_pattern = re.compile(
        r"^(what|how|why|when|where|who|which|can|do|does|is|are|should|will)\b",
        re.I)
    q_heads = [h for h in all_htext if h.endswith("?") or q_pattern.match(h)]
    q_ratio = len(q_heads) / len(all_htext) if all_htext else 0

    if len(q_heads) >= 3 and q_ratio >= 0.4:
        c = _check("Question-Based Headings", "pass", 15, 15,
                   f"{len(q_heads)}/{len(all_htext)} headings are question-style — strong AEO signal.", "")
    elif len(q_heads) >= 2:
        c = _check("Question-Based Headings", "pass", 10, 15,
                   f"{len(q_heads)} question-style headings.",
                   "Convert more H2/H3s to questions that match user search intent.")
    elif len(q_heads) == 1:
        c = _check("Question-Based Headings", "warn", 5, 15,
                   "Only 1 question-style heading.",
                   "Reformulate section headings as natural questions (e.g. 'How does X work?').")
    else:
        c = _check("Question-Based Headings", "fail", 0, 15,
                   "No question-style headings found.",
                   "Rewrite H2/H3 headings as questions. AI engines match these to conversational queries.")
    aeo.append(c)

    # A4. Paragraph conciseness ───────────────────────────────────── 10 pts
    # AI engines extract short, self-contained paragraphs best
    para_texts  = [p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True)]
    if para_texts:
        avg_pw    = sum(_word_count(p) for p in para_texts) / len(para_texts)
        long_p    = [p for p in para_texts if _word_count(p) > 80]
        if avg_pw <= 50 and not long_p:
            c = _check("Paragraph Conciseness", "pass", 10, 10,
                       f"Avg paragraph {avg_pw:.0f} words — concise and AI-extractable.", "")
        elif avg_pw <= 70:
            c = _check("Paragraph Conciseness", "pass", 7, 10,
                       f"Avg paragraph {avg_pw:.0f} words — mostly concise.",
                       f"{len(long_p)} paragraph(s) over 80 words. Break these up.")
        else:
            c = _check("Paragraph Conciseness", "warn", 4, 10,
                       f"Avg paragraph {avg_pw:.0f} words — too long for AI extraction.",
                       "Break paragraphs into 2–4 sentence chunks (40–60 words). "
                       "AI engines prefer short, self-contained answers.")
    else:
        c = _check("Paragraph Conciseness", "warn", 5, 10,
                   "No paragraph elements detected.", "")
    aeo.append(c)

    # A5. AEO-relevant schema ─────────────────────────────────────── 15 pts
    aeo_schema_set   = {"FAQPage", "QAPage", "HowTo", "Article",
                        "NewsArticle", "BlogPosting"}
    found_aeo_schema = set(schema_types) & aeo_schema_set
    if len(found_aeo_schema) >= 2:
        c = _check("AEO Schema Markup", "pass", 15, 15,
                   f"Multiple AEO schemas: {', '.join(found_aeo_schema)} — "
                   "eligible for multiple rich-result types.", "")
    elif found_aeo_schema:
        c = _check("AEO Schema Markup", "pass", 10, 15,
                   f"AEO schema: {', '.join(found_aeo_schema)}.",
                   "Add FAQPage + Article schema together to maximise rich-result eligibility.")
    else:
        c = _check("AEO Schema Markup", "fail", 0, 15,
                   "No AEO-relevant structured data found.",
                   "Add FAQPage or HowTo JSON-LD. These directly feed Google AI Overviews "
                   "and Perplexity citations.")
    aeo.append(c)

    # A6. List & step content ─────────────────────────────────────── 10 pts
    list_items  = sum(len(lst.find_all("li")) for lst in lists)
    has_ordered = bool(soup.find_all("ol"))
    if list_items >= 10 and has_ordered:
        c = _check("List & Step Content", "pass", 10, 10,
                   f"{list_items} list items incl. numbered steps — highly extractable by AI.", "")
    elif list_items >= 5:
        c = _check("List & Step Content", "pass", 7, 10,
                   f"{list_items} list items.",
                   "Add numbered step lists for process content — frequently cited in AI answers.")
    elif list_items >= 1:
        c = _check("List & Step Content", "warn", 4, 10,
                   f"Only {list_items} list item(s).",
                   "Convert key information into bullet points and numbered steps.")
    else:
        c = _check("List & Step Content", "fail", 0, 10,
                   "No list content found.",
                   "Add bullet lists for features/benefits and <ol> numbered steps for processes. "
                   "Lists are among the most-cited content in AI answers.")
    aeo.append(c)

    # A7. Entity clarity & freshness ──────────────────────────────── 10 pts
    first_100 = " ".join(body_text.split()[:100]).lower()
    kw_in_intro = kw and kw in first_100
    has_date    = bool(
        soup.find("time") or
        re.search(
            r"\b(january|february|march|april|may|june|july|august|"
            r"september|october|november|december|\d{4})\b",
            body_lower[:600]))

    if kw_in_intro and has_date:
        c = _check("Entity & Freshness Signals", "pass", 10, 10,
                   "Keyword in intro + date/freshness signal — strong entity clarity.", "")
    elif kw_in_intro or has_date:
        msgs = []
        if not kw_in_intro and kw:
            msgs.append(f"'{target_keyword}' not in first 100 words")
        if not has_date:
            msgs.append("no visible date signal")
        c = _check("Entity & Freshness Signals", "warn", 6, 10,
                   "Partial: " + "; ".join(msgs) + ".",
                   "Mention the topic in the first sentence. Add a visible published/updated date.")
    elif not kw:
        c = _check("Entity & Freshness Signals", "warn", 6, 10,
                   "Enter a keyword above for entity-clarity analysis." +
                   (" Date signal found." if has_date else " No date signal found."), "")
    else:
        c = _check("Entity & Freshness Signals", "fail", 0, 10,
                   f"'{target_keyword}' not in intro and no date signals.",
                   f"Mention '{target_keyword}' in the first sentence. "
                   "Add a last-updated date — freshness is a key trust signal for AI engines.")
    aeo.append(c)

    aeo_total = sum(c["score"] for c in aeo)
    aeo_max   = sum(c["max_score"] for c in aeo)
    aeo_score = round(aeo_total / aeo_max * 100) if aeo_max else 0

    # ── priority fixes ─────────────────────────────────────────────────────────
    all_checks = seo + aeo
    fails = [c for c in all_checks if c["status"] == "fail" and c["fix"]]
    warns = [c for c in all_checks if c["status"] == "warn" and c["fix"]]
    priority_fixes = (fails + warns)[:6]

    result.update({
        "seo_score":    seo_score,
        "aeo_score":    aeo_score,
        "seo_checks":   seo,
        "aeo_checks":   aeo,
        "priority_fixes": priority_fixes,
    })
    return result
