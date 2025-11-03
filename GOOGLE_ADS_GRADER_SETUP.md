# Google Ads Grader - Setup Guide

## Issue

The Google Ads Grader tool at `/ads-grader` is showing:

```
Google Ads connection not configured. Using demo mode.
```

This means the required Google Ads API credentials are not configured in your environment variables.

---

## Why This Happens

The Ads Grader needs to connect to the Google Ads API to fetch real account data. Without proper credentials, it falls back to "demo mode" which uses mock data.

The code checks for these credentials at startup:

```python
# From app/config.py lines 23-26
GOOGLE_ADS_DEVELOPER_TOKEN = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN") or None
GOOGLE_ADS_LOGIN_CUSTOMER_ID = os.getenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID") or None
GOOGLE_ADS_CLIENT_ID = os.getenv("GOOGLE_ADS_CLIENT_ID","")
GOOGLE_ADS_CLIENT_SECRET = os.getenv("GOOGLE_ADS_CLIENT_SECRET","")
```

If `GOOGLE_ADS_CLIENT_ID` is not set, the app shows the "demo mode" message (see `app/ads_grader/__init__.py` line 75).

---

## Required Credentials

To connect the Ads Grader to real Google Ads accounts, you need:

### 1. Google Ads Developer Token
- **Purpose:** Authenticates your application with the Google Ads API
- **How to get it:**
  1. Sign in to your [Google Ads Manager account](https://ads.google.com/home/tools/manager-accounts/)
  2. Navigate to **TOOLS & SETTINGS** > **Setup** > **API Center**
  3. Apply for a developer token (requires approval from Google)
  4. **Note:** For testing, Google provides a test developer token, but it only works with test accounts

### 2. Google OAuth 2.0 Credentials
- **Purpose:** Allow users to authorize your app to access their Google Ads data
- **How to get them:**
  1. Go to [Google Cloud Console](https://console.cloud.google.com/)
  2. Select your project (or create a new one)
  3. Enable the **Google Ads API**:
     - Navigate to **APIs & Services** > **Library**
     - Search for "Google Ads API"
     - Click **Enable**
  4. Create OAuth 2.0 credentials:
     - Navigate to **APIs & Services** > **Credentials**
     - Click **+ CREATE CREDENTIALS** > **OAuth client ID**
     - Choose **Web application**
     - Add authorized redirect URIs:
       - For local development: `http://localhost:5000/ads-grader/connect/callback`
       - For production: `https://yourdomain.com/ads-grader/connect/callback`
     - Click **Create**
  5. Copy the **Client ID** and **Client Secret**

### 3. Login Customer ID (Optional but Recommended)
- **Purpose:** The Google Ads Manager account ID that has access to the accounts you want to grade
- **Format:** Remove dashes (e.g., `123-456-7890` becomes `1234567890`)
- **How to find it:**
  1. Sign in to your [Google Ads Manager account](https://ads.google.com/)
  2. Look in the top-right corner for your customer ID

---

## Configuration Steps

### Option 1: Using Environment Variables (Recommended for Production)

Set these environment variables in your hosting environment:

```bash
# Required
export GOOGLE_ADS_CLIENT_ID="your-client-id.apps.googleusercontent.com"
export GOOGLE_ADS_CLIENT_SECRET="your-client-secret"
export GOOGLE_ADS_DEVELOPER_TOKEN="your-developer-token"

# Optional
export GOOGLE_ADS_LOGIN_CUSTOMER_ID="1234567890"  # No dashes
export GOOGLE_ADS_REDIRECT_URI="https://yourdomain.com/ads-grader/connect/callback"
```

### Option 2: Using .env File (For Local Development)

1. Create a `.env` file in the project root:

```bash
cd /home/user/flaskapp
nano .env
```

2. Add the following content:

```env
# Google Ads API Configuration
GOOGLE_ADS_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_ADS_CLIENT_SECRET=your-client-secret
GOOGLE_ADS_DEVELOPER_TOKEN=your-developer-token
GOOGLE_ADS_LOGIN_CUSTOMER_ID=1234567890
GOOGLE_ADS_REDIRECT_URI=http://localhost:5000/ads-grader/connect/callback
```

3. Install python-dotenv (if not already installed):

```bash
pip install python-dotenv
```

4. Update your Flask app to load the .env file (usually in `wsgi.py` or `__init__.py`):

```python
from dotenv import load_dotenv
load_dotenv()  # Load environment variables from .env file
```

### Option 3: Set Environment Variables in Docker

If using Docker, add to your `docker-compose.yml`:

```yaml
services:
  web:
    environment:
      - GOOGLE_ADS_CLIENT_ID=your-client-id.apps.googleusercontent.com
      - GOOGLE_ADS_CLIENT_SECRET=your-client-secret
      - GOOGLE_ADS_DEVELOPER_TOKEN=your-developer-token
      - GOOGLE_ADS_LOGIN_CUSTOMER_ID=1234567890
      - GOOGLE_ADS_REDIRECT_URI=https://yourdomain.com/ads-grader/connect/callback
```

Or use an `.env` file with Docker:

```yaml
services:
  web:
    env_file:
      - .env
```

---

## Verification

After setting the environment variables, restart your Flask application and:

1. Navigate to `/ads-grader`
2. Click "Connect Google Ads" or similar button
3. You should be redirected to Google's OAuth consent screen
4. After authorizing, you should be able to select a Google Ads account
5. The grader should fetch real data instead of showing "demo mode"

---

## Troubleshooting

### Issue: Still seeing "demo mode" after configuration

**Solution:**
- Verify environment variables are set correctly:
  ```bash
  # In Python shell
  import os
  print(os.getenv('GOOGLE_ADS_CLIENT_ID'))
  ```
- Ensure you restarted the Flask application after setting variables
- Check for typos in variable names (they are case-sensitive)

### Issue: "Error connecting to Google Ads"

**Solutions:**
- Verify your OAuth redirect URI matches exactly:
  - Check Google Cloud Console credentials configuration
  - Check `GOOGLE_ADS_REDIRECT_URI` environment variable
  - Must include the protocol (`http://` or `https://`)
- Ensure Google Ads API is enabled in your Google Cloud project
- Verify your developer token is active (not expired or rejected)

### Issue: "No Google Ads accounts found"

**Solutions:**
- The user authorizing must have access to at least one Google Ads account
- If using a Manager account, ensure `GOOGLE_ADS_LOGIN_CUSTOMER_ID` is set
- Verify the OAuth scopes include necessary permissions

### Issue: "Failed to authorize Google Ads access"

**Solutions:**
- User must grant all requested permissions during OAuth flow
- Check that the redirect URI is correctly configured in both:
  - Google Cloud Console
  - Your environment variables
- Clear browser cookies/cache and try again

---

## OAuth Flow Explanation

When a user clicks "Connect Google Ads":

1. **Authorization Request:** App redirects to Google OAuth consent screen
2. **User Consent:** User logs in and grants permissions
3. **Callback:** Google redirects back to your app with an authorization code
4. **Token Exchange:** App exchanges code for access and refresh tokens
5. **API Access:** App uses tokens to fetch Google Ads data

The tokens are stored in the user's session for single-use grading. For recurring analysis, you could store them in the database.

---

## Security Best Practices

1. **Never commit credentials to git:**
   ```bash
   # Add to .gitignore
   echo ".env" >> .gitignore
   echo "*.env" >> .gitignore
   ```

2. **Use secrets management in production:**
   - AWS Secrets Manager
   - Google Secret Manager
   - HashiCorp Vault
   - Environment variables in your hosting platform (Heroku, Railway, etc.)

3. **Rotate credentials regularly:**
   - Update OAuth client secrets periodically
   - Monitor for unauthorized access in Google Cloud Console

4. **Restrict OAuth scopes to minimum required:**
   - The Ads Grader only needs read-only access
   - Current scope: `https://www.googleapis.com/auth/adwords` (read/write)
   - Consider changing to read-only if available

---

## Testing the Setup

### Test with Google's Test Account

Before using production credentials, test with Google's test account:

1. Use test developer token: `INSERT_DEVELOPER_TOKEN_HERE` (provided by Google)
2. Create a test Google Ads account in the Google Ads interface
3. Use test OAuth credentials from Google Cloud Console

### Verify API Access

Create a simple test script:

```python
from google.ads.googleads.client import GoogleAdsClient

credentials = {
    "developer_token": "YOUR_DEVELOPER_TOKEN",
    "client_id": "YOUR_CLIENT_ID",
    "client_secret": "YOUR_CLIENT_SECRET",
    "refresh_token": "USER_REFRESH_TOKEN",  # From OAuth flow
    "use_proto_plus": True,
}

client = GoogleAdsClient.load_from_dict(credentials)
ga_service = client.get_service("GoogleAdsService")

query = "SELECT customer.id, customer.descriptive_name FROM customer"
response = ga_service.search(customer_id="YOUR_CUSTOMER_ID", query=query)

for row in response:
    print(f"Customer ID: {row.customer.id}")
    print(f"Name: {row.customer.descriptive_name}")
```

---

## Code References

### Where Demo Mode is Triggered

**File:** `flaskapp/app/ads_grader/__init__.py`
**Line:** 75-78

```python
# Check if OAuth credentials are configured
if not current_app.config.get("GOOGLE_ADS_CLIENT_ID"):
    logger.warning("Google Ads OAuth not configured - using demo mode")
    flash("Google Ads connection not configured. Using demo mode.", "info")
    return redirect(url_for("ads_grader_bp.analyze"))
```

### Where Credentials are Loaded

**File:** `flaskapp/app/config.py`
**Lines:** 22-30

```python
# Google Ads API configuration
GOOGLE_ADS_DEVELOPER_TOKEN = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN") or None
GOOGLE_ADS_LOGIN_CUSTOMER_ID = (os.getenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID") or "").replace("-", "") or None
GOOGLE_ADS_CLIENT_ID = os.getenv("GOOGLE_ADS_CLIENT_ID","")
GOOGLE_ADS_CLIENT_SECRET = os.getenv("GOOGLE_ADS_CLIENT_SECRET","")
GOOGLE_ADS_REDIRECT_URI = os.getenv("GOOGLE_ADS_REDIRECT_URI","https://fieldsprout.io/ads-grader/connect/callback")
```

### Where Client is Initialized

**File:** `flaskapp/app/ads_grader/google_ads_client.py`
**Lines:** 32-38

```python
# Build credentials dictionary for Google Ads client
credentials = {
    "developer_token": current_app.config.get("GOOGLE_ADS_DEVELOPER_TOKEN"),
    "client_id": current_app.config.get("GOOGLE_ADS_CLIENT_ID"),
    "client_secret": current_app.config.get("GOOGLE_ADS_CLIENT_SECRET"),
    "refresh_token": refresh_token,
    "use_proto_plus": True,
}
```

---

## Additional Resources

- [Google Ads API Documentation](https://developers.google.com/google-ads/api/docs/start)
- [OAuth 2.0 Setup Guide](https://developers.google.com/google-ads/api/docs/oauth/overview)
- [Developer Token Guide](https://developers.google.com/google-ads/api/docs/get-started/dev-token)
- [Python Client Library](https://developers.google.com/google-ads/api/docs/client-libs/python/)

---

## Summary

**The Issue:** Missing Google Ads API credentials in environment variables

**The Fix:**
1. Get credentials from Google Cloud Console and Google Ads Manager
2. Set environment variables: `GOOGLE_ADS_CLIENT_ID`, `GOOGLE_ADS_CLIENT_SECRET`, `GOOGLE_ADS_DEVELOPER_TOKEN`
3. Restart Flask application
4. Test the OAuth flow

**Estimated Time:** 30-60 minutes (including Google approval wait time for developer token)

**Next Steps After Setup:**
- Test with a real Google Ads account
- Monitor API usage in Google Cloud Console
- Consider implementing rate limiting for API calls
- Add error handling for expired tokens
