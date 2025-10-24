# app/google/campaigns.py
from __future__ import annotations

from flask import Blueprint, request, jsonify
from app import db
from app.models_ads import (
    AdsCampaign,
    AdsAdGroup,
    AdsAd,
    AdsKeyword,
    NegativeKeyword,
    SharedNegativeMap,
)
import json

# Keep this blueprint; it's already registered in app/__init__.py with url_prefix="/account/campaigns"
campaigns_bp = Blueprint("campaigns_bp", __name__)

@campaigns_bp.post("/drafts")
def create_draft():
    """
    Accepts a draft payload (validated echo for now):
    {
      "campaign": {...},
      "ad_groups": [
        {
          "name": "...",
          "cpc_bid_cents": 125,
          "ads": [{"final_url": "...", "headlines": [...], "descriptions": [...], "path1": "...", "path2": "..."}],
          "keywords": [{"text": "...", "match_type": "EXACT"}, ...],
          "negatives": [{"text": "...", "match_type": "PHRASE"}, ...]
        }
      ],
      "shared_negative_list_ids": [1,2]
    }
    """
    payload = request.get_json(force=True)
    return jsonify({"status": "ok", "draft": payload})


@campaigns_bp.post("/publish")
def publish_campaign():
    """
    Persists campaign → ad groups → ads/keywords/negatives and attaches any shared negative lists.
    """
    payload = request.get_json(force=True)
    try:
        c = payload["campaign"]
        campaign = AdsCampaign(
            name=c["name"],
            status=c.get("status", "enabled"),
            daily_budget_cents=c.get("daily_budget_cents", 0),
            objective=c.get("objective"),
            network=c.get("network"),
            language=c.get("language", "en"),
            geo_targets=json.dumps(c.get("geo_targets")) if isinstance(c.get("geo_targets"), (list, dict)) else c.get("geo_targets"),
            start_date=c.get("start_date"),
            end_date=c.get("end_date"),
        )
        db.session.add(campaign)
        db.session.flush()

        for ag in payload.get("ad_groups", []):
            ag_row = AdsAdGroup(
                campaign_id=campaign.id,
                name=ag["name"],
                status=ag.get("status", "enabled"),
                max_cpc_cents=ag.get("cpc_bid_cents"),
            )
            db.session.add(ag_row)
            db.session.flush()

            for ad in ag.get("ads", []):
                # Support RSA-like payload: lists of headlines/descriptions -> take first 3 / first 2
                headlines = ad.get("headlines") or []
                descriptions = ad.get("descriptions") or []
                ad_row = AdsAd(
                    ad_group_id=ag_row.id,
                    status=ad.get("status", "enabled"),
                    ad_type=ad.get("ad_type", "text"),
                    final_url=ad["final_url"],
                    path1=ad.get("path1"),
                    path2=ad.get("path2"),
                    headline1=(headlines[0] if len(headlines) > 0 else ad.get("headline1", ""))[:30],
                    headline2=(headlines[1] if len(headlines) > 1 else ad.get("headline2"))[:30] if (len(headlines) > 1 or ad.get("headline2")) else None,
                    headline3=(headlines[2] if len(headlines) > 2 else ad.get("headline3"))[:30] if (len(headlines) > 2 or ad.get("headline3")) else None,
                    description1=(descriptions[0] if len(descriptions) > 0 else ad.get("description1"))[:90] if (len(descriptions) > 0 or ad.get("description1")) else None,
                    description2=(descriptions[1] if len(descriptions) > 1 else ad.get("description2"))[:90] if (len(descriptions) > 1 or ad.get("description2")) else None,
                )
                db.session.add(ad_row)

            for kw in ag.get("keywords", []):
                kw_row = AdsKeyword(
                    ad_group_id=ag_row.id,
                    text=kw["text"],
                    match_type=(kw.get("match_type") or "EXACT").lower(),  # store as lower if you prefer
                    status=kw.get("status", "enabled"),
                    max_cpc_cents=kw.get("max_cpc_cents"),
                )
                db.session.add(kw_row)

            for neg in ag.get("negatives", []):
                n = NegativeKeyword(
                    scope="ad_group",
                    ad_group_id=ag_row.id,
                    text=neg["text"],
                    match_type=neg.get("match_type", "PHRASE"),
                )
                db.session.add(n)

        for list_id in payload.get("shared_negative_list_ids", []):
            db.session.add(SharedNegativeMap(list_id=list_id, campaign_id=campaign.id))

        db.session.commit()
        return jsonify({"status": "created", "campaign_id": campaign.id}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400
