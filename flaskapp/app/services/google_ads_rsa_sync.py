# app/services/google_ads_rsa_sync.py
"""
RSA (Responsive Search Ad) asset performance sync and reporting.

Pulls per-asset performance labels from the Google Ads API and stores them in
rsa_assets.  Also provides a structured performance report and an auto-promote
function that writes OptimizerRecommendation rows for winning/losing assets.
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers (mirrored from google_ads_sync for independence)
# ---------------------------------------------------------------------------

def _int(v: Any, default: int = 0) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return default


def _str(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _label_name(v: Any) -> Optional[str]:
    """Safely extract .name from an enum-like object or string."""
    if v is None:
        return None
    if hasattr(v, "name"):
        return v.name
    return str(v).strip() or None


# ---------------------------------------------------------------------------
# GAQL query
# ---------------------------------------------------------------------------

_RSA_QUERY = """
SELECT ad_group_ad.ad.id,
       ad_group_ad.ad.responsive_search_ad.headlines,
       ad_group_ad.ad.responsive_search_ad.descriptions,
       ad_group_ad.ad_strength,
       ad_group.id,
       ad_group.name,
       campaign.id,
       campaign.name,
       metrics.impressions,
       metrics.clicks,
       metrics.conversions
FROM ad_group_ad
WHERE ad_group_ad.ad.type = 'RESPONSIVE_SEARCH_AD'
  AND ad_group_ad.status != 'REMOVED'
