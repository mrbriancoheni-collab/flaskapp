from __future__ import annotations
import os
from typing import Dict, Any
from flask import Blueprint, request, Response, current_app

import requests

telephony_bp = Blueprint("telephony_bp", __name__)

def _twilio_creds():
    sid = os.getenv("TWILIO_ACCOUNT_SID")
    tok = os.getenv("TWILIO_AUTH_TOKEN")
    from_num = os.getenv("TWILIO_FROM_NUMBER")
    if sid and tok and from_num:
        return {"sid": sid, "token": tok, "from": from_num}
    return None

def _twiml(xml: str) -> Response:
    return Response(xml, status=200, mimetype="text/xml")

@telephony_bp.route("/twilio/voice", methods=["POST"])
def twilio_voice():
    """
    Basic inbound call flow:
      - tries to dial your business number (TWILIO_FORWARD_TO)
      - sets a StatusCallback to /telephony/twilio/status
    """
    forward_to = os.getenv("TWILIO_FORWARD_TO")  # e.g., +14155550100
    status_cb = os.getenv("BASE_PUBLIC_URL", "").rstrip("/") + "/telephony/twilio/status"

    if not forward_to:
        # fallback: simple voicemail-ish message
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="alice">Thanks for calling. We’ll be right with you.</Say>
  <Pause length="1"/>
  <Say voice="alice">Please leave a message after the tone.</Say>
  <Record maxLength="120" playBeep="true"/>
</Response>"""
        return _twiml(xml)

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Dial action="{status_cb}" method="POST" timeout="20">
    <Number statusCallback="{status_cb}" statusCallbackEvent="answered completed no-answer busy failed" statusCallbackMethod="POST">{forward_to}</Number>
  </Dial>
  <Say voice="alice">Sorry, we couldn’t connect your call.</Say>
</Response>"""
    return _twiml(xml)

@telephony_bp.route("/twilio/status", methods=["POST"])
def twilio_status():
    """
    If call not answered, send a quick SMS follow-up (“missed call textback”).
    """
    creds = _twilio_creds()
    to_number = request.form.get("From")
    call_status = (request.form.get("CallStatus") or "").lower()
    current_app.logger.info("Twilio status: %s -> %s", to_number, call_status)

    if call_status in ("no-answer", "busy", "failed"):
        body = os.getenv("MISSED_CALL_SMS", "Sorry we missed your call—text us here and we’ll help right away.")
        if creds and to_number:
            try:
                sid, tok, from_num = creds["sid"], creds["token"], creds["from"]
                url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
                requests.post(url, data={"From": from_num, "To": to_number, "Body": body}, auth=(sid, tok), timeout=10)
            except Exception:
                current_app.logger.exception("Missed-call SMS failed")
        else:
            # simulate
            current_app.logger.info("Simulated missed-call SMS to %s: %s", to_number, body)

    # Twilio expects 200 OK with any body
    return ("", 200)
