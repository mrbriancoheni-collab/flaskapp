# app/routers/ui.py
from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from typing import Optional, List
import json

from app.db import get_db
from app.models import CompanyProfile, CampaignDraft
from app.services.llm_service import generate_pain_service_campaign
from app.services.export_service import draft_to_excel
from app.services.validation import validate_draft_no_broad

router = APIRouter()

@router.get("/builder", response_class=HTMLResponse)
def builder_get(request: Request, db: Session = Depends(get_db), profile_id: Optional[int] = None):
    profiles = db.query(CompanyProfile).all()
    draft = None
    if profile_id:
        draft = db.query(CampaignDraft).filter(
            CampaignDraft.profile_id == profile_id
        ).order_by(CampaignDraft.id.desc()).first()
    return request.app.templates.TemplateResponse("builder.html", {
        "request": request,
        "profiles": profiles,
        "active_profile_id": profile_id,
        "draft": draft,
    })

@router.post("/builder/generate", response_class=HTMLResponse)
def builder_generate(
    request: Request,
    profile_id: int = Form(...),
    top_n_services: int = Form(1),
    db: Session = Depends(get_db),
):
    profile = db.get(CompanyProfile, profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    # Rank/select top N services (uses profile.services with optional weights)
    services: List[str] = []
    if profile.services:
        svc_list = json.loads(profile.services) if isinstance(profile.services, str) else profile.services
        # naive ordering by optional 'priority' else original order
        ordered = sorted(svc_list, key=lambda s: s.get("priority", 0), reverse=True)
        services = [s["name"] if isinstance(s, dict) else s for s in ordered[:top_n_services]]

    draft_json = generate_pain_service_campaign(
        profile_dict=profile.as_public_dict(),  # implement on model
        services=services,
        match_types=["Phrase", "Exact"],
        adgroups_by_pain=True,
        max_headlines=15,
        max_descriptions=4,
    )
    validate_draft_no_broad(draft_json)

    draft = CampaignDraft(user_id=profile.user_id, profile_id=profile.id, draft_json=draft_json, status="draft")
    db.add(draft); db.commit(); db.refresh(draft)

    return RedirectResponse(url=f"/builder?profile_id={profile.id}", status_code=303)

@router.post("/builder/manual/add", response_class=HTMLResponse)
def builder_manual_add(
    request: Request,
    profile_id: int = Form(...),
    campaign_name: str = Form(...),
    adgroup_name: str = Form(...),
    match_type: str = Form("Exact"),
    keyword: str = Form(""),
    final_url: str = Form(""),
    db: Session = Depends(get_db),
):
    profile = db.get(CompanyProfile, profile_id)
    if not profile:
        raise HTTPException(404, "Profile not found")

    # Get or create current draft
    draft = db.query(CampaignDraft).filter(
        CampaignDraft.profile_id == profile_id, CampaignDraft.status == "draft"
    ).order_by(CampaignDraft.id.desc()).first()
    if not draft:
        draft = CampaignDraft(user_id=profile.user_id, profile_id=profile.id, draft_json={"campaigns": []}, status="draft")
        db.add(draft); db.commit(); db.refresh(draft)

    data = draft.draft_json
    # ensure campaign/ad group exist
    camp = next((c for c in data["campaigns"] if c["name"] == campaign_name), None)
    if not camp:
        camp = {"name": campaign_name, "type": "Search", "budget_per_day": 100, "locations": ["US"], "languages": ["English"], "bid_strategy": "MANUAL_CPC", "ad_groups": []}
        data["campaigns"].append(camp)
    ag = next((g for g in camp["ad_groups"] if g["name"] == adgroup_name), None)
    if not ag:
        ag = {"name": adgroup_name, "default_max_cpc": 2.0, "keywords": [], "rsas": [], "negatives": [], "extensions": {"sitelinks": []}}
        camp["ad_groups"].append(ag)

    if keyword:
        if match_type not in ("Phrase", "Exact"):
            raise HTTPException(400, "Only Phrase or Exact allowed")
        ag["keywords"].append({"text": keyword, "match": match_type, "final_url": final_url})

    validate_draft_no_broad(data)
    draft.draft_json = data
    db.add(draft); db.commit()

    return RedirectResponse(url=f"/builder?profile_id={profile.id}", status_code=303)

@router.get("/builder/export/{draft_id}")
def builder_export(draft_id: int, db: Session = Depends(get_db)):
    draft = db.get(CampaignDraft, draft_id)
    if not draft:
        raise HTTPException(404, "Draft not found")
    path = draft_to_excel(draft.draft_json, f"draft_{draft.id}.xlsx")
    return RedirectResponse(url=f"/download/local?path={path}", status_code=302)

@router.post("/builder/approve/{draft_id}")
def builder_approve(draft_id: int, db: Session = Depends(get_db)):
    draft = db.get(CampaignDraft, draft_id)
    if not draft:
        raise HTTPException(404, "Draft not found")
    draft.status = "approved"
    db.add(draft); db.commit()
    return RedirectResponse(url=f"/builder?profile_id={draft.profile_id}", status_code=303)
