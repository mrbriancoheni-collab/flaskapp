# app/services/google_ads_health_score.py
"""
Google Ads account health score — computed from locally-synced data.

Uses the SAME 10 dimensions, weights, formulas, and grade scale as the Google
Ads Health Grader (app/ads_grader/analyzer.py) so scores are consistent whether
a user looks at the grader report or the paid-account dashboard.

When live API data is available, the grader produces richer signals (search_term_view
via API, RSA ad_strength, campaign_criterion device modifiers). This service reads
from locally-synced DB tables and notes where it falls back to a proxy or neutral
default.
"""
from __future__ import annotations

from datetime import date, timedelta

# ── Shared constants (mirror analyzer.py / google_ads_client.py) ─────────────

NEGATIVE_KW_BENCHMARK = 135  # same as analyzer.py BENCHMARKS["negative_keywords_avg"]
LONG_TAIL_TARGET       = 0.50  # same as analyzer.py BENCHMARKS["long_tail_target"]
QS_TARGET              = 7.0   # same as analyzer.py BENCHMARKS["quality_score_target"]

# Exact same list as GoogleAdsGraderClient._get_search_terms() in google_ads_client.py
WASTE_PATTERNS = [
    # DIY / informational intent
    "how to ", "how do i ", "how do you ", "diy ", "do it yourself",
    "tutorial", "guide", "tips", "step by step", "can i ",
    "should i ", "what is ", "what are ", "why is ", "why does ",
    "definition", "wikipedia", "reddit", "youtube", "forum", "video",
    # Job seekers / employment
    " job", " jobs", "career", "careers", " hiring", "salary",
    "wage", "apprentice", "journeyman", "technician school",
    "electrician school", "hvac school", "plumbing school",
    "how to become", "get certified", "certification exam",
    # Supply / wholesale
    "wholesale", "supply house", "distributor", "buy parts",
    " parts", "equipment for sale", "amazon", "home depot parts",
    "lowes parts", "menards",
    # Clearly informational
    "history of", "types of", "different types",
]

# Identical weight map to analyzer.py _calculate_overall_score()
DIMENSION_WEIGHTS = {
    "wasted_spend":         0.25,
    "quality_score":        0.15,
    "landing_pages":        0.10,
    "ctr_optimization":     0.12,
    "text_ad_optimization": 0.10,
    "account_activity":     0.10,
    "long_tail_keywords":   0.08,
    "impression_share":     0.05,
    "mobile_advertising":   0.05,
    "expanded_text_ads":    0.00,
}


def _grade(score: float) -> str:
    """Identical grade scale to analyzer.py _calculate_grade()."""
    if score >= 90: return "A+"
    if score >= 85: return "A"
    if score >= 80: return "A-"
    if score >= 75: return "B+"
    if score >= 70: return "B"
    if score >= 65: return "B-"
    if score >= 60: return "C+"
    if score >= 55: return "C"
    if score >= 50: return "C-"
    if score >= 45: return "D+"
    if score >= 40: return "D"
    return "F"


def _color(score: float) -> str:
    if score >= 75: return "green"
    if score >= 50: return "yellow"
    return "red"


