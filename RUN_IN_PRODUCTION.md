# Run Lead Automation in Production

## Quick Start

1. **SSH into your production server**

2. **Navigate to the application directory:**
   ```bash
   cd /home/fieljtgr/flaskapp
   ```

3. **Run the automation script:**
   ```bash
   ./force_complete_automation.sh
   ```

This will:
- Check current automation status
- Ask for confirmation
- Run scraping, enrichment, and emailing in batches
- Continue until daily limits are hit or all work is complete

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
