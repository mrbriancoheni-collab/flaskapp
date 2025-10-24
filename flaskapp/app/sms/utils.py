# app/sms/utils.py
from __future__ import annotations
import os
from typing import Optional
from flask import current_app

try:
    from twilio.rest import Client  # optional
except Exception:
    Client = None  # allow running without twilio installed

def _twilio_client() -> Optional["Client"]:
    sid = os.getenv("TWILIO_ACCOUNT_SID")
    token = os.getenv("TWILIO_AUTH_TOKEN")
    if not (sid and token and Client):
        return None
    try:
        return Client(sid, token)
    except Exception:
        current_app.logger.exception("Twilio client init failed")
        return None

def send_sms(to: str, body: str) -> bool:
    """
    Sends SMS via Twilio if configured; otherwise logs and simulates success.
    Env needed: TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER
    """
    tw_from = os.getenv("TWILIO_FROM_NUMBER")
    client = _twilio_client()
    if client and tw_from:
        try:
            msg = client.messages.create(to=to, from_=tw_from, body=body)
            current_app.logger.info("Twilio SMS sent sid=%s to=%s", getattr(msg, "sid", "?"), to)
            return True
        except Exception:
            current_app.logger.exception("Twilio SMS send failed")
            return False

    # Fallback: simulate
    current_app.logger.warning("SMS simulated (Twilio not configured). to=%s body=%s", to, body[:200])
    return True
