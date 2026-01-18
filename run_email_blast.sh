#!/bin/bash
# Script to manually run smart email sequencing
#
# This script uses intelligent delay-based sequencing to automatically
# progress contacts through multi-step email campaigns (steps 1-6, etc.)
#
# Usage:
#   bash run_email_blast.sh           # Smart sequencing (recommended)
#   bash run_email_blast.sh 1         # Send only step 1
#   bash run_email_blast.sh 2         # Send only step 2

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
BASE_DIR="$SCRIPT_DIR"

cd "$BASE_DIR" || exit 1

# Source .env file if it exists
if [ -f "$BASE_DIR/.env" ]; then
    export $(grep -v '^#' "$BASE_DIR/.env" | xargs)
fi

# Set defaults if not in environment
export EMAIL_PROVIDER="${EMAIL_PROVIDER:-brevo}"
export BREVO_FROM_EMAIL="${BREVO_FROM_EMAIL:-noreply@fieldsprout.io}"
export BREVO_FROM_NAME="${BREVO_FROM_NAME:-FieldSprout}"

# Create logs directory
mkdir -p "$BASE_DIR/logs"

# Auto-detect Python virtualenv
if [ -f "$BASE_DIR/venv/bin/python" ]; then
    PYTHON="$BASE_DIR/venv/bin/python"
elif [ -f "$BASE_DIR/virtualenv/bin/python" ]; then
    PYTHON="$BASE_DIR/virtualenv/bin/python"
else
    PYTHON="python3"
fi

# Get mode from first argument (default: smart)
MODE="${1:-smart}"

# Create Python script
cat > /tmp/email_blast_runner.py <<'EOFPYTHON'
import sys
import os

# Add the flaskapp directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'flaskapp'))

from app import create_app
from app.services.lead_automation_service import LeadAutomationService

def run_smart_sequencing():
    """Run smart delay-based sequencing (recommended)"""
    app = create_app()

    with app.app_context():
        print("=" * 80)
        print("SMART SEQUENCE PROGRESSION")
        print("Automatically sends next step based on delay_days configuration")
        print("=" * 80)

        service = LeadAutomationService()
        result = service.send_next_sequence_steps()

        print("\n" + "=" * 80)
        print("COMPLETE:")
        print(f"  - Emails sent: {result['sent']}")
        print(f"  - Total contacts checked: {result.get('total_contacts_checked', 0)}")
        print(f"  - Skipped (unsubscribed): {result.get('skipped_unsubscribed', 0)}")
        print(f"  - Skipped (not ready/delay pending): {result.get('skipped_not_ready', 0)}")
        print(f"  - Skipped (completed all steps): {result.get('skipped_complete', 0)}")
        print("=" * 80)

        return result

def run_single_step(sequence_step):
    """Run email blast for a specific sequence step"""
    app = create_app()

    with app.app_context():
        print("=" * 80)
        print(f"SENDING SEQUENCE STEP {sequence_step} TO ALL WHO HAVEN'T RECEIVED IT")
        print("=" * 80)

        service = LeadAutomationService()
        result = service.send_to_all_unsent_ever(sequence_step=sequence_step)

        print("\n" + "=" * 80)
        print(f"COMPLETE:")
        print(f"  - Emails sent: {result['sent']}")
        print(f"  - Sequence step: {sequence_step}")
        print(f"  - Eligible contacts (haven't received step {sequence_step}): {result.get('eligible_contacts', 0)}")
        print(f"  - Total contacts checked: {result.get('total_contacts_checked', 0)}")
        print(f"  - Skipped (unsubscribed): {result.get('skipped_unsubscribed', 0)}")
        print(f"  - Skipped (already received step {sequence_step}): {result.get('skipped_already_received_step', 0)}")
        print("=" * 80)

        return result

if __name__ == '__main__':
    try:
        # Get mode from environment variable set by bash script
        mode = os.environ.get('EMAIL_BLAST_MODE', 'smart')

        if mode == 'smart':
            result = run_smart_sequencing()
        else:
            # Mode is a step number
            step = int(mode)
            result = run_single_step(step)

        sys.exit(0 if result['sent'] >= 0 else 1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
EOFPYTHON

# Set environment variable for Python script
export EMAIL_BLAST_MODE="$MODE"

# Run the script
echo "========================================" | tee -a "$BASE_DIR/logs/email_blast.log"
echo "Starting email blast at $(date)" | tee -a "$BASE_DIR/logs/email_blast.log"
echo "Base dir: $BASE_DIR" | tee -a "$BASE_DIR/logs/email_blast.log"
echo "Python: $PYTHON" | tee -a "$BASE_DIR/logs/email_blast.log"
echo "Mode: $MODE" | tee -a "$BASE_DIR/logs/email_blast.log"
echo "========================================" | tee -a "$BASE_DIR/logs/email_blast.log"

$PYTHON /tmp/email_blast_runner.py 2>&1 | tee -a "$BASE_DIR/logs/email_blast.log"

EXIT_CODE=$?

echo "========================================" | tee -a "$BASE_DIR/logs/email_blast.log"
echo "Finished at $(date) with exit code: $EXIT_CODE" | tee -a "$BASE_DIR/logs/email_blast.log"
echo "========================================" | tee -a "$BASE_DIR/logs/email_blast.log"

# Cleanup
rm /tmp/email_blast_runner.py

exit $EXIT_CODE
