# app/services/skimmer_sync.py
"""
Skimmer CRM sync service.

Functions:
  normalize_phone         — normalise a raw phone string to E.164
  sync_completed_jobs     — pull completed work orders from Skimmer API
  match_jobs_to_gclids    — link jobs to Google click IDs via PhoneGclidMap
  push_job_conversions    — upload matched jobs as offline conversions to Google Ads
  send_review_requests    — email post-service review requests to customers
  run_full_sync           — run all four steps in order
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_COMPLETED_STATUSES = {"completed", "invoiced", "paid"}

_DEFAULT_REVIEW_TEMPLATE = (
    "Hi {customer_name},\n\n"
    "Thank you for letting us take care of your pool! We'd love to hear about "
    "your experience — a quick review means the world to small businesses like ours.\n\n"
    "Leave us a review here: [Leave a Review]\n\n"
    "Thanks again,\n{business_name}"
)


# ---------------------------------------------------------------------------
# A. normalize_phone
# ---------------------------------------------------------------------------

def normalize_phone(phone: str) -> Optional[str]:
    """
    Normalise a raw phone string to E.164 (+1XXXXXXXXXX for US numbers).

    Returns None if the number cannot be normalised.
    """
    if not phone:
        return None
    # Strip everything except digits
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits[0] == "1":
        return f"+{digits}"
    return None


# ---------------------------------------------------------------------------
# B. sync_completed_jobs
# ---------------------------------------------------------------------------

def sync_completed_jobs(account_id: int) -> dict:
    """
    Pull completed work orders from the Skimmer API and upsert them into SkimmerJob.

    Returns {"synced": N, "new": N, "errors": []}.
    """
    from app import db
    from app.models_skimmer import SkimmerAuth, SkimmerJob
    from app.services.skimmer_client import client_from_account

    result: Dict[str, Any] = {"synced": 0, "new": 0, "errors": []}

    # Load auth record
    try:
        auth = SkimmerAuth.query.filter_by(account_id=account_id).first()
        if not auth:
            result["errors"].append("No Skimmer auth configured for this account.")
            return result
    except Exception as exc:
        result["errors"].append(f"DB error loading SkimmerAuth: {exc}")
        return result

    # Build client
    client = client_from_account(account_id)
    if client is None:
        result["errors"].append("Could not create Skimmer client — API key missing or invalid.")
        return result

    # Determine sync window
    if auth.last_synced_at is None:
        since = datetime.utcnow() - timedelta(days=7)
    else:
        since = auth.last_synced_at - timedelta(hours=1)

    since_iso = since.strftime("%Y-%m-%dT%H:%M:%S")

    # Fetch work orders from Skimmer
    try:
        work_orders = client.get_work_orders(status="completed", completed_after=since_iso)
    except Exception as exc:
        result["errors"].append(f"Skimmer API error: {exc}")
        return result

    for wo in work_orders:
        try:
            raw_status = (wo.get("status") or "").lower().strip()
            if raw_status not in _COMPLETED_STATUSES:
                continue

            job_id = str(wo.get("id") or wo.get("work_order_id") or "").strip()
            if not job_id:
                continue

            # Normalise phone
            raw_phone = (
                wo.get("customer_phone")
                or wo.get("phone")
                or (wo.get("customer") or {}).get("phone")
                or ""
            )
            phone_e164 = normalize_phone(raw_phone) if raw_phone else None

            # Parse completed_at
            completed_at_raw = wo.get("completed_at") or wo.get("completed_date")
            completed_at: Optional[datetime] = None
            if completed_at_raw:
                for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                    try:
                        completed_at = datetime.strptime(
                            str(completed_at_raw).split("+")[0].split("Z")[0].strip(), fmt
                        )
                        break
                    except ValueError:
                        continue

            # Invoice total in cents
            invoice_raw = wo.get("invoice_total") or wo.get("total") or wo.get("amount")
            invoice_cents: Optional[int] = None
            if invoice_raw is not None:
                try:
                    invoice_cents = int(float(invoice_raw) * 100)
                except (TypeError, ValueError):
                    pass

            # Customer fields
            customer = wo.get("customer") or {}
            customer_name = (
                wo.get("customer_name")
                or customer.get("name")
                or f"{customer.get('first_name', '')} {customer.get('last_name', '')}".strip()
                or None
            )
            customer_email = (
                wo.get("customer_email")
                or customer.get("email")
                or None
            )
            customer_id = str(
                wo.get("customer_id") or customer.get("id") or ""
            ).strip() or None

            service_address = (
                wo.get("service_address")
                or wo.get("address")
                or (wo.get("service_location") or {}).get("address")
                or None
            )
            service_type = wo.get("service_type") or wo.get("job_type") or None

            # Upsert
            existing = SkimmerJob.query.filter_by(
                account_id=account_id,
                skimmer_job_id=job_id,
            ).first()

            is_new = existing is None
            job = existing or SkimmerJob(
                account_id=account_id,
                skimmer_job_id=job_id,
            )

            job.skimmer_customer_id = customer_id
            job.customer_name = customer_name
            job.customer_email = customer_email
            job.customer_phone = raw_phone or None
            job.customer_phone_e164 = phone_e164
            job.service_address = service_address
            job.service_type = service_type
            job.status = raw_status
            if completed_at:
                job.completed_at = completed_at
            if invoice_cents is not None:
                job.invoice_total_cents = invoice_cents
            job.raw_json = json.dumps(wo)

            if is_new:
                db.session.add(job)
                result["new"] += 1

            result["synced"] += 1

        except Exception as exc:
            logger.exception("Error processing work order %s for account %s", wo, account_id)
            result["errors"].append(str(exc))

    # Persist and update last_synced_at
    try:
        auth.last_synced_at = datetime.utcnow()
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.exception("DB commit failed in sync_completed_jobs account %s", account_id)
        result["errors"].append(f"DB commit error: {exc}")

    return result


# ---------------------------------------------------------------------------
# C. match_jobs_to_gclids
# ---------------------------------------------------------------------------

def match_jobs_to_gclids(account_id: int) -> dict:
    """
    For SkimmerJob rows without a matched_gclid, look up PhoneGclidMap and populate.

    Returns {"matched": N, "unmatched": N}.
    """
    from app import db
    from app.models_skimmer import SkimmerJob, PhoneGclidMap

    result: Dict[str, Any] = {"matched": 0, "unmatched": 0}

    try:
        jobs = (
            SkimmerJob.query
            .filter(
                SkimmerJob.account_id == account_id,
                SkimmerJob.matched_gclid.is_(None),
                SkimmerJob.customer_phone_e164.isnot(None),
            )
            .all()
        )
    except Exception as exc:
        logger.exception("match_jobs_to_gclids query failed for account %s", account_id)
        return {"matched": 0, "unmatched": 0, "error": str(exc)}

    now = datetime.utcnow()
    for job in jobs:
        try:
            mapping = (
                PhoneGclidMap.query
                .filter_by(account_id=account_id, phone_e164=job.customer_phone_e164)
                .filter(PhoneGclidMap.expires_at > now)
                .order_by(PhoneGclidMap.created_at.desc())
                .first()
            )
            if mapping:
                job.matched_gclid = mapping.gclid
                result["matched"] += 1
            else:
                result["unmatched"] += 1
        except Exception as exc:
            logger.warning("Error matching job %s: %s", job.id, exc)
            result["unmatched"] += 1

    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.exception("DB commit failed in match_jobs_to_gclids account %s", account_id)

    return result


# ---------------------------------------------------------------------------
# D. push_job_conversions
# ---------------------------------------------------------------------------

def push_job_conversions(account_id: int) -> dict:
    """
    For SkimmerJob rows with a matched_gclid but no offline conversion yet,
    create OfflineConversionImport rows and upload them.

    Returns {"pushed": N, "errors": []}.
    """
    from app import db
    from app.models_skimmer import SkimmerJob
    from app.models_ads import OfflineConversionImport
    from app.services.google_ads_offline_conversions import upload_pending_conversions

    result: Dict[str, Any] = {"pushed": 0, "errors": []}

    try:
        jobs = (
            SkimmerJob.query
            .filter(
                SkimmerJob.account_id == account_id,
                SkimmerJob.matched_gclid.isnot(None),
                SkimmerJob.offline_conv_pushed_at.is_(None),
            )
            .all()
        )
    except Exception as exc:
        logger.exception("push_job_conversions query failed for account %s", account_id)
        result["errors"].append(str(exc))
        return result

    for job in jobs:
        try:
            conversion_value = (
                job.invoice_total_cents / 100.0
                if job.invoice_total_cents is not None
                else 0.0
            )
            oci = OfflineConversionImport(
                account_id=account_id,
                source="skimmer",
                external_id=job.skimmer_job_id,
                gclid=job.matched_gclid,
                conversion_name="Completed Pool Service Job",
                conversion_time=job.completed_at,
                conversion_value=conversion_value,
                currency_code="USD",
                status="pending",
            )
            db.session.add(oci)
            db.session.flush()
        except Exception as exc:
            logger.exception("Error creating OfflineConversionImport for job %s", job.id)
            result["errors"].append(f"Job {job.skimmer_job_id}: {exc}")

    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.exception("DB commit failed creating OCI rows for account %s", account_id)
        result["errors"].append(f"DB commit error: {exc}")
        return result

    # Upload to Google Ads
    try:
        upload_result = upload_pending_conversions(account_id)
        upload_errors = upload_result.get("errors", [])
    except Exception as exc:
        logger.exception("upload_pending_conversions failed for account %s", account_id)
        upload_errors = [str(exc)]

    # Mark jobs based on upload result
    now = datetime.utcnow()
    try:
        jobs_refetch = (
            SkimmerJob.query
            .filter(
                SkimmerJob.account_id == account_id,
                SkimmerJob.matched_gclid.isnot(None),
                SkimmerJob.offline_conv_pushed_at.is_(None),
            )
            .all()
        )
        for job in jobs_refetch:
            # Check matching OCI record status
            oci_row = OfflineConversionImport.query.filter_by(
                account_id=account_id,
                source="skimmer",
                external_id=job.skimmer_job_id,
            ).order_by(OfflineConversionImport.created_at.desc()).first()

            if oci_row:
                job.offline_conv_pushed_at = now
                job.offline_conv_status = oci_row.status if oci_row.status in ("uploaded", "failed") else "uploaded"
                if oci_row.status != "failed":
                    result["pushed"] += 1
            else:
                job.offline_conv_pushed_at = now
                job.offline_conv_status = "failed"

        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.exception("Error updating job conv status for account %s", account_id)
        result["errors"].append(str(exc))

    if upload_errors:
        result["errors"].extend(upload_errors)

    return result


# ---------------------------------------------------------------------------
# E. send_review_requests
# ---------------------------------------------------------------------------

def send_review_requests(account_id: int) -> dict:
    """
    Send post-service review request emails for completed jobs where:
    - review_sent_at is NULL
    - customer_email is set
    - completed_at < now - delay_hours

    Returns {"sent": N, "errors": []}.
    """
    from app import db
    from app.models_skimmer import SkimmerAuth, SkimmerJob
    from app.models import Account
    from app.emailer import send_mail

    result: Dict[str, Any] = {"sent": 0, "errors": []}

    try:
        auth = SkimmerAuth.query.filter_by(account_id=account_id).first()
        if not auth:
            result["errors"].append("No Skimmer auth configured for this account.")
            return result
        if not auth.review_requests_enabled:
            return result
    except Exception as exc:
        result["errors"].append(f"DB error loading SkimmerAuth: {exc}")
        return result

    delay_hours = auth.review_request_delay_hours or 24
    cutoff = datetime.utcnow() - timedelta(hours=delay_hours)

    try:
        jobs = (
            SkimmerJob.query
            .filter(
                SkimmerJob.account_id == account_id,
                SkimmerJob.status.in_(list(_COMPLETED_STATUSES)),
                SkimmerJob.review_sent_at.is_(None),
                SkimmerJob.customer_email.isnot(None),
                SkimmerJob.completed_at < cutoff,
            )
            .all()
        )
    except Exception as exc:
        logger.exception("send_review_requests query failed for account %s", account_id)
        result["errors"].append(str(exc))
        return result

    # Load account name
    try:
        account = Account.query.get(account_id)
        business_name = account.name if account else "Your Pool Service"
    except Exception:
        business_name = "Your Pool Service"

    template = auth.review_request_template or _DEFAULT_REVIEW_TEMPLATE

    for job in jobs:
        try:
            customer_name = job.customer_name or "Valued Customer"
            body = template.format(
                customer_name=customer_name,
                business_name=business_name,
            )
            subject = f"How did we do? — {business_name}"
            send_mail(
                to=job.customer_email,
                subject=subject,
                text=body,
            )
            job.review_sent_at = datetime.utcnow()
            result["sent"] += 1
        except Exception as exc:
            logger.warning(
                "Failed to send review request for job %s to %s: %s",
                job.skimmer_job_id, job.customer_email, exc,
            )
            result["errors"].append(
                f"Job {job.skimmer_job_id} ({job.customer_email}): {exc}"
            )

    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.exception("DB commit failed in send_review_requests account %s", account_id)
        result["errors"].append(f"DB commit error: {exc}")

    return result


# ---------------------------------------------------------------------------
# F. run_full_sync
# ---------------------------------------------------------------------------

def run_full_sync(account_id: int) -> dict:
    """
    Run all sync steps in order:
      1. sync_completed_jobs
      2. match_jobs_to_gclids
      3. push_job_conversions
      4. send_review_requests

    Returns a combined result dict.
    """
    combined: Dict[str, Any] = {}

    sync_result = sync_completed_jobs(account_id)
    combined["sync"] = sync_result

    match_result = match_jobs_to_gclids(account_id)
    combined["match"] = match_result

    push_result = push_job_conversions(account_id)
    combined["push"] = push_result

    review_result = send_review_requests(account_id)
    combined["reviews"] = review_result

    # Flatten top-level error list for convenience
    all_errors = (
        sync_result.get("errors", [])
        + push_result.get("errors", [])
        + review_result.get("errors", [])
    )
    combined["errors"] = all_errors
    combined["ok"] = len(all_errors) == 0

    return combined
