# Run Lead Automation in Production

## Quick Start (Recommended)

1. **SSH into your production server**

2. **Run the automation script from anywhere:**
   ```bash
   /home/fieljtgr/flaskapp/run_automation_production.sh
   ```

This script will:
- Automatically load environment variables from `/home/fieljtgr/.env`
- Navigate to the correct app directory
- Check current automation status
- Ask for confirmation
- Run scraping, enrichment, and emailing in batches
- Continue until all 20 campaigns are processed or daily limits are hit

## Alternative Method

If you prefer to run from the app directory:

```bash
cd /home/fieljtgr/flaskapp
./force_complete_automation.sh
```

## Manual Run (Alternative)

If you prefer to run manually:

```bash
cd /home/fieljtgr/flaskapp

# Check status first
python3 run_lead_automation.py --dry-run

# Run the automation
python3 run_lead_automation.py
```

## Monitoring Progress

Check the state file to see progress:
```bash
cat automation_state.json
```

## Configuration Verified

The system is configured with:
- ✅ 20 business types (Plumbing, HVAC, Electrical, etc.)
- ✅ 100 US cities per campaign
- ✅ Directory exclusions (Yelp, HomeAdvisor, etc.)
- ✅ Brevo email from brian@fieldsprout.io
- ✅ All workers ready

## Daily Limits

- Scraping: 50 campaigns per day
- Enrichment: 100 leads per day
- Emails: 250 per day

The script will run multiple times automatically until these limits are hit or all campaigns are complete.
