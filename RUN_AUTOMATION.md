# How to Run Lead Automation

## Quick Start

The automation script needs database credentials to run. Here's how to set it up:

### Option 1: Using Environment Variable (Recommended)

```bash
# Set the database connection string
export SQLALCHEMY_DATABASE_URI="mysql+pymysql://root:YOUR_PASSWORD@localhost:3306/fieljtgr_xyz?charset=utf8mb4"

# Run the automation
python3 run_automation.py
```

**Replace `YOUR_PASSWORD` with your actual MySQL root password.**

### Option 2: Using the Virtual Environment

If you have a virtualenv set up with environment variables already configured:

```bash
# Activate virtualenv
source /home/fieljtgr/virtualenv/flaskapp/3.9/bin/activate

# Change to app directory
cd /home/fieljtgr/flaskapp

# Run automation
python3 run_automation.py
```

### Option 3: Create a .env File

Create a `.env` file in `/home/user/flaskapp/` (or `/home/fieljtgr/flaskapp/`):

```bash
SQLALCHEMY_DATABASE_URI=mysql+pymysql://root:YOUR_PASSWORD@localhost:3306/fieljtgr_xyz?charset=utf8mb4
```

Then run:

```bash
# Load .env and run
python3 run_automation.py
```

---

## What the Script Does

The automation runs 3 stages daily:

1. **Scraping** (up to 50 campaigns/day)
   - Searches Google for campaigns configured
   - Extracts company leads from ads, maps, LSA, organic results

2. **Enrichment** (up to 100 leads/day)
   - Uses Apollo.io to find decision maker contact info
   - Gets emails, titles, LinkedIn profiles

3. **Email Sending** (up to 250 emails/day)
   - Sends personalized outreach emails
   - Tracks opens, clicks, replies
   - Respects CAN-SPAM compliance

---

## Checking Your Database Password

If you don't know your MySQL password, try:

```bash
# Check if MySQL config file has credentials
cat ~/.my.cnf

# Or check the virtualenv activation script
cat /home/fieljtgr/virtualenv/flaskapp/3.9/bin/activate | grep -i "database\|mysql"
```

---

## After Running

Once the automation runs successfully, you can check results with:

```bash
# SQL diagnostic (fast)
mysql -u root -p fieljtgr_xyz < check_lead_automation_status.sql

# Python diagnostic (detailed)
python3 check_lead_automation_status.py
```

---

## Common Errors

### Error: "No module named 'bs4'" or similar import errors
**Solution:** Install dependencies:
```bash
source /home/fieljtgr/virtualenv/flaskapp/3.9/bin/activate
cd /home/fieljtgr/flaskapp
pip install -r flaskapp/requirements.txt
```
**See:** `INSTALL_DEPENDENCIES.md` for detailed instructions

### Error: "SQLALCHEMY_DATABASE_URI must be set"
**Solution:** Set the environment variable before running (see Option 1 above)

### Error: "Access denied for user 'root'@'localhost'"
**Solution:** Wrong password - update the connection string with correct password

### Error: "Unknown database 'fieljtgr_xyz'"
**Solution:** Run the migration first:
```bash
mysql -u root -p fieljtgr_xyz < migrations_sql/012_lead_automation_complete.sql
```

### Error: "Cannot initialize scraper"
**Solution:** Missing SerpAPI key:
```bash
export SERPAPI_KEY="your_serpapi_key"
```

### Error: "Cannot initialize mailgun outreach service"
**Solution:** Missing email provider credentials:
```bash
# For Mailgun:
export MAILGUN_API_KEY="your_key"
export MAILGUN_DOMAIN="mg.yourdomain.com"

# OR for Brevo:
export EMAIL_PROVIDER="brevo"
export BREVO_API_KEY="your_key"
```

---

## Setting Up Daily Automation (Cron)

Once it's working manually, set up a daily cron job:

```bash
# Edit crontab
crontab -e

# Add this line (runs daily at 9 AM):
0 9 * * * export SQLALCHEMY_DATABASE_URI="mysql+pymysql://root:PASSWORD@localhost:3306/fieljtgr_xyz?charset=utf8mb4" && cd /home/fieljtgr/flaskapp && /home/fieljtgr/virtualenv/flaskapp/3.9/bin/python3 run_automation.py >> /tmp/lead_automation.log 2>&1
```

**Remember to replace PASSWORD with your actual password!**

---

## Need Help?

1. Check the setup guide: `SETUP_LEAD_AUTOMATION.md`
2. Run the diagnostic: `check_lead_automation_status.sql`
3. Check application logs for detailed errors
