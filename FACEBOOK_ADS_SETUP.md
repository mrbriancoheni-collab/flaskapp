# Facebook / Meta Ads Setup

The Facebook Ads integration (connect, sync, AI agents, mutations) requires a
Meta App and three environment variables in the root `.env` file.

## 1. Create a Meta App

1. Go to https://developers.facebook.com/apps and click **Create App**
2. Choose **Business** as the app type
3. Under **Add Products**, add **Facebook Login** and **Marketing API**
4. In **Facebook Login → Settings**, add your callback to
   **Valid OAuth Redirect URIs**:
   `https://fieldsprout.io/account/fbads/callback`
5. In **App Review → Permissions and Features**, request advanced access for:
   - `ads_management`
   - `ads_read`
   - `read_insights`
   - `business_management`
   - `pages_show_list`
   - `leads_retrieval`

## 2. Add environment variables

Add to the root `.env` file (same directory as `run_job.py`):

```bash
FB_APP_ID=your_app_id_from_meta_dashboard
FB_APP_SECRET=your_app_secret_from_meta_dashboard
# Optional — defaults to https://fieldsprout.io/account/fbads/callback
# FB_REDIRECT_URI=https://staging.example.com/account/fbads/callback
```

Restart the app (touch `tmp/restart.txt` for Passenger) after changing `.env`.

## 3. Connect an account

1. In the app, go to **Account → Facebook Ads → Connect**
2. Approve the permission dialog (the scopes above)
3. Select the ad account and page to manage

Tokens are long-lived (60 days), stored in the `facebook_tokens` table, and
auto-refreshed when within 7 days of expiry. If a token fully expires, the UI
prompts the user to reconnect.

## 4. Enable the daily sync cron

Campaigns, ad sets, ads, and 30-day insights sync nightly. Add to crontab:

```bash
30 3 * * * cd /home/fieldsprout/flaskapp && python run_job.py sync_fb_all_accounts >> logs/cron.log 2>&1
```

Or run once manually to verify the connection end to end:

```bash
python run_job.py sync_fb_all_accounts
```
