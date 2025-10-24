# app/services/validation.py
def validate_draft_no_broad(draft: dict):
    for c in draft.get("campaigns", []):
        for g in c.get("ad_groups", []):
            for kw in g.get("keywords", []):
                if kw.get("match") not in ("Phrase","Exact"):
                    raise ValueError(f"Only Phrase/Exact allowed: {kw}")
