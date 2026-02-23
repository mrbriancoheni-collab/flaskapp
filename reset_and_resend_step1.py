#!/usr/bin/env python3
"""
Reset all lead-generation email state and immediately resend step-1 emails
to every eligible contact.

What this does
--------------
1. RESET — for every campaign:
   - Deletes all LeadContactEmail tracking records
   - Deletes all LeadEmail (legacy) tracking records
   - Resets LeadContact.email_status → 'pending' and current_sequence_step → 0
   - Resets Lead.email_status → 'pending', current_sequence_step → 0,
     last_email_sent_at → NULL
   - Sets any 'completed' campaign back to 'sending'

2. RESEND — calls send_to_all_unsent_ever(sequence_step=1) which sends the
   first sequence email to every contact that hasn't already received it
   (after the reset above, that is everyone).

Usage
-----
    # Dry-run first — shows counts, sends nothing
    python3 reset_and_resend_step1.py --dry-run

    # Live run
    python3 reset_and_resend_step1.py
"""

import sys
import os
from datetime import datetime

# ── Path / env setup (same as passenger_wsgi.py) ─────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "flaskapp"))

env_file = os.path.join(os.path.dirname(__file__), "flaskapp", ".env")
if os.path.exists(env_file):
    with open(env_file) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

DRY_RUN = "--dry-run" in sys.argv


def main():
    from app import create_app
    from app.extensions import db
    from app.models_leads import (
        LeadCampaign, Lead, LeadContact, LeadContactEmail, LeadEmail
    )
    from app.services.lead_automation_service import LeadAutomationService

    app = create_app()

    with app.app_context():
        print("=" * 70)
        print("LEAD EMAIL RESET + STEP-1 RESEND")
        print(f"Mode : {'DRY RUN (nothing will change)' if DRY_RUN else 'LIVE'}")
        print(f"Time : {datetime.utcnow().isoformat()} UTC")
        print("=" * 70)

        # ── 1. Current state snapshot ─────────────────────────────────────────
        lce_total   = LeadContactEmail.query.count()
        le_total    = LeadEmail.query.count()
        contacts    = LeadContact.query.count()
        c_sent      = LeadContact.query.filter_by(email_status="sent").count()
        c_pending   = LeadContact.query.filter_by(email_status="pending").count()
        leads_total = Lead.query.count()
        campaigns   = LeadCampaign.query.all()

        print(f"\nBEFORE RESET:")
        print(f"  Campaigns              : {len(campaigns)}")
        print(f"  LeadContactEmail rows  : {lce_total}")
        print(f"  LeadEmail rows (legacy): {le_total}")
        print(f"  LeadContacts total     : {contacts}")
        print(f"    - sent               : {c_sent}")
        print(f"    - pending            : {c_pending}")
        print(f"  Leads total            : {leads_total}")

        print(f"\n{'[DRY RUN] ' if DRY_RUN else ''}Proceeding with reset...")

        if not DRY_RUN:
            # ── 2. Delete all tracking records ────────────────────────────────
            deleted_lce = LeadContactEmail.query.delete(synchronize_session=False)
            deleted_le  = LeadEmail.query.delete(synchronize_session=False)
            db.session.flush()

            # ── 3. Reset LeadContact state ────────────────────────────────────
            contacts_reset = LeadContact.query.update(
                {
                    "email_status": "pending",
                    "current_sequence_step": 0,
                    "last_email_sent_at": None,
                },
                synchronize_session=False,
            )

            # ── 4. Reset Lead state ───────────────────────────────────────────
            leads_reset = Lead.query.update(
                {
                    "email_status": "pending",
                    "current_sequence_step": 0,
                    "last_email_sent_at": None,
                },
                synchronize_session=False,
            )

            # ── 5. Un-complete campaigns ──────────────────────────────────────
            campaigns_reset = LeadCampaign.query.filter(
                LeadCampaign.status.in_(["completed", "paused"])
            ).update({"status": "sending"}, synchronize_session=False)

            db.session.commit()

            print(f"\nRESET COMPLETE:")
            print(f"  Deleted LeadContactEmail : {deleted_lce}")
            print(f"  Deleted LeadEmail        : {deleted_le}")
            print(f"  Contacts reset→pending   : {contacts_reset}")
            print(f"  Leads reset→pending      : {leads_reset}")
            print(f"  Campaigns un-completed   : {campaigns_reset}")

            # ── 6. Send step-1 emails ─────────────────────────────────────────
            print(f"\nTriggering step-1 email send...")
            service = LeadAutomationService()
            result  = service.send_to_all_unsent_ever(sequence_step=1)

            print(f"\nSEND RESULT:")
            for k, v in result.items():
                print(f"  {k:35}: {v}")

        else:
            # Dry-run: just show what would happen
            pending_contacts = LeadContact.query.filter(
                LeadContact.email.isnot(None),
                LeadContact.email_status != "unsubscribed",
            ).count()

            print(f"\n[DRY RUN] Would delete:")
            print(f"  LeadContactEmail rows  : {lce_total}")
            print(f"  LeadEmail rows (legacy): {le_total}")
            print(f"\n[DRY RUN] Would reset to 'pending':")
            print(f"  LeadContacts           : {contacts}")
            print(f"  Leads                  : {leads_total}")
            print(f"\n[DRY RUN] Would send step-1 to up to: {pending_contacts} contacts")
            print(f"  (subject to 250/day limit and unsubscribe checks)")
            print(f"\nRun without --dry-run to execute.")

        print("\n" + "=" * 70)
        print("DONE")
        print("=" * 70)


if __name__ == "__main__":
    sys.exit(main() or 0)