def compute_health_score(account_id: int, aid_goals=None) -> dict:
    """
    Compute the 10-dimension health score from locally-synced data.

    Returns dict with keys: overall, grade, dimensions, top_issues,
    has_eta, and optionally goal_performance.
    """
    from app import db
    from sqlalchemy import text

    today     = date.today()
    ninety_ago = today - timedelta(days=90)

    # ── DB helpers ────────────────────────────────────────────────────────────

    def _scalar(sql, params=None):
        try:
            v = db.session.execute(text(sql), params or {}).scalar()
            return v if v is not None else 0
        except Exception:
            try: db.session.rollback()
            except Exception: pass
            return 0

    def _rows(sql, params=None):
        try:
            return db.session.execute(text(sql), params or {}).mappings().all()
        except Exception:
            try: db.session.rollback()
            except Exception: pass
            return []

    def _one(sql, params=None):
        try:
            return db.session.execute(text(sql), params or {}).mappings().one_or_none()
        except Exception:
            try: db.session.rollback()
            except Exception: pass
            return None

    # ─────────────────────────────────────────────────────────────────────────
    # 1. WASTED SPEND  (25%)
    # Primary: search_terms table — apply WASTE_PATTERNS, compute waste_pct
    # Fallback: neg_kw count vs 135 benchmark → estimated 5–25% waste
    # Formula: score = max(0, 100 − waste_pct × 2.5)   ← identical to grader
    # ─────────────────────────────────────────────────────────────────────────
    waste_pct          = 20.0   # pessimistic default
    wasted_spend_score = 50.0
    waste_detail       = "No search term data synced yet."

    try:
        st_rows = _rows(
            """SELECT st.search_term, st.cost_micros
               FROM search_terms st
               JOIN ads_campaigns ac ON ac.id = st.campaign_id
               WHERE ac.account_id = :aid AND st.date >= :d""",
            {"aid": account_id, "d": ninety_ago},
        )

        if st_rows:
            total_spend = sum(r["cost_micros"] / 1_000_000 for r in st_rows)
            waste_spend = 0.0
            waste_count = 0
            for r in st_rows:
                if any(p in (r["search_term"] or "").lower() for p in WASTE_PATTERNS):
                    waste_spend += r["cost_micros"] / 1_000_000
                    waste_count += 1

            waste_pct = (waste_spend / total_spend * 100) if total_spend > 0 else 0.0
            wasted_spend_score = max(0.0, 100.0 - waste_pct * 2.5)

            if waste_count == 0:
                waste_detail = "No irrelevant search terms found in the last 90 days — solid negative keyword coverage."
            elif waste_pct < 10:
                waste_detail = (
                    f"{waste_count} waste search term(s) costing {waste_pct:.1f}% of budget. "
                    "Adding them as negatives will reclaim that spend immediately."
                )
            else:
                waste_detail = (
                    f"{waste_count} irrelevant search terms are consuming {waste_pct:.1f}% of your budget. "
                    "Block these as negative keywords now."
                )
        else:
            # Fallback: negative keyword coverage ratio (same formula as grader)
            neg_count = _scalar(
                """SELECT COUNT(*) FROM negative_keywords nk
                   LEFT JOIN ads_campaigns ac ON ac.id = nk.campaign_id
                   WHERE ac.account_id = :aid""",
                {"aid": account_id},
            )
            coverage  = min(1.0, neg_count / NEGATIVE_KW_BENCHMARK)
            waste_pct = 25 * (1 - coverage) + 5   # 0% cov → 25% waste, 100% cov → 5%
            wasted_spend_score = max(0.0, 100.0 - waste_pct * 2.5)
            waste_detail = (
                f"Estimated {waste_pct:.0f}% waste from {neg_count} negative keywords vs "
                f"{NEGATIVE_KW_BENCHMARK} benchmark. Run the Grader for a live search-term scan."
            )
    except Exception:
        pass

    # ─────────────────────────────────────────────────────────────────────────
    # 2. QUALITY SCORE  (15%)
    # AVG(quality_score) from gads_stats_daily keyword rows
    # Formula: score = avg_qs / 10 × 100   ← identical to grader
    # ─────────────────────────────────────────────────────────────────────────
    quality_score_score = 50.0
    qs_detail           = "No quality score data synced yet."

    try:
        qs_row = _one(
            """SELECT AVG(gs.quality_score) AS avg_qs,
                      SUM(CASE WHEN gs.quality_score < 5 THEN 1 ELSE 0 END) AS low_count
               FROM gads_stats_daily gs
               JOIN keywords k       ON k.id  = gs.entity_id
               JOIN ad_groups ag     ON ag.id  = k.ad_group_id
               JOIN ads_campaigns ac ON ac.id  = ag.campaign_id
               WHERE gs.entity_type = 'keyword' AND ac.account_id = :aid
                 AND gs.date >= :d AND gs.quality_score IS NOT NULL""",
            {"aid": account_id, "d": ninety_ago},
        )
        if qs_row and qs_row["avg_qs"] is not None:
            avg_qs    = float(qs_row["avg_qs"])
            low_count = int(qs_row["low_count"] or 0)
            quality_score_score = min(100.0, (avg_qs / 10.0) * 100.0)
            if avg_qs >= QS_TARGET:
                qs_detail = f"Average QS {avg_qs:.1f}/10 — above the 7.0 target, lowering your cost per click."
            elif avg_qs >= 5:
                qs_detail = (
                    f"Average QS {avg_qs:.1f}/10 — below the 7.0 target. "
                    f"{low_count} keyword(s) score below 5. Rewrite ads to match keyword intent."
                )
            else:
                qs_detail = (
                    f"Average QS {avg_qs:.1f}/10 — well below target. "
                    "Poor relevance is significantly raising your CPC."
                )
    except Exception:
        pass

    # ─────────────────────────────────────────────────────────────────────────
    # 3. CTR OPTIMIZATION  (12%)
    # Overall CTR from campaign stats (last 90 days)
    # Step function identical to grader _score_ctr_optimization()
    # ─────────────────────────────────────────────────────────────────────────
    ctr_val   = 0.0
    ctr_score = 50.0
    ctr_detail = "No click data for the last 90 days."

    try:
        ctr_row = _one(
            """SELECT SUM(gs.clicks) AS clicks, SUM(gs.impressions) AS impressions
               FROM gads_stats_daily gs
               JOIN ads_campaigns ac ON ac.id = gs.entity_id AND ac.account_id = :aid
               WHERE gs.entity_type = 'campaign' AND gs.date >= :d""",
            {"aid": account_id, "d": ninety_ago},
        )
        if ctr_row and (ctr_row["impressions"] or 0) > 0:
            ctr_val = (ctr_row["clicks"] or 0) / ctr_row["impressions"] * 100
            if   ctr_val >= 5.0: ctr_score = 100.0
            elif ctr_val >= 3.0: ctr_score = 70.0
            elif ctr_val >= 2.0: ctr_score = 50.0
            elif ctr_val >= 1.0: ctr_score = 30.0
            else:                ctr_score = 10.0

            if ctr_val >= 5:
                ctr_detail = f"CTR {ctr_val:.1f}% is above average — compelling ads earning strong clicks."
            elif ctr_val >= 3:
                ctr_detail = f"CTR {ctr_val:.1f}% is decent. Testing new headlines could push it higher."
            else:
                ctr_detail = (
                    f"CTR {ctr_val:.1f}% is low. Rewriting headlines to be more specific "
                    "increases clicks without spending more."
                )
    except Exception:
        pass

    # ─────────────────────────────────────────────────────────────────────────
    # 4. LANDING PAGE EXPERIENCE  (10%)
    # landing_page_exp distribution from gads_stats_daily keyword rows
    # Weights: ABOVE_AVG=100, AVG=65, BELOW_AVG=20, unknown=50  ← identical to grader
    # ─────────────────────────────────────────────────────────────────────────
    landing_score  = 50.0
    landing_detail = "No landing page experience data synced yet."

    try:
        lp_rows = _rows(
            """SELECT gs.landing_page_exp, COUNT(*) AS cnt
               FROM gads_stats_daily gs
               JOIN keywords k       ON k.id  = gs.entity_id
               JOIN ad_groups ag     ON ag.id  = k.ad_group_id
               JOIN ads_campaigns ac ON ac.id  = ag.campaign_id
               WHERE gs.entity_type = 'keyword' AND ac.account_id = :aid
                 AND gs.date >= :d AND gs.landing_page_exp IS NOT NULL
               GROUP BY gs.landing_page_exp""",
            {"aid": account_id, "d": ninety_ago},
        )
        if lp_rows:
            dist    = {r["landing_page_exp"]: int(r["cnt"]) for r in lp_rows}
            total   = sum(dist.values())
            above   = dist.get("ABOVE_AVERAGE", 0)
            avg_lp  = dist.get("AVERAGE", 0)
            below   = dist.get("BELOW_AVERAGE", 0)
            unknown = total - above - avg_lp - below

            landing_score = (above * 100 + avg_lp * 65 + below * 20 + unknown * 50) / total

            below_pct = round(below / total * 100)
            above_pct = round(above / total * 100)
            if below_pct > 30:
                landing_detail = (
                    f"{below_pct}% of keywords have Below Average landing page experience — "
                    "pages don't match what people searched for, raising your CPC."
                )
            elif above_pct > 50:
                landing_detail = f"{above_pct}% of keywords have Above Average landing page experience — strong alignment."
            else:
                landing_detail = "Landing page experience is mixed. Aligning page content to keyword intent will lower your cost per lead."
    except Exception:
        pass

    # ─────────────────────────────────────────────────────────────────────────
    # 5. TEXT AD OPTIMIZATION  (10%)
    # Grader uses RSA ad_strength (not stored in DB).
    # Best available proxy: ad_relevance QS component (ABOVE/AVERAGE/BELOW) —
    # it directly measures whether ad copy matches the keyword, same intent.
    # Same 60/40 split: relevance score × 60% + CTR component × 40%
    # ─────────────────────────────────────────────────────────────────────────
    text_ad_score  = 50.0
    text_ad_detail = "No ad relevance data synced yet."

    try:
        rel_rows = _rows(
            """SELECT gs.ad_relevance, COUNT(*) AS cnt
               FROM gads_stats_daily gs
               JOIN keywords k       ON k.id  = gs.entity_id
               JOIN ad_groups ag     ON ag.id  = k.ad_group_id
               JOIN ads_campaigns ac ON ac.id  = ag.campaign_id
               WHERE gs.entity_type = 'keyword' AND ac.account_id = :aid
                 AND gs.date >= :d AND gs.ad_relevance IS NOT NULL
               GROUP BY gs.ad_relevance""",
            {"aid": account_id, "d": ninety_ago},
        )
        if rel_rows:
            dist      = {r["ad_relevance"]: int(r["cnt"]) for r in rel_rows}
            total     = sum(dist.values())
            above     = dist.get("ABOVE_AVERAGE", 0)
            avg_rel   = dist.get("AVERAGE", 0)
            below_rel = dist.get("BELOW_AVERAGE", 0)
            unknown   = total - above - avg_rel - below_rel

            # Map ad_relevance → same weights as grader RSA strength buckets
            relevance_score = (above * 100 + avg_rel * 65 + below_rel * 20 + unknown * 50) / total
            # CTR component: min(100, ctr / 4%) × 100  ← same as grader
            ctr_component   = min(100.0, (ctr_val / 4.0) * 100.0)
            text_ad_score   = round(relevance_score * 0.60 + ctr_component * 0.40, 1)

            below_pct = round(below_rel / total * 100)
            above_pct = round(above / total * 100)
            if below_pct > 30:
                text_ad_detail = (
                    f"{below_pct}% of ads are Below Average for relevance — rewrite to match keyword themes more closely. "
                    "Run the Grader for RSA ad strength details."
                )
            elif above_pct > 50:
                text_ad_detail = f"{above_pct}% of ads are Above Average for ad relevance — strong keyword/ad alignment."
            else:
                text_ad_detail = "Ad relevance is mixed. Tighter, more specific ad copy will improve this score."
        else:
            # Fall back to CTR-only signal
            ctr_component  = min(100.0, (ctr_val / 4.0) * 100.0)
            text_ad_score  = round(50.0 * 0.60 + ctr_component * 0.40, 1)
            text_ad_detail = "Ad relevance data not synced — run the Grader for RSA ad strength analysis."
    except Exception:
        pass

    # ─────────────────────────────────────────────────────────────────────────
    # 6. ACCOUNT ACTIVITY  (10%)
    # Points-based: ads/group + kw/group + conversion tracking + active mgmt
    # Identical signal + point values to grader _score_account_activity()
    # ─────────────────────────────────────────────────────────────────────────
    account_activity_score = 0.0
    activity_detail        = "No account structure data available."

    try:
        ag_count = _scalar(
            """SELECT COUNT(*) FROM ad_groups ag
               JOIN ads_campaigns ac ON ac.id = ag.campaign_id
               WHERE ac.account_id = :aid AND ag.status != 'removed'""",
            {"aid": account_id},
        )
        ad_count = _scalar(
            """SELECT COUNT(*) FROM ads a
               JOIN ad_groups ag     ON ag.id = a.ad_group_id
               JOIN ads_campaigns ac ON ac.id = ag.campaign_id
               WHERE ac.account_id = :aid AND a.status != 'removed'""",
            {"aid": account_id},
        )
        kw_count = _scalar(
            """SELECT COUNT(*) FROM keywords k
               JOIN ad_groups ag     ON ag.id = k.ad_group_id
               JOIN ads_campaigns ac ON ac.id = ag.campaign_id
               WHERE ac.account_id = :aid AND k.status != 'removed'""",
            {"aid": account_id},
        )

        pts          = 0
        detail_parts = []
        avg_ads = (ad_count / ag_count) if ag_count > 0 else 0
        avg_kw  = (kw_count / ag_count) if ag_count > 0 else 0

        # Ads per group  (35 pts max)
        if   avg_ads >= 3: pts += 35
        elif avg_ads >= 2:
            pts += 22
            detail_parts.append(f"{avg_ads:.1f} ads/group — aim for 3+ for proper A/B testing.")
        elif avg_ads >= 1:
            pts += 10
            detail_parts.append(f"Only {avg_ads:.1f} ad/group — add at least 2 more per group.")
        else:
            detail_parts.append("No active ads found.")

        # Keywords per group  (30 pts max)
        if   5 <= avg_kw <= 20: pts += 30
        elif 1 <= avg_kw <  5:
            pts += 20
            detail_parts.append(f"{avg_kw:.0f} keywords/group — consider adding more tightly-themed keywords.")
        elif 21 <= avg_kw <= 50:
            pts += 15
            detail_parts.append(f"{avg_kw:.0f} keywords/group is getting broad — split into tighter groups.")
        elif avg_kw > 50:
            pts += 5
            detail_parts.append(f"{avg_kw:.0f} keywords/group is too many — relevance suffers at this volume.")
        elif avg_kw > 0:
            pts += 10

        # Conversion tracking  (15 pts)
        has_conv = _scalar(
            """SELECT SUM(gs.conversions)
               FROM gads_stats_daily gs
               JOIN ads_campaigns ac ON ac.id = gs.entity_id AND ac.account_id = :aid
               WHERE gs.entity_type = 'campaign' AND gs.date >= :d""",
            {"aid": account_id, "d": ninety_ago},
        ) or 0
        if has_conv > 0:
            pts += 15
        else:
            detail_parts.append("No conversions recorded — verify conversion tracking is set up.")

        # Active extensions / negative keywords as management signal  (20 pts)
        # Grader checks active extensions via API; here we use neg_kw presence as
        # the best available proxy for active account management.
        neg_count_mgmt = _scalar(
            """SELECT COUNT(*) FROM negative_keywords nk
               LEFT JOIN ads_campaigns ac ON ac.id = nk.campaign_id
               WHERE ac.account_id = :aid""",
            {"aid": account_id},
        )
        if neg_count_mgmt > 0:
            pts += 20
        else:
            detail_parts.append("No negative keywords found — add negatives and ad extensions to protect budget.")

        account_activity_score = min(100.0, float(pts))
        activity_detail = (
            f"Structure: {ag_count} ad groups, {avg_ads:.1f} ads/group, {avg_kw:.0f} keywords/group."
            + (" " + " ".join(detail_parts) if detail_parts else " Conversion tracking active.")
        )
    except Exception:
        account_activity_score = 50.0
        activity_detail = "Could not load account structure data."

    # ─────────────────────────────────────────────────────────────────────────
    # 7. LONG-TAIL KEYWORDS  (8%)
    # % of keywords with 3+ words vs 50% benchmark  ← identical to grader
    # ─────────────────────────────────────────────────────────────────────────
    long_tail_score  = 50.0
    long_tail_detail = "No keyword data available."

    try:
        kw_rows = _rows(
            """SELECT k.text FROM keywords k
               JOIN ad_groups ag     ON ag.id = k.ad_group_id
               JOIN ads_campaigns ac ON ac.id = ag.campaign_id
               WHERE ac.account_id = :aid AND k.status != 'removed'""",
            {"aid": account_id},
        )
        if kw_rows:
            total_kw   = len(kw_rows)
            long_tail  = sum(1 for r in kw_rows if len((r["text"] or "").split()) >= 3)
            lt_pct     = long_tail / total_kw
            long_tail_score = min(100.0, (lt_pct / LONG_TAIL_TARGET) * 100.0)
            lt_display = round(lt_pct * 100)
            if lt_pct >= 0.50:
                long_tail_detail = f"{lt_display}% of keywords are 3+ words — good specificity targets high-intent buyers."
            elif lt_pct >= 0.25:
                long_tail_detail = f"Only {lt_display}% of keywords are 3+ words. Add location + service-specific phrases to reach higher-intent buyers at lower CPC."
            else:
                long_tail_detail = f"Only {lt_display}% long-tail keywords. Broad single-word terms are expensive and attract low-intent traffic."
    except Exception:
        pass

    # ─────────────────────────────────────────────────────────────────────────
    # 8. IMPRESSION SHARE — RANK  (5%)
    # AVG(lost_is_rank) from campaign stats — budget-lost IS is NOT penalised
    # Step function identical to grader _score_impression_share()
    # ─────────────────────────────────────────────────────────────────────────
    impression_share_score = 50.0
    is_detail              = "No impression share data synced."

    try:
        is_row = _one(
            """SELECT AVG(gs.lost_is_rank)   AS rank_lost,
                      AVG(gs.lost_is_budget) AS budget_lost
               FROM gads_stats_daily gs
               JOIN ads_campaigns ac ON ac.id = gs.entity_id AND ac.account_id = :aid
               WHERE gs.entity_type = 'campaign' AND gs.date >= :d
                 AND gs.lost_is_rank IS NOT NULL""",
            {"aid": account_id, "d": ninety_ago},
        )
        if is_row and is_row["rank_lost"] is not None:
            rank_pct   = float(is_row["rank_lost"]   or 0) * 100
            budget_pct = float(is_row["budget_lost"] or 0) * 100

            if   rank_pct <  5:  impression_share_score = 95.0
            elif rank_pct < 10:  impression_share_score = 80.0
            elif rank_pct < 20:  impression_share_score = 62.0
            elif rank_pct < 30:  impression_share_score = 45.0
            elif rank_pct < 40:  impression_share_score = 28.0
            else:                impression_share_score = 10.0

            rank_msg = f"Losing {rank_pct:.0f}% of auctions to rank (quality/bid issue)."
            budget_msg = (
                f" Budget is also limiting delivery by {budget_pct:.0f}% — note: budget losses aren't scored."
                if budget_pct > 10 else ""
            )
            is_detail = rank_msg + budget_msg
    except Exception:
        pass

    # ─────────────────────────────────────────────────────────────────────────
    # 9. MOBILE ADVERTISING  (5%)
    # gads_stats_daily doesn't store per-device breakdowns.
    # Neutral default — grader needs live API data (campaign_criterion) for this.
    # ─────────────────────────────────────────────────────────────────────────
    mobile_score  = 50.0
    mobile_detail = (
        "Mobile bid adjustment analysis requires a live Grader scan. "
        "Run the Google Ads Health Grader for your full mobile score."
    )

    # ─────────────────────────────────────────────────────────────────────────
    # 10. EXPANDED TEXT ADS  (0%)  — informational only
    # ─────────────────────────────────────────────────────────────────────────
    has_eta              = False
    expanded_score       = 85.0  # Not used in weighting; kept for DB parity
    try:
        eta_count = _scalar(
            """SELECT COUNT(*) FROM ads a
               JOIN ad_groups ag     ON ag.id = a.ad_group_id
               JOIN ads_campaigns ac ON ac.id = ag.campaign_id
               WHERE ac.account_id = :aid AND a.status != 'removed'
                 AND LOWER(a.ad_type) LIKE '%expanded%'""",
            {"aid": account_id},
        )
        has_eta = eta_count > 0
    except Exception:
        pass

    # ─────────────────────────────────────────────────────────────────────────
    # WEIGHTED OVERALL  — identical formula to analyzer._calculate_overall_score()
    # ─────────────────────────────────────────────────────────────────────────
    scores_map = {
        "wasted_spend":         wasted_spend_score,
        "quality_score":        quality_score_score,
        "landing_pages":        landing_score,
        "ctr_optimization":     ctr_score,
        "text_ad_optimization": text_ad_score,
        "account_activity":     account_activity_score,
        "long_tail_keywords":   long_tail_score,
        "impression_share":     impression_share_score,
        "mobile_advertising":   mobile_score,
        "expanded_text_ads":    expanded_score,
    }

    overall = sum(scores_map[k] * DIMENSION_WEIGHTS[k] for k in DIMENSION_WEIGHTS)

    # Extra waste penalty (same as analyzer.py)
    # waste_pct already computed above; apply: -(waste_pct - 10) * 2 when waste > 10%
    if waste_pct > 10:
        overall = max(0.0, overall - (waste_pct - 10) * 2.0)

    overall = round(max(0.0, min(100.0, overall)), 1)

    # ─────────────────────────────────────────────────────────────────────────
    # DIMENSION RESPONSE DICT
    # ─────────────────────────────────────────────────────────────────────────
    dimensions = {
        "wasted_spend": {
            "score": round(wasted_spend_score, 1), "label": "Wasted Spend",
            "weight": 25, "detail": waste_detail, "color": _color(wasted_spend_score),
        },
        "quality_score": {
            "score": round(quality_score_score, 1), "label": "Quality Score",
            "weight": 15, "detail": qs_detail, "color": _color(quality_score_score),
        },
        "ctr_optimization": {
            "score": round(ctr_score, 1), "label": "CTR Optimization",
            "weight": 12, "detail": ctr_detail, "color": _color(ctr_score),
        },
        "landing_pages": {
            "score": round(landing_score, 1), "label": "Landing Page Experience",
            "weight": 10, "detail": landing_detail, "color": _color(landing_score),
        },
        "text_ad_optimization": {
            "score": round(text_ad_score, 1), "label": "Text Ad Optimization",
            "weight": 10, "detail": text_ad_detail, "color": _color(text_ad_score),
        },
        "account_activity": {
            "score": round(account_activity_score, 1), "label": "Account Activity",
            "weight": 10, "detail": activity_detail, "color": _color(account_activity_score),
        },
        "long_tail_keywords": {
            "score": round(long_tail_score, 1), "label": "Long-Tail Keywords",
            "weight": 8, "detail": long_tail_detail, "color": _color(long_tail_score),
        },
        "impression_share": {
            "score": round(impression_share_score, 1), "label": "Impression Share (Rank)",
            "weight": 5, "detail": is_detail, "color": _color(impression_share_score),
        },
        "mobile_advertising": {
            "score": round(mobile_score, 1), "label": "Mobile Advertising",
            "weight": 5, "detail": mobile_detail, "color": _color(mobile_score),
        },
        "expanded_text_ads": {
            "score": round(expanded_score, 1), "label": "Expanded Text Ads",
            "weight": 0, "flag_only": True,
            "detail": (
                "Legacy ETAs still active — these can't be edited. Replace with RSAs."
                if has_eta else "No legacy ETAs found."
            ),
            "color": "yellow" if has_eta else "gray",
        },
    }

    # Top issues (up to 4 weakest weighted dimensions)
    top_issues = []
    for key, dim in sorted(
        ((k, v) for k, v in dimensions.items() if v.get("weight", 0) > 0),
        key=lambda x: x[1]["score"],
    ):
        if dim["score"] < 70:
            top_issues.append({
                "title":  dim["label"],
                "score":  dim["score"],
                "impact": "High" if dim["score"] < 40 else ("Medium" if dim["score"] < 60 else "Low"),
                "detail": dim["detail"],
                "action": key,
            })
        if len(top_issues) >= 4:
            break

    result = {
        "overall":    overall,
        "grade":      _grade(overall),
        "dimensions": dimensions,
        "top_issues": top_issues,
        "has_eta":    has_eta,
    }

    # Goal performance (unchanged from original — data source is the same)
    if aid_goals is not None:
        try:
            if hasattr(aid_goals, "__dict__"):
                target_leads    = getattr(aid_goals, "target_monthly_leads", None)
                target_cpa_cents = getattr(aid_goals, "target_cpa_cents", None)
            else:
                target_leads    = aid_goals.get("target_monthly_leads")
                target_cpa_cents = aid_goals.get("target_cpa_cents")

            if target_leads:
                month_start = today.replace(day=1)
                actual_row  = _one(
                    """SELECT SUM(gs.conversions) AS conv,
                              SUM(gs.cost_micros) / 1000000.0 AS spend
                       FROM gads_stats_daily gs
                       JOIN ads_campaigns ac ON ac.id = gs.entity_id AND ac.account_id = :aid
                       WHERE gs.entity_type = 'campaign' AND gs.date >= :d""",
                    {"aid": account_id, "d": month_start},
                )
                actual_leads = int(float((actual_row or {}).get("conv") or 0))
                actual_spend = float((actual_row or {}).get("spend") or 0)
                on_track     = actual_leads >= target_leads
                gap          = max(0, target_leads - actual_leads)
                cpa          = (actual_spend / actual_leads) if actual_leads > 0 else (
                    target_cpa_cents / 100 if target_cpa_cents else 0
                )

                if on_track:
                    gap_message = f"You've hit your monthly lead goal of {target_leads}. Excellent!"
                elif gap > 0 and cpa > 0:
                    gap_message = (
                        f"You need {gap} more leads to hit your goal. "
                        f"At your current CPA of ${cpa:.0f}, that's ~${round(gap * cpa)} more in budget."
                    )
                else:
                    gap_message = f"You need {gap} more leads to hit your monthly goal of {target_leads}."

                result["goal_performance"] = {
                    "target_leads": target_leads,
                    "actual_leads": actual_leads,
                    "on_track":     on_track,
                    "gap_message":  gap_message,
                }
        except Exception:
            pass

    return result


