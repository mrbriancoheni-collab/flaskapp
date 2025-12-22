# Installing Dependencies for Lead Automation

## Quick Fix: Install Missing Dependencies

The automation requires Python packages that aren't installed yet in your virtualenv.

### Step 1: Activate Virtual Environment

```bash
source /home/fieljtgr/virtualenv/flaskapp/3.9/bin/activate
```

### Step 2: Navigate to App Directory

```bash
cd /home/fieljtgr/flaskapp
```

### Step 3: Install All Dependencies

```bash
pip install -r flaskapp/requirements.txt
```

This will install:
- `beautifulsoup4` - Web scraping for lead extraction
- `requests` - HTTP client for API calls
- `google-ads` - Google Ads API integration
- `cryptography` - Encryption for credentials
- `weasyprint` - PDF generation for reports
- And all other required packages

### Step 4: Verify Installation

```bash
python3 -c "from bs4 import BeautifulSoup; print('✓ BeautifulSoup installed successfully')"
```

### Step 5: Run Automation Again

```bash
python3 run_automation.py
```

---

## Alternative: Install Just BeautifulSoup

If you only want to fix the immediate error:

```bash
source /home/fieljtgr/virtualenv/flaskapp/3.9/bin/activate
pip install beautifulsoup4
```

**Note:** You'll likely hit more missing dependencies. It's better to install everything from requirements.txt.

---

## Common Installation Issues

### Error: "No module named 'pip'"

```bash
# Reinstall pip in virtualenv
python3 -m ensurepip --upgrade
```

### Error: "Permission denied"

```bash
# Make sure you're in the virtualenv (should see (flaskapp) in prompt)
source /home/fieljtgr/virtualenv/flaskapp/3.9/bin/activate

# Install without sudo (virtualenv doesn't need it)
pip install -r flaskapp/requirements.txt
```

### Error: "gcc: command not found" (during weasyprint install)

```bash
# Install build tools (may need sudo/root)
yum install gcc python3-devel  # CentOS/RHEL
# OR
apt-get install build-essential python3-dev  # Ubuntu/Debian
```

### Error: "Could not find a version that satisfies..."

```bash
# Update pip first
pip install --upgrade pip setuptools wheel

# Then try again
pip install -r flaskapp/requirements.txt
```

---

## Full Requirements List

The automation needs these packages:

**Core Flask:**
- Flask, Flask-Login, Flask-WTF, Flask-SQLAlchemy, Flask-Migrate
- PyMySQL (database connector)

**Lead Automation:**
- `beautifulsoup4` - HTML parsing for web scraping
- `requests` - HTTP requests
- `google-ads` - Google Ads API
- `openai` - AI content generation
- `anthropic` - Claude AI integration

**Email & Outreach:**
- `email-validator` - Email validation
- Mailgun/Brevo SDK (configured via API keys)

**Security:**
- `cryptography` - Credential encryption
- `flask-limiter` - Rate limiting

**Reporting:**
- `pandas`, `numpy` - Data processing
- `weasyprint`, `Pillow` - PDF generation

---

## After Installation

Once dependencies are installed, run:

```bash
./run_lead_automation.sh
```

Or manually:

```bash
export SQLALCHEMY_DATABASE_URI="mysql+pymysql://root:YOUR_PASSWORD@localhost:3306/fieljtgr_xyz?charset=utf8mb4"
python3 run_automation.py
```

---

## Still Having Issues?

1. **Check Python version:**
   ```bash
   python3 --version  # Should be 3.9.x
   ```

2. **Verify you're in virtualenv:**
   ```bash
   which python3  # Should show /home/fieljtgr/virtualenv/flaskapp/3.9/bin/python3
   ```

3. **List installed packages:**
   ```bash
   pip list | grep beautifulsoup
   ```

4. **Check for conflicting packages:**
   ```bash
   pip check
   ```
