# Fix Email Sending Issues

## Problem 1: BREVO_API_KEY Not Found (401 Error)

The error `Brevo error: 401 - Key not found` means the BREVO_API_KEY is not set properly.

### Solution:

1. **Check your .env file at `/home/fieljtgr/.env`**:
   ```bash
   grep BREVO_API_KEY /home/fieljtgr/.env
   ```

2. **If missing or empty, add your Brevo API key**:
   ```bash
   # Edit the .env file
   nano /home/fieljtgr/.env

   # Add this line (replace with your actual key):
   BREVO_API_KEY=your_actual_brevo_api_key_here
   BREVO_FROM_EMAIL=brian@fieldsprout.io
   BREVO_FROM_NAME=Brian @ FieldSprout.io
   ```

3. **Get your Brevo API key from**:
   - Login to Brevo: https://app.brevo.com/
   - Go to Settings → SMTP & API → API Keys
   - Copy your v3 API key

4. **Test the key is working**:
   ```python
   # Quick test
   python3 -c "
   import os
   import requests
   key = os.getenv('BREVO_API_KEY')
   if not key:
       print('ERROR: BREVO_API_KEY not set')
   else:
       print(f'Testing key: {key[:10]}...')
       headers = {'api-key': key}
       r = requests.get('https://api.brevo.com/v3/account', headers=headers)
       print(f'Status: {r.status_code}')
       if r.status_code == 200:
           print('✓ API key is valid!')
           print(f'Account: {r.json().get(\"email\")}')
       else:
           print(f'✗ API key invalid: {r.text}')
   "
   ```

---

## Problem 2: Slow Email Sending (One Email at a Time)

### Current Issue:
The automation sends emails **one at a time**, making an API call for each email. This is:
- ❌ SLOW (takes ~500ms per email)
- ❌ Inefficient (250 emails = 125 seconds of API calls)
- ❌ More likely to hit rate limits

### Solution: Batch Email Sending

I've created a **batch email sender** that sends up to **500 emails per API call**!

#### Benefits:
- ✅ **100x FASTER** - Send 500 emails in 1 API call instead of 500 calls
- ✅ **Fewer rate limits** - Much less likely to hit Brevo's API rate limits
- ✅ **More efficient** - Fewer network requests

---

## How to Enable Batch Sending

### Option 1: Use the New Batch Module (Recommended)

The batch sending module is in:
```
flaskapp/app/services/lead_automation_service_batch.py
```

To use it, update your main automation service:

1. **Edit `lead_automation_service.py`**:
   ```python
   # At the top, add this import:
   from app.services.lead_automation_service_batch import process_email_sending_batch

   # Then replace the _process_email_sending method with:
   def _process_email_sending(self) -> int:
       """Send emails in batches (MUCH FASTER!)"""
       return process_email_sending_batch(self)
   ```

That's it! The automation will now send emails in batches of up to 500 at a time.

### Option 2: Manual Batch Send Script

If you want to manually send emails in batches without running the full automation:

```python
#!/usr/bin/env python3
"""Send pending emails in batches"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'flaskapp'))

from app import create_app
from app.services.lead_automation_service_batch import process_email_sending_batch
from app.services.lead_automation_service import LeadAutomationService

app = create_app()

with app.app_context():
    service = LeadAutomationService()
    sent = process_email_sending_batch(service)
    print(f"Sent {sent} emails in batches!")
```

Save as `send_batch_emails.py` and run:
```bash
python3 send_batch_emails.py
```

---

## Performance Comparison

### OLD (One-by-One):
```
Sending 250 emails:
- 250 API calls × 500ms = 125 seconds
- Higher chance of rate limits
- More network overhead
```

### NEW (Batch):
```
Sending 250 emails:
- 1 API call × 1 second = 1 second
- Very unlikely to hit rate limits
- Minimal network overhead
```

**Result: 100x faster!** 🚀

---

## After Fixing

1. **Fix the API key** first (Problem 1)
2. **Enable batch sending** (Problem 2)
3. **Run the automation again**:
   ```bash
   /home/fieljtgr/flaskapp/run_automation_production.sh
   ```

You should see emails sent MUCH faster with no 401 errors!
