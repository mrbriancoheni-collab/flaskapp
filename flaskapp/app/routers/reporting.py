# app/routers/reporting.py
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from datetime import date, timedelta

from app.db import get_db
from app.models import PerformanceSnapshot, Suggestions, GoogleAdsAuth
from app.services.google_ads_service import client_from_refresh, fetch_kpis, apply_suggestion
from app.services.crypto import decrypt
from app.services.suggestions import generate_suggestions_from_metrics

router = APIRouter()

@router.get("/results", response_class=HTMLResponse)
def results_get(request: Request, db: Session = Depends(get_db)):
    snaps = db.query(PerformanceSnapshot).order_by(PerformanceSnapshot.as_of_date.desc()).limit(30).all()
    suggs = db.query(Suggestions).order_by(Suggestions.id.desc()).limit(50).all()
    return request.app.templates.TemplateResponse("results.html", {
        "request": request,
        "snapshots": snaps,
        "suggestions": suggs
    })

@router.post("/results/pull")
def results_pull(db: Session = Depends(get_db)):
    auth = db.query(GoogleAdsAuth).first()
    client = client_from_refresh(auth.get_refresh_token(), auth.manager_customer_id)
    metrics = fetch_kpis(client, auth.customer_id, days=14)
    # save snapshot
    snap = PerformanceSnapshot(user_id=auth.user_id, customer_id=auth.customer_id, as_of_date=date.today(), metrics=metrics)
    db.add(snap); db.commit()
    return RedirectResponse("/results", status_code=303)

@router.post("/results/suggest")
def results_suggest(db: Session = Depends(get_db)):
    snap = db.query(PerformanceSnapshot).order_by(PerformanceSnapshot.id.desc()).first()
    recs = generate_suggestions_from_metrics(snap.metrics)
    s = Suggestions(user_id=snap.user_id, snapshot_id=snap.id, suggestion_json=recs)
    db.add(s); db.commit()
    return RedirectResponse("/results", status_code=303)

@router.post("/results/suggestions/apply/{suggestion_id}")
def results_apply(suggestion_id: int, db: Session = Depends(get_db)):
    auth = db.query(GoogleAdsAuth).first()
    s = db.get(Suggestions, suggestion_id)
    client = client_from_refresh(auth.get_refresh_token(), auth.manager_customer_id)
    apply_suggestion(client, auth.customer_id, s.suggestion_json)
    s.accepted = True
    db.add(s); db.commit()
    return RedirectResponse("/results", status_code=303)
