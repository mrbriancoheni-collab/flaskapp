# LinkedIn AI Post Generator Setup

## Current Status
✅ Anthropic library installed
⚠️ ANTHROPIC_API_KEY needs to be added to production environment

## Issue
LinkedIn post generator shows "AI Configuration Required" and posts don't auto-generate from URL parameters.

## Root Cause
The `ANTHROPIC_API_KEY` environment variable is not set in the production environment.

## Solution

### Step 1: Add API Key to Production Environment

On the production server, add the following line to `/home/fieljtgr/.env`:

```bash
ANTHROPIC_API_KEY=your_anthropic_api_key_here
```

Get your API key from: https://console.anthropic.com/settings/keys

### Step 2: Verify the .env File

```bash
# SSH into production server
ssh user@fieldsprout.io

# Check if the key is set
grep ANTHROPIC_API_KEY /home/fieljtgr/.env
```

### Step 3: Restart the Application

The Flask app uses `python-dotenv` to load environment variables from `.env` file. After adding the key, restart the application:

```bash
# Restart Flask application (method depends on your deployment)
# If using systemd:
sudo systemctl restart flaskapp

# If using supervisor:
sudo supervisorctl restart flaskapp

# If using gunicorn directly, find and restart the process:
ps aux | grep gunicorn
sudo kill -HUP <gunicorn_master_pid>
```

### Step 4: Test the LinkedIn Post Generator

1. Visit: https://fieldsprout.io/account/linkedin/post-generator
2. The banner should now show "AI-Powered Content Generation Active" (green)
3. Fill in expertise and topic, click "Generate Thought Leader Post"
4. Or use URL parameters for auto-generation:

```
https://fieldsprout.io/account/linkedin/post-generator?expertise=20+years+of+marketing+experience&industry=home+services&topic=AI+in+home+services&tone=professional&include_hashtags=on&include_cta=on
```

## What Was Fixed in This Update

1. **Anthropic Library**: Installed `anthropic` Python package
2. **Form Pre-filling**: Fixed industry/tone dropdowns and checkboxes to properly pre-select from URL parameters
3. **Auto-generation**: Posts should now auto-generate when URL has both expertise and topic parameters

## Files Modified

- `flaskapp/templates/linkedin/post_generator.html` - Fixed form pre-filling for all fields
- Installed: `anthropic==0.75.0` and dependencies

## Environment Variables Used

- `ANTHROPIC_API_KEY` - Required for AI post generation (Claude API)

## Troubleshooting

### "AI not configured" banner still showing
- Verify ANTHROPIC_API_KEY is in .env file
- Restart the Flask application
- Check application logs for import errors

### Posts not auto-generating from URL
- Ensure both `expertise` and `topic` parameters are in the URL
- Check browser console (F12) for JavaScript errors
- Verify the Generate button is not disabled

### "Missing ANTHROPIC_API_KEY" error alert
- The API key is not set in the environment
- Follow Step 1-3 above to add and reload

### Import errors after installing anthropic
- Check that the Flask app can import the library:
  ```bash
  python3 -c "import anthropic; print('OK')"
  ```
- If using a virtual environment, make sure it's activated and library is installed there

## API Cost Information

- Model used: `claude-3-5-sonnet-20241022`
- Approximate cost: $0.003 per post generation (150-300 word posts)
- Max tokens per request: 1000

## Next Steps

1. Add the ANTHROPIC_API_KEY to production .env
2. Restart the Flask app
3. Test post generation
4. Deploy the latest code changes from this branch: `claude/limit-scraping-campaigns-0JNOv`
