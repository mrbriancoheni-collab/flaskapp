#!/usr/bin/env python3
"""Apply migration 024: add bid_strategy, target_cpa_micros, target_roas to ads_campaigns"""
import sys
sys.path.insert(0, '/home/user/flaskapp/flaskapp')

from app import create_app, db
from sqlalchemy import text, inspect

app = create_app()
with app.app_context():
    insp = inspect(db.engine)
    existing = {c['name'] for c in insp.get_columns('ads_campaigns')}
    
    additions = [
        ("bid_strategy",      "VARCHAR(32) NULL DEFAULT 'manual_cpc'"),
        ("target_cpa_micros", "BIGINT NULL"),
        ("target_roas",       "FLOAT NULL"),
    ]
    
    for col, defn in additions:
        if col in existing:
            print(f"  SKIP  {col} already exists")
        else:
            db.session.execute(text(f"ALTER TABLE ads_campaigns ADD COLUMN {col} {defn}"))
            print(f"  ADDED {col}")
    
    db.session.commit()
    print("Done.")
