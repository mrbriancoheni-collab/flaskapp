# app/routers/google_ads.py
import os, json
from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from urllib.parse import urlencode

from app.db import get_db
from app.models import GoogleAdsAuth, CampaignDraft, CampaignUpload
from app.services.crypto import encrypt, decrypt
from app.services.google_ads_service import (
    build_google_auth_url,
    exchange_code_for_refresh_token,
    client_from_refresh,
    create_everything_from_draft,
)

router = APIRouter()

@router.get("/connect", response_class=HTMLResponse)
def connect_get(request: Request, db: Session = Depends(get_db)):
    auth = db.query(GoogleAdsAuth).first()
    return request.app.templates.TemplateResponse("connect.html", {
        "request": request,
        "auth": auth,
        "developer_token_set": bool(os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN"))
    })

@router.get("/oauth/google-ads/start")
def oauth_start():
    return RedirectResponse(build_google_auth_url(), status_code=302)

@router.get("/oauth/google-ads/callback")
def oauth_callback(code: str, state: str = ""):
    refresh_token, login_customer_id = exchange_code_for_refresh_token(code)
    payload = urlencode({
        "refresh": encrypt(refresh_token),
        "login": login_customer_id or ""
    })
    return RedirectResponse(f"/connect?{payload}", status_code=302)

@router.post("/connect/save", response_class=HTMLResponse)
def connect_save(
    request: Request,
    customer_id: str = Form(...),
    refresh: str = Form(...),
    login: str = Form(""),
    db: Session = Depends(get_db),
):
    # store once per user (multi-user: scope by user_id)
    # Note: refresh comes encrypted from the form (encrypted in OAuth callback for URL security)
    # Decrypt it first, then use set_refresh_token() which will re-encrypt for storage
    plaintext_token = decrypt(refresh)

    auth = db.query(GoogleAdsAuth).first()
    if not auth:
        auth = GoogleAdsAuth(user_id=1, account_id=1, customer_id=customer_id, manager_customer_id=login or None)
        auth.set_refresh_token(plaintext_token)
    else:
        auth.customer_id = customer_id
        auth.set_refresh_token(plaintext_token)
        auth.manager_customer_id = login or None
    db.add(auth); db.commit()
    return RedirectResponse("/connect", status_code=303)

@router.post("/upload/{draft_id}")
def upload_draft(draft_id: int, db: Session = Depends(get_db)):
    draft = db.get(CampaignDraft, draft_id)
    if not draft or draft.status != "approved":
        raise HTTPException(400, "Draft must be approved before upload")

    auth = db.query(GoogleAdsAuth).first()
    if not auth:
        raise HTTPException(400, "Connect Google Ads first")

    client = client_from_refresh(
        refresh_token=auth.get_refresh_token(),
        login_cid=auth.manager_customer_id
    )

    resp = create_everything_from_draft(client, auth.customer_id, draft.draft_json)

    upload = CampaignUpload(user_id=draft.user_id, campaign_draft_id=draft.id, upload_status="success")
    db.add(upload); db.commit()

    draft.status = "uploaded"; db.add(draft); db.commit()
    return RedirectResponse("/connect", status_code=303)
