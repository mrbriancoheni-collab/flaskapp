# app/services/export_service.py
import pandas as pd
from pathlib import Path

def _rows_from_draft(draft: dict):
    campaigns, ad_groups, keywords, rsas, negatives, sitelinks = [], [], [], [], [], []
    for c in draft.get("campaigns", []):
        campaigns.append({
            "Campaign": c["name"],
            "Campaign State": "enabled",
            "Campaign Type": c.get("type","Search"),
            "Budget": c.get("budget_per_day", 100),
            "Budget Type": "Daily",
            "Networks": "Google; Search Partners",
            "Location": "; ".join(c.get("locations", [])),
            "Languages": "; ".join(c.get("languages", [])),
            "Bid Strategy Type": c.get("bid_strategy","MANUAL_CPC")
        })
        for g in c.get("ad_groups", []):
            ad_groups.append({
                "Campaign": c["name"],
                "Ad Group": g["name"],
                "Ad Group State": "enabled",
                "Default Max CPC": g.get("default_max_cpc", 1.5),
            })
            for kw in g.get("keywords", []):
                keywords.append({
                    "Campaign": c["name"],
                    "Ad Group": g["name"],
                    "Keyword": kw["text"],
                    "Criterion Type": kw["match"],  # "Phrase" or "Exact"
                    "Final URL": kw.get("final_url","")
                })
            for ad in g.get("rsas", []):
                row = {"Campaign": c["name"], "Ad Group": g["name"], "Ad State": "enabled", "Final URL": ad.get("final_url","")}
                if "paths" in ad:
                    if len(ad["paths"]) > 0: row["Path 1"] = ad["paths"][0]
                    if len(ad["paths"]) > 1: row["Path 2"] = ad["paths"][1]
                for i, h in enumerate(ad.get("headlines", [])[:15], 1):
                    row[f"Headline {i}"] = h
                for i, d in enumerate(ad.get("descriptions", [])[:4], 1):
                    row[f"Description {i}"] = d
                rsas.append(row)
            for neg in g.get("negatives", []):
                negatives.append({
                    "Campaign": c["name"],
                    "Ad Group": g["name"],
                    "Keyword": neg["text"],
                    "Match Type": neg.get("match","Broad")
                })
            for sl in g.get("extensions", {}).get("sitelinks", []):
                sitelinks.append({
                    "Campaign": c["name"],
                    "Ad Group": "",
                    "Extension": "Sitelink",
                    "Link Text": sl["text"],
                    "Final URL": sl.get("final_url",""),
                    "Description Line 1": sl.get("desc1",""),
                    "Description Line 2": sl.get("desc2","")
                })
    return campaigns, ad_groups, keywords, rsas, negatives, sitelinks

def draft_to_excel(draft: dict, filename: str) -> str:
    c, ag, kw, ads, neg, sl = _rows_from_draft(draft)
    out = Path("/mnt/data") / filename
    with pd.ExcelWriter(out, engine="xlsxwriter") as w:
        pd.DataFrame(c).to_excel(w, "Campaigns", index=False)
        pd.DataFrame(ag).to_excel(w, "AdGroups", index=False)
        pd.DataFrame(kw).to_excel(w, "Keywords", index=False)
        pd.DataFrame(ads).to_excel(w, "RSAs", index=False)
        pd.DataFrame(neg).to_excel(w, "Negatives", index=False)
        pd.DataFrame(sl).to_excel(w, "Extensions", index=False)
    return str(out)