def get_grader_context_for_agents(account_id: int) -> dict:
    """
    Return the latest grader report's key signals as a structured dict
    for injection into agent context dicts.

    Agents can use this to prioritise work based on quality health, not
    just raw performance numbers.  Callers should merge this under a
    'grader_context' key in the agent's context dict.

    Returns an empty dict if no grader report exists for the account.
    """
    try:
        from app.models_ads_grader import GoogleAdsGraderReport

        report = (
            GoogleAdsGraderReport.query
            .filter_by(account_id=account_id)
            .filter(GoogleAdsGraderReport.account_id.isnot(None))
            .order_by(GoogleAdsGraderReport.created_at.desc())
            .first()
        )
        if not report:
            return {}

        dm = report.detailed_metrics or {}
        st = dm.get("search_terms", {})
        bp = report.best_practices or {}

        return {
            # Overall quality health
            "overall_score":  float(report.overall_score or 0),
            "overall_grade":  report.overall_grade or "",
            "report_date":    report.report_date.isoformat() if report.report_date else None,

            # Section scores — agents use these to prioritise actions
            "section_scores": {
                "wasted_spend":         report.wasted_spend_score,
                "quality_score":        report.quality_score_optimization_score,
                "landing_pages":        report.landing_page_score,
                "ctr_optimization":     report.ctr_optimization_score,
                "text_ad_optimization": report.text_ad_optimization_score,
                "account_activity":     report.account_activity_score,
                "long_tail_keywords":   report.long_tail_keywords_score,
                "impression_share":     report.impression_share_score,
                "mobile_advertising":   report.mobile_advertising_score,
            },

            # Waste signal — direct input for negative keyword agent
            "waste_terms":      st.get("waste_terms", []),     # list of {term, cost, clicks}
            "waste_term_count": st.get("waste_term_count", 0),
            "waste_spend":      st.get("waste_spend", 0.0),

            # QS component breakdowns — for targeting specific fixes
            "post_click_distribution": (
                dm.get("quality_scores", {}).get("post_click_distribution", {})
            ),
            "ad_relevance_distribution": (
                dm.get("quality_scores", {}).get("creative_distribution", {})
            ),

            # Ad strength — signals which ad groups need creative work
            "ad_strength_distribution": (
                dm.get("ads", {}).get("ad_strength_distribution", {})
            ),

            # Device bid alignment — for mobile bid agent
            "device_bid_adjustments": dm.get("device_bid_adjustments", {}),
            "device_performance":     dm.get("device_performance", {}),

            # Impression share rank vs budget split
            "impression_share_detail": dm.get("impression_share", {}),

            # Best practices flags
            "has_conversion_tracking": bp.get("conversion_tracking", False),
            "has_ad_extensions":       bp.get("ad_extensions", False),
            "has_mobile_bid_adj":      bp.get("mobile_bid_adjustments", False),
            "has_legacy_eta_ads":      bp.get("legacy_eta_ads", False),
        }
    except Exception:
        return {}
