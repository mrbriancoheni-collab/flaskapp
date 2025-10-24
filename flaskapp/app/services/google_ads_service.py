# app/services/google_ads_service.py
import os
from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException
from datetime import date, timedelta

AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/adwords"

def build_google_auth_url():
    params = {
        "client_id": os.getenv("GOOGLE_ADS_CLIENT_ID"),
        "redirect_uri": os.getenv("GOOGLE_ADS_REDIRECT_URI"),
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent"
    }
    from urllib.parse import urlencode
    return f"{AUTH_URI}?{urlencode(params)}"

def exchange_code_for_refresh_token(code: str):
    import requests
    data = {
        "client_id": os.getenv("GOOGLE_ADS_CLIENT_ID"),
        "client_secret": os.getenv("GOOGLE_ADS_CLIENT_SECRET"),
        "redirect_uri": os.getenv("GOOGLE_ADS_REDIRECT_URI"),
        "grant_type": "authorization_code",
        "code": code,
    }
    r = requests.post(TOKEN_URI, data=data)
    r.raise_for_status()
    payload = r.json()
    # login_customer_id is chosen later (MCC); return None here
    return payload["refresh_token"], None

def client_from_refresh(refresh_token: str, login_cid: str | None):
    cfg = {
        "developer_token": os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN"),
        "client_id": os.getenv("GOOGLE_ADS_CLIENT_ID"),
        "client_secret": os.getenv("GOOGLE_ADS_CLIENT_SECRET"),
        "refresh_token": refresh_token,
        "login_customer_id": login_cid,
        "use_proto_plus": True
    }
    return GoogleAdsClient.load_from_dict(cfg)