""".strip()


# ---------------------------------------------------------------------------
# A. sync_rsa_assets
# ---------------------------------------------------------------------------

def sync_rsa_assets(account_id: int) -> Dict[str, Any]:
    """
    Pull RSA asset performance from Google Ads and upsert into rsa_assets.

    Returns {"ads_synced": N, "assets_synced": N, "errors": []}.
    """
    from app import db
    from app.models_ads import AdsAd, AdsAdGroup, AdsCampaign, RsaAsset
    from app.google.utils_ads import resolve_ads_context, google_ads_search
    from app.google.token_utils import ensure_access_token

    RsaAsset.ensure_columns()

    summary: Dict[str, Any] = {
        "ads_synced": 0,
        "assets_synced": 0,
        "errors": [],
    }

    # ── credentials ──────────────────────────────────────────────────────────
    try:
        ctx = resolve_ads_context(account_id)
        customer_id = ctx.get("customer_id")
        login_customer_id = ctx.get("login_customer_id")
        if not customer_id:
            summary["errors"].append("No Google Ads customer_id configured for this account.")
            return summary
        access_token, _ = ensure_access_token(account_id, ("ads", "lsa"))
    except Exception as exc:
        summary["errors"].append(f"Credential error: {exc}")
        return summary

    # ── fetch rows ───────────────────────────────────────────────────────────
    try:
        rows = google_ads_search(
            access_token=access_token,
            customer_id=customer_id,
            query=_RSA_QUERY,
            login_customer_id=login_customer_id,
            stream=True,
        )
    except Exception as exc:
        summary["errors"].append(f"API fetch error: {exc}")
        return summary

    # ── build local lookup tables so we avoid N+1 queries ───────────────────
    # campaign lookup: google_campaign_id → local id
    camp_lookup: Dict[str, int] = {}
    for c in AdsCampaign.query.filter_by(account_id=account_id).all():
        if c.google_campaign_id:
            camp_lookup[str(c.google_campaign_id).strip()] = c.id

    # ad-group lookup: google_ad_group_id → (local id, campaign local id)
    ag_lookup: Dict[str, tuple] = {}
    for ag in (AdsAdGroup.query
               .join(AdsCampaign, AdsCampaign.id == AdsAdGroup.campaign_id)
               .filter(AdsCampaign.account_id == account_id).all()):
        if ag.google_ad_group_id:
            ag_lookup[str(ag.google_ad_group_id).strip()] = (ag.id, ag.campaign_id)

    def _get_or_create_campaign(google_cid: str, name: str) -> int:
        key = google_cid.strip()
        if key in camp_lookup:
            return camp_lookup[key]
        camp = AdsCampaign(
            account_id=account_id,
            name=name or f"Campaign {google_cid}",
            status="enabled",
            google_campaign_id=key,
            daily_budget_cents=0,
        )
        db.session.add(camp)
        db.session.flush()
        camp_lookup[key] = camp.id
        return camp.id

    def _get_or_create_adgroup(camp_local_id: int, google_agid: str, name: str) -> int:
        key = google_agid.strip()
        if key in ag_lookup:
            return ag_lookup[key][0]
        ag = AdsAdGroup(
            campaign_id=camp_local_id,
            name=name or f"Ad Group {google_agid}",
            status="enabled",
            google_ad_group_id=key,
        )
        db.session.add(ag)
        db.session.flush()
        ag_lookup[key] = (ag.id, camp_local_id)
        return ag.id

    def _get_or_create_ad(ag_local_id: int, google_ad_id: str) -> int:
        """Return local AdsAd.id, creating a minimal stub if needed."""
        ad = AdsAd.query.filter_by(google_ad_id=google_ad_id).first()
        if ad is None:
            ad = AdsAd(
                ad_group_id=ag_local_id,
                status="enabled",
                ad_type="text",
                headline1="(synced RSA)",
                final_url="",
                google_ad_id=google_ad_id,
            )
            db.session.add(ad)
            db.session.flush()
        return ad.id

    def _upsert_asset(
        google_ad_id: str,
        ad_local_id: int,
        asset_type: str,
        asset_text: str,
        pinned_field: Optional[str],
        performance_label: Optional[str],
        impressions: int,
        clicks: int,
        conversions: float,
    ) -> None:
        existing = RsaAsset.query.filter_by(
            google_ad_id=google_ad_id,
            asset_type=asset_type,
            asset_text=asset_text,
        ).first()
        if existing:
            existing.ad_id = ad_local_id
            existing.pinned_field = pinned_field
            existing.performance_label = performance_label
            existing.impressions = impressions
            existing.clicks = clicks
            existing.conversions = conversions
        else:
            db.session.add(RsaAsset(
                account_id=account_id,
                ad_id=ad_local_id,
                google_ad_id=google_ad_id,
                asset_type=asset_type,
                asset_text=asset_text,
                pinned_field=pinned_field,
                performance_label=performance_label,
                impressions=impressions,
                clicks=clicks,
                conversions=conversions,
            ))

    # ── process each API row ─────────────────────────────────────────────────
    try:
        for row in rows:
            try:
                ad_data = row.get("adGroupAd", {}).get("ad", {})
                rsa = ad_data.get("responsiveSearchAd", {})
                metrics = row.get("metrics", {})
                ag_data = row.get("adGroup", {})
                camp_data = row.get("campaign", {})

                google_ad_id = _str(ad_data.get("id"))
                if not google_ad_id:
                    continue

                google_cid = _str(camp_data.get("id"))
                google_agid = _str(ag_data.get("id"))
                camp_name = camp_data.get("name", "")
                ag_name = ag_data.get("name", "")

                impressions = _int(metrics.get("impressions"))
                clicks = _int(metrics.get("clicks"))
                try:
                    conversions = float(metrics.get("conversions") or 0)
                except (TypeError, ValueError):
                    conversions = 0.0

                # Ensure campaign / ad group / ad rows exist locally
                camp_local_id = (
                    _get_or_create_campaign(google_cid, camp_name)
                    if google_cid else None
                )
                ag_local_id = (
                    _get_or_create_adgroup(camp_local_id, google_agid, ag_name)
                    if (google_agid and camp_local_id) else None
                )
                ad_local_id = _get_or_create_ad(ag_local_id or 0, google_ad_id)

                # ── headlines ──
                headlines = rsa.get("headlines") or []
                for headline in headlines:
                    text = _str(headline.get("text") if isinstance(headline, dict) else getattr(headline, "text", None))
                    if not text:
                        continue
                    if isinstance(headline, dict):
                        pinned = _str(headline.get("pinnedField"))
                        label = _str(headline.get("assetPerformanceLabel"))
                    else:
                        pinned = _label_name(getattr(headline, "pinned_field", None))
                        label = _label_name(getattr(headline, "asset_performance_label", None))
                    _upsert_asset(
                        google_ad_id, ad_local_id,
                        "headline", text, pinned, label,
                        impressions, clicks, conversions,
                    )
                    summary["assets_synced"] += 1

                # ── descriptions ──
                descriptions = rsa.get("descriptions") or []
                for desc in descriptions:
                    text = _str(desc.get("text") if isinstance(desc, dict) else getattr(desc, "text", None))
                    if not text:
                        continue
                    if isinstance(desc, dict):
                        pinned = _str(desc.get("pinnedField"))
                        label = _str(desc.get("assetPerformanceLabel"))
                    else:
                        pinned = _label_name(getattr(desc, "pinned_field", None))
                        label = _label_name(getattr(desc, "asset_performance_label", None))
                    _upsert_asset(
                        google_ad_id, ad_local_id,
                        "description", text, pinned, label,
                        impressions, clicks, conversions,
                    )
                    summary["assets_synced"] += 1

                summary["ads_synced"] += 1

            except Exception as row_exc:
                logger.warning("RSA row processing error: %s", row_exc)
                summary["errors"].append(f"Row error: {row_exc}")

        db.session.commit()
        logger.info(
            "RSA sync complete for account %s — ads: %d, assets: %d",
            account_id, summary["ads_synced"], summary["assets_synced"],
        )

    except Exception as exc:
        db.session.rollback()
        summary["errors"].append(f"Sync error: {exc}")
        logger.exception("RSA sync failed for account %s", account_id)

    return summary


# ---------------------------------------------------------------------------
# B. get_rsa_performance_report
# ---------------------------------------------------------------------------

def get_rsa_performance_report(account_id: int) -> Dict[str, Any]:
    """
    Return a structured, plain-English performance report for all RSA assets
    belonging to this account.

    Keys: best_headlines, worst_headlines, best_descriptions, worst_descriptions,
          ads_with_low_assets, recommendations.
    """
    from app.models_ads import RsaAsset, AdsAd, AdsAdGroup, AdsCampaign
    from sqlalchemy.orm import joinedload

    # Pull all assets for this account
    assets = RsaAsset.query.filter_by(account_id=account_id).all()

    if not assets:
        return {
            "best_headlines": [],
            "worst_headlines": [],
            "best_descriptions": [],
            "worst_descriptions": [],
            "ads_with_low_assets": [],
            "recommendations": ["No RSA assets found — sync your ads first."],
        }

    # Build ad/adgroup/campaign name lookup
    ad_ids = {a.ad_id for a in assets if a.ad_id}
    ad_rows = AdsAd.query.filter(AdsAd.id.in_(ad_ids)).all() if ad_ids else []
    ad_map = {r.id: r for r in ad_rows}

    ag_ids = {r.ad_group_id for r in ad_rows}
    ag_rows = AdsAdGroup.query.filter(AdsAdGroup.id.in_(ag_ids)).all() if ag_ids else []
    ag_map = {r.id: r for r in ag_rows}

    camp_ids = {r.campaign_id for r in ag_rows}
    camp_rows = AdsCampaign.query.filter(
        AdsCampaign.id.in_(camp_ids),
        AdsCampaign.account_id == account_id,
    ).all() if camp_ids else []
    camp_map = {r.id: r for r in camp_rows}

    def _campaign_name(asset: RsaAsset) -> Optional[str]:
        ad = ad_map.get(asset.ad_id)
        if not ad:
            return None
        ag = ag_map.get(ad.ad_group_id)
        if not ag:
            return None
        camp = camp_map.get(ag.campaign_id)
        return camp.name if camp else None

    def _adgroup_name(asset: RsaAsset) -> Optional[str]:
        ad = ad_map.get(asset.ad_id)
        if not ad:
            return None
        ag = ag_map.get(ad.ad_group_id)
        return ag.name if ag else None

    # ── group by (asset_type, asset_text, performance_label) ─────────────────
    # For each unique text we aggregate ad_count and campaigns.
    from collections import defaultdict

    # text → {"label": ..., "ad_count": ..., "campaigns": set, "impressions": ...}
    headline_agg: Dict[str, dict] = defaultdict(lambda: {
        "label": None, "ad_count": 0, "campaigns": set(), "impressions": 0
    })
    desc_agg: Dict[str, dict] = defaultdict(lambda: {
        "label": None, "ad_count": 0, "campaigns": set(), "impressions": 0
    })

    for asset in assets:
        bucket = headline_agg if asset.asset_type == "headline" else desc_agg
        entry = bucket[asset.asset_text]
        entry["label"] = asset.performance_label
        entry["ad_count"] += 1
        camp_name = _campaign_name(asset)
        if camp_name:
            entry["campaigns"].add(camp_name)
        entry["impressions"] += asset.impressions or 0

    def _to_list(agg: dict) -> List[dict]:
        return [
            {
                "text": text,
                "label": d["label"],
                "ad_count": d["ad_count"],
                "campaigns": sorted(d["campaigns"]),
                "impressions": d["impressions"],
            }
            for text, d in agg.items()
        ]

    all_headlines = _to_list(headline_agg)
    all_descs = _to_list(desc_agg)

    def _filter_sort(items: List[dict], label: str, reverse: bool = True) -> List[dict]:
        filtered = [i for i in items if i["label"] == label]
        return sorted(filtered, key=lambda x: x["impressions"], reverse=reverse)

    best_headlines = _filter_sort(all_headlines, "BEST")
    worst_headlines = _filter_sort(all_headlines, "LOW")
    best_descriptions = _filter_sort(all_descs, "BEST")
    worst_descriptions = _filter_sort(all_descs, "LOW")

    # ── ads with too many low-performing assets ───────────────────────────────
    # Group by google_ad_id: count LOW labels
    ad_asset_map: Dict[str, dict] = defaultdict(lambda: {
        "low_count": 0, "total": 0, "ad_id": None,
        "adgroup": None, "campaign": None,
    })

    for asset in assets:
        key = asset.google_ad_id or str(asset.ad_id)
        entry = ad_asset_map[key]
        entry["total"] += 1
        entry["ad_id"] = asset.ad_id
        if asset.performance_label == "LOW":
            entry["low_count"] += 1
        if not entry["adgroup"]:
            entry["adgroup"] = _adgroup_name(asset)
        if not entry["campaign"]:
            entry["campaign"] = _campaign_name(asset)

    ads_with_low: List[dict] = []
    for google_ad_id, data in ad_asset_map.items():
        if data["low_count"] >= 1:
            low = data["low_count"]
            ads_with_low.append({
                "ad_id": data["ad_id"],
                "google_ad_id": google_ad_id,
                "ad_group": data["adgroup"] or "Unknown ad group",
                "campaign": data["campaign"] or "Unknown campaign",
                "low_count": low,
                "message": (
                    f"{low} {'headline' if low == 1 else 'headlines/descriptions'} "
                    f"{'isn\'t' if low == 1 else 'aren\'t'} performing — "
                    "consider replacing them."
                ),
            })

    ads_with_low.sort(key=lambda x: x["low_count"], reverse=True)

    # ── plain-English recommendations ────────────────────────────────────────
    recommendations: List[str] = []

    if best_headlines:
        top = best_headlines[0]["text"]
        recommendations.append(
            f"Headline \"{top}\" is your best performer — use it in more ads."
        )

    # Low headlines running with significant traffic
    low_with_traffic = [
        h for h in worst_headlines
        if h["impressions"] >= 500
    ]
    if low_with_traffic:
        count = len(low_with_traffic)
        recommendations.append(
            f"{count} {'headline' if count == 1 else 'headlines'} marked LOW "
            f"{'has' if count == 1 else 'have'} received 500+ impressions without "
            "improvement — pause and replace them."
        )

    if best_descriptions:
        top_desc = best_descriptions[0]["text"]
        recommendations.append(
            f"Description \"{top_desc[:60]}{'...' if len(top_desc) > 60 else ''}\" "
            "is resonating with customers — keep it in your top ads."
        )

    learning = [a for a in assets if a.performance_label == "LEARNING"]
    if learning:
        recommendations.append(
            f"{len(learning)} assets are still in the learning phase — "
            "avoid making changes until Google has enough data (usually 2–4 weeks)."
        )

    if not recommendations:
        recommendations.append(
            "Sync your latest data to get personalized recommendations."
        )

    return {
        "best_headlines": best_headlines,
        "worst_headlines": worst_headlines,
        "best_descriptions": best_descriptions,
        "worst_descriptions": worst_descriptions,
        "ads_with_low_assets": ads_with_low,
        "recommendations": recommendations,
    }


# ---------------------------------------------------------------------------
# C. auto_promote_winners
# ---------------------------------------------------------------------------

def auto_promote_winners(account_id: int) -> Dict[str, Any]:
    """
    Inspect RSA asset performance and create OptimizerRecommendation rows for:
    1. BEST headlines that are not pinned to position 1 or 2.
    2. Ads with 3+ LOW-labeled assets that have received >500 impressions.

    Returns {"recommendations_created": N, "errors": []}.
    """
    from app import db
    from app.models_ads import RsaAsset, AdsAd, AdsAdGroup, AdsCampaign, OptimizerRecommendation

    result: Dict[str, Any] = {"recommendations_created": 0, "errors": []}

    try:
        assets = RsaAsset.query.filter_by(account_id=account_id).all()
        if not assets:
            return result

        # Build ad-level groupings
        # google_ad_id → list of assets
        by_ad: Dict[str, List[RsaAsset]] = defaultdict(list)
        for asset in assets:
            key = asset.google_ad_id or str(asset.ad_id or "")
            if key:
                by_ad[key].append(asset)

        # Helper: get local AdsAd id for a group of assets
        def _ad_local_id(asset_list: List[RsaAsset]) -> Optional[int]:
            for a in asset_list:
                if a.ad_id:
                    return a.ad_id
            return None

        _PIN_POSITIONS = {"HEADLINE_1", "HEADLINE_2", "1", "2"}

        for google_ad_id, ad_assets in by_ad.items():
            ad_local_id = _ad_local_id(ad_assets)
            if not ad_local_id:
                continue

            headlines = [a for a in ad_assets if a.asset_type == "headline"]
            total_impressions = max((a.impressions or 0) for a in ad_assets) if ad_assets else 0

            # ── Rule 1: BEST headline not pinned to position 1 or 2 ──────────
            for asset in headlines:
                if asset.performance_label != "BEST":
                    continue
                pinned = (asset.pinned_field or "").upper()
                already_pinned = any(p in pinned for p in _PIN_POSITIONS) if pinned else False
                if already_pinned:
                    continue

                # Check if a recommendation already exists (open)
                existing = OptimizerRecommendation.query.filter_by(
                    account_id=account_id,
                    scope_type="ad",
                    scope_id=ad_local_id,
                    category="rsa_pin_winner",
                    status="open",
                ).first()
                if existing:
                    continue

                rec = OptimizerRecommendation(
                    account_id=account_id,
                    scope_type="ad",
                    scope_id=ad_local_id,
                    category="rsa_pin_winner",
                    title=f"Pin your best headline to top position",
                    details=(
                        f'The headline "{asset.asset_text}" is labeled BEST by Google '
                        f"but is not locked to position 1 or 2. Pinning it ensures it "
                        f"always shows — which typically increases click-through rate."
                    ),
                    expected_impact="Potential CTR improvement by always showing your top headline.",
                    severity=2,
                    suggested_action_json=json.dumps({
                        "action": "pin_headline",
                        "google_ad_id": google_ad_id,
                        "asset_text": asset.asset_text,
                        "pin_to": "HEADLINE_1",
                    }),
                )
                db.session.add(rec)
                result["recommendations_created"] += 1

            # ── Rule 2: 3+ LOW assets with >500 impressions ──────────────────
            low_assets = [a for a in ad_assets if a.performance_label == "LOW"]
            if len(low_assets) >= 3 and total_impressions > 500:
                existing = OptimizerRecommendation.query.filter_by(
                    account_id=account_id,
                    scope_type="ad",
                    scope_id=ad_local_id,
                    category="rsa_replace_low",
                    status="open",
                ).first()
                if not existing:
                    low_texts = [a.asset_text for a in low_assets[:5]]
                    rec = OptimizerRecommendation(
                        account_id=account_id,
                        scope_type="ad",
                        scope_id=ad_local_id,
                        category="rsa_replace_low",
                        title=f"Replace {len(low_assets)} underperforming ad copy pieces",
                        details=(
                            f"This ad has {len(low_assets)} headlines/descriptions marked LOW "
                            f"after {total_impressions:,} impressions. Google is struggling to "
                            f"find winning combinations. Replace them with fresh copy that "
                            f"highlights unique benefits, urgency, or social proof."
                        ),
                        expected_impact=(
                            "Replacing low-performing copy can improve ad strength and "
                            "unlock better combinations."
                        ),
                        severity=2,
                        suggested_action_json=json.dumps({
                            "action": "replace_low_assets",
                            "google_ad_id": google_ad_id,
                            "low_asset_texts": low_texts,
                            "impressions": total_impressions,
                        }),
                    )
                    db.session.add(rec)
                    result["recommendations_created"] += 1

        db.session.commit()
        logger.info(
            "auto_promote_winners: created %d recommendations for account %s",
            result["recommendations_created"], account_id,
        )

    except Exception as exc:
        db.session.rollback()
        result["errors"].append(str(exc))
        logger.exception("auto_promote_winners failed for account %s", account_id)

    return result
