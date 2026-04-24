#!/usr/bin/env python3
"""
Set up FieldSprout lead generation cron jobs.

Run this on the production server as root:
    cd /home/fieldsprout/flaskapp && python3 scripts/setup_cron_jobs.py

What it installs:
    2:00 AM — scrape new leads
    3:00 AM — enrich leads (crawl websites, find emails)
    9:00 AM — send outreach emails (Mon-Fri only)
"""
import os
import subprocess
import sys
from datetime import datetime

# ── Paths ──────────────────────────────────────────────────────────────────
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)

# Prefer the cPanel virtualenv; fall back to whatever Python is running this
VENV_PYTHON = "/home/fieldsprout/virtualenv/flaskapp/3.9/bin/python3"
PYTHON = VENV_PYTHON if os.path.exists(VENV_PYTHON) else sys.executable

LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

# ── Cron job definitions ───────────────────────────────────────────────────
# Each job: cd to project root so load_env.py finds .env, then run the script.
_BASE = f"cd {PROJECT_ROOT} && {PYTHON}"

JOBS = [
    {
        "name":     "Lead Scraping",
        "schedule": "0 2 * * *",   # 2 AM daily
        "command":  f"{_BASE} scripts/run_lead_scraping.py >> {LOG_DIR}/lead_scraping.log 2>&1",
    },
    {
        "name":     "Lead Enrichment",
        "schedule": "0 3 * * *",   # 3 AM daily (after scraping)
        "command":  f"{_BASE} scripts/run_lead_enrichment.py >> {LOG_DIR}/lead_enrichment.log 2>&1",
    },
    {
        "name":     "Lead Outreach (email)",
        "schedule": "0 9 * * 1-5", # 9 AM Mon-Fri
        "command":  f"{_BASE} scripts/run_lead_outreach.py >> {LOG_DIR}/lead_outreach.log 2>&1",
    },
]

MARKER = "# ── FieldSprout Lead Generation ──"


def get_crontab() -> str:
    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    return result.stdout if result.returncode == 0 else ""


def set_crontab(content: str) -> bool:
    proc = subprocess.run(["crontab", "-"], input=content, text=True, capture_output=True)
    if proc.returncode != 0:
        print(f"crontab error: {proc.stderr.strip()}")
    return proc.returncode == 0


def build_block() -> str:
    lines = [
        "",
        MARKER,
        f"# Updated {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
    ]
    for job in JOBS:
        lines.append(f"# {job['name']}")
        lines.append(f"{job['schedule']} {job['command']}")
    lines.append("")
    return "\n".join(lines)


def main():
    print(f"Project root : {PROJECT_ROOT}")
    print(f"Python       : {PYTHON}")
    print(f"Log dir      : {LOG_DIR}")
    print()

    if not os.path.exists(PYTHON):
        print(f"ERROR: Python not found at {PYTHON}")
        print("Update VENV_PYTHON in this script to the correct path.")
        sys.exit(1)

    # Strip any existing FieldSprout block, then append fresh one
    current = get_crontab()
    lines = current.splitlines()

    cleaned: list[str] = []
    skip = False
    for line in lines:
        if line.strip() == MARKER:
            skip = True
        if not skip:
            cleaned.append(line)
        if skip and line.strip() == "" and cleaned:
            skip = False   # blank line ends the block

    new_crontab = "\n".join(cleaned).rstrip("\n") + build_block() + "\n"

    print("Installing cron jobs:")
    for job in JOBS:
        print(f"  {job['schedule']:15s} {job['name']}")
    print()

    if set_crontab(new_crontab):
        print("Done. Run `crontab -l` to verify.\n")
        print(f"Logs will be written to {LOG_DIR}/")
        print("  lead_scraping.log   — new leads found")
        print("  lead_enrichment.log — website crawl & email discovery")
        print("  lead_outreach.log   — emails sent")
    else:
        print("Failed to install crontab.")
        sys.exit(1)


if __name__ == "__main__":
    main()
