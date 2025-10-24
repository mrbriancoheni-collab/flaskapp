# app/maps/utils.py
from __future__ import annotations
import json, re
from typing import List
from sqlalchemy import text
from app import db

def get_service_zipcodes(account_id: int) -> List[str]:
    row = db.session.execute(
        text("SELECT service_zipcodes FROM account_settings WHERE account_id=:aid"),
        {"aid": account_id},
    ).fetchone()
    if not row or not row[0]:
        return []
    val = row[0]
    try:
        data = json.loads(val)
        if isinstance(data, list):
            return [str(z).strip() for z in data if str(z).strip()]
    except Exception:
        pass
    parts = re.split(r"[,\s]+", val)
    return [p.strip() for p in parts if p.strip()]

def set_service_zipcodes(account_id: int, zips: List[str]) -> None:
    payload = json.dumps(sorted(set([z.strip() for z in zips if z.strip()])))
    db.session.execute(
        text("""
            INSERT INTO account_settings (account_id, service_zipcodes)
            VALUES (:aid, :val)
            ON DUPLICATE KEY UPDATE service_zipcodes=:val
        """),
        {"aid": account_id, "val": payload},
    )
    db.session.commit()
