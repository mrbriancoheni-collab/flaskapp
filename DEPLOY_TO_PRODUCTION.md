# Deploy Lead Automation to Production

## Step 1: Pull Latest Changes to Production

SSH into your production server and run:

```bash
cd /home/fieljtgr/flaskapp

# Pull the latest changes from the branch
git fetch origin
git checkout claude/limit-scraping-campaigns-0JNOv
git pull origin claude/limit-scraping-campaigns-0JNOv
```

Or if you want to merge into main first:

```bash
cd /home/fieljtgr/flaskapp

# Merge the feature branch into main
git checkout main
git pull origin main
git merge claude/limit-scraping-campaigns-0JNOv
git push origin main
```

## Step 2: Verify Files Are Present

Check that the automation files are now in production:

```bash
ls -la /home/fieljtgr/flaskapp/run_lead_automation.py
ls -la /home/fieljtgr/flaskapp/run_automation_production.sh
ls -la /home/fieljtgr/flaskapp/force_complete_automation.sh
```

All three files should be present.

## Step 3: Ensure Environment Variables Are Set

Verify your `.env` file has the required variables:

```bash
grep -E "SQLALCHEMY_DATABASE_URI|BREVO|SERPAPI" /home/fieljtgr/.env
```

Should show:
- `SQLALCHEMY_DATABASE_URI` - Your database connection
- `BREVO_API_KEY` - Your Brevo API key
- `BREVO_FROM_EMAIL=brian@fieldsprout.io`
- `BREVO_FROM_NAME=Brian @ FieldSprout.io`
- `SERPAPI_API_KEY` - Your SerpAPI key

## Step 4: Install Dependencies (if needed)

If you don't have a virtualenv yet, or need to update dependencies:

```bash
cd /home/fieljtgr/flaskapp

# If virtualenv doesn't exist at /home/fieljtgr/virtualenv/flaskapp/3.9/
python3 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install -r flaskapp/requirements.txt
```

## Step 5: Run the Automation

Now you can run the automation:

```bash
/home/fieljtgr/flaskapp/run_automation_production.sh
```

Or manually:

```bash
cd /home/fieljtgr/flaskapp
source /home/fieljtgr/.env
python3 run_lead_automation.py --dry-run  # Check status first
python3 run_lead_automation.py            # Run automation
```

---

## Troubleshooting

### If git isn't available in production:

Copy the files manually:

```bash
# From your local machine or git server
scp run_lead_automation.py user@production:/home/fieljtgr/flaskapp/
scp run_automation_production.sh user@production:/home/fieljtgr/flaskapp/
scp force_complete_automation.sh user@production:/home/fieljtgr/flaskapp/

# Make scripts executable
ssh user@production "chmod +x /home/fieljtgr/flaskapp/*.sh"
```

### If virtualenv path is different:

Edit `run_automation_production.sh` and update the `VENV_DIR` variable to match your actual virtualenv location.