# -------------------- Upload --------------------
def create_everything_from_draft(client: GoogleAdsClient, customer_id: str, draft: dict):
    ga_service = client.get_service("GoogleAdsService")

    ops = []
    res_index = {"budget": {}, "campaign": {}, "adgroup": {}}
    tmp_id = -1

    # 1) Budgets & Campaigns
    budget_svc = client.get_service("CampaignBudgetService")
    campaign_svc = client.get_service("CampaignService")
    for c in draft.get("campaigns", []):
        budget = client.get_type("CampaignBudget")
        budget.resource_name = budget_svc.campaign_budget_path(customer_id, str(abs(tmp_id)))
        budget.name = f"{c['name']} Budget"
        budget.amount_micros = int(c.get("budget_per_day", 100) * 1_000_000)
        budget.delivery_method = client.enums.BudgetDeliveryMethodEnum.STANDARD
        op = client.get_type("CampaignBudgetOperation")
        op.create.CopyFrom(budget)
        ops.append(client.get_type("MutateOperation", version="v17"))
        ops[-1].campaign_budget_operation.CopyFrom(op)
        res_index["budget"][c["name"]] = budget.resource_name

        campaign = client.get_type("Campaign")
        campaign.resource_name = campaign_svc.campaign_path(customer_id, str(abs(tmp_id-1)))
        campaign.name = c["name"]
        campaign.advertising_channel_type = client.enums.AdvertisingChannelTypeEnum.SEARCH
        campaign.status = client.enums.CampaignStatusEnum.PAUSED
        campaign.campaign_budget = budget.resource_name
        # (Optional) networks, languages, locations handled via criteria later if needed
        cop = client.get_type("CampaignOperation")
        cop.create.CopyFrom(campaign)
        ops.append(client.get_type("MutateOperation", version="v17"))
        ops[-1].campaign_operation.CopyFrom(cop)

        res_index["campaign"][c["name"]] = campaign.resource_name
        tmp_id -= 2

    # 2) Ad Groups
    adgroup_svc = client.get_service("AdGroupService")
    for c in draft.get("campaigns", []):
        for g in c.get("ad_groups", []):
            ag = client.get_type("AdGroup")
            ag.resource_name = adgroup_svc.ad_group_path(customer_id, str(abs(tmp_id)))
            ag.name = g["name"]
            ag.campaign = res_index["campaign"][c["name"]]
            ag.status = client.enums.AdGroupStatusEnum.ENABLED
            ag.cpc_bid_micros = int(g.get("default_max_cpc", 2.0) * 1_000_000)
            agop = client.get_type("AdGroupOperation")
            agop.create.CopyFrom(ag)
            ops.append(client.get_type("MutateOperation", version="v17"))
            ops[-1].ad_group_operation.CopyFrom(agop)
            res_index["adgroup"][(c["name"], g["name"])] = ag.resource_name
            tmp_id -= 1

    # 3) Keywords
    agc_svc = client.get_service("AdGroupCriterionService")
    for c in draft.get("campaigns", []):
        for g in c.get("ad_groups", []):
            for kw in g.get("keywords", []):
                match = kw["match"]
                if match not in ("Phrase","Exact"):
                    raise ValueError("Only Phrase/Exact allowed")
                crit = client.get_type("AdGroupCriterion")
                crit.ad_group = res_index["adgroup"][(c["name"], g["name"])]
                crit.status = client.enums.AdGroupCriterionStatusEnum.ENABLED
                crit.keyword.text = kw["text"]
                crit.keyword.match_type = (client.enums.KeywordMatchTypeEnum.PHRASE if match=="Phrase"
                                           else client.enums.KeywordMatchTypeEnum.EXACT)
                op = client.get_type("AdGroupCriterionOperation")
                op.create.CopyFrom(crit)
                mo = client.get_type("MutateOperation", version="v17")
                mo.ad_group_criterion_operation.CopyFrom(op)
                ops.append(mo)

    # 4) RSAs
    ad_svc = client.get_service("AdGroupAdService")
    for c in draft.get("campaigns", []):
        for g in c.get("ad_groups", []):
            for ad in g.get("rsas", []):
                aga = client.get_type("AdGroupAd")
                aga.ad_group = res_index["adgroup"][(c["name"], g["name"])]
                aga.status = client.enums.AdGroupAdStatusEnum.PAUSED
                # build RSA
                adu = client.get_type("Ad")
                adu.final_urls.append(ad.get("final_url",""))
                if ad.get("paths"):
                    if len(ad["paths"]) > 0: adu.path1 = ad["paths"][0]
                    if len(ad["paths"]) > 1: adu.path2 = ad["paths"][1]
                adu.responsive_search_ad.headlines.extend(
                    [client.get_type("AdTextAsset", version="v17")(text=h) for h in ad.get("headlines", [])[:15]]
                )
                adu.responsive_search_ad.descriptions.extend(
                    [client.get_type("AdTextAsset", version="v17")(text=d) for d in ad.get("descriptions", [])[:4]]
                )
                aga.ad.CopyFrom(adu)
                agop = client.get_type("AdGroupAdOperation")
                agop.create.CopyFrom(aga)
                mo = client.get_type("MutateOperation", version="v17")
                mo.ad_group_ad_operation.CopyFrom(agop)
                ops.append(mo)

    # Execute batch mutate
    try:
        response = ga_service.mutate(customer_id=customer_id, mutate_operations=ops)
        return response
    except GoogleAdsException as e:
        raise RuntimeError(str(e.failure))

# -------------------- KPIs --------------------
def fetch_kpis(client: GoogleAdsClient, customer_id: str, days: int = 14):
    ga_service = client.get_service("GoogleAdsService")
    query = f"""
        SELECT
          campaign.name, ad_group.name,
          metrics.impressions, metrics.clicks, metrics.cost_micros,
          metrics.conversions, metrics.conversions_value, metrics.ctr, metrics.average_cpc
        FROM ad_group
        WHERE segments.date >= '{(date.today()-timedelta(days=days)).isoformat()}'
          AND segments.date <= '{date.today().isoformat()}'
    """
    rows = ga_service.search(customer_id=customer_id, query=query)
    out = []
    for r in rows:
        out.append({
            "campaign": r.campaign.name,
            "ad_group": r.ad_group.name,
            "impr": r.metrics.impressions,
            "clicks": r.metrics.clicks,
            "cost": r.metrics.cost_micros/1_000_000.0,
            "conv": r.metrics.conversions,
            "conv_value": r.metrics.conversions_value,
            "ctr": r.metrics.ctr,
            "avg_cpc": r.metrics.average_cpc/1_000_000.0 if r.metrics.average_cpc else 0
        })
    return out

# -------------------- Suggestions apply (stub) --------------------
def apply_suggestion(client: GoogleAdsClient, customer_id: str, suggestion_json: dict):
    """
    Translate suggestion_json actions (e.g., add negative, pause keyword, add RSA asset)
    into mutate operations and execute. Keep this mapping tight & audited.
    """
    # Implement action handlers here (out of scope for brevity).
    pass
