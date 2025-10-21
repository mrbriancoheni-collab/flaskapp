# app/pov/utils.py
from typing import Optional
from sqlalchemy import text
from app import db
from app.models_content import POVProfile
from flask import current_app

def get_account_id_from_session():
    # Mirrors your session pattern
    from flask import session as _s
    # We stored account_id in users table; fetch quickly if absent in session.
    acc = _s.get("account_id")
    if acc:
        return int(acc)
    try:
        uid = _s.get("user_id")
        if not uid:
            return None
        with db.engine.connect() as conn:
            row = conn.execute(text("SELECT account_id FROM users WHERE id=:id"), {"id": uid}).fetchone()
            return int(row[0]) if row else None
    except Exception:
        current_app.logger.exception("get_account_id_from_session failed")
        return None

def select_pov(account_id: int, site_id: Optional[int] = None, service_key: Optional[str] = None,
               prefer_id: Optional[int] = None) -> Optional[POVProfile]:
    """
    Selection order:
      1) prefer_id (if provided and active)
      2) service default (account+site+service_key, is_default=1)
      3) site default (account+site, is_default=1)
      4) global default (account, is_default=1)
      5) most recently updated active profile in that narrowest scope
    """
    q = POVProfile.query.filter_by(account_id=account_id, is_archived=False)

    if prefer_id:
        one = q.filter(POVProfile.id == prefer_id).first()
        if one:
            return one

    if site_id and service_key:
        one = q.filter_by(scope="service", site_id=site_id, service_key=(service_key or "").lower(), is_default=True).first()
        if one: return one
        one = q.filter_by(scope="service", site_id=site_id, service_key=(service_key or "").lower()).order_by(POVProfile.updated_at.desc()).first()
        if one: return one

    if site_id:
        one = q.filter_by(scope="site", site_id=site_id, is_default=True).first()
        if one: return one
        one = q.filter_by(scope="site", site_id=site_id).order_by(POVProfile.updated_at.desc()).first()
        if one: return one

    one = q.filter_by(scope="global", is_default=True).first()
    if one: return one

    return q.order_by(POVProfile.updated_at.desc()).first()
