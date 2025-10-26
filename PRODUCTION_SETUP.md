# Google Ads Grader - Production Setup for fieldsprout.io

## Environment Variables for Production

You already have existing Google OAuth credentials. The Ads Grader uses **separate** redirect URI.

### Required Environment Variables

Add these to your production environment:

```bash
# Google Ads API Credentials (already provided)
GOOGLE_ADS_CLIENT_ID="1017078396252-4au60ogqmpjntrbi1d3guamjpld2a8b3.apps.googleusercontent.com"
GOOGLE_ADS_CLIENT_SECRET="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"
GOOGLE_ADS_DEVELOPER_TOKEN="BVH9TCTe66hciT3TrMrKxg"

# Ads Grader specific redirect URI
GOOGLE_ADS_REDIRECT_URI="https://fieldsprout.io/ads-grader/connect/callback"
```

**Note**: This is **separate** from your existing `GOOGLE_REDIRECT_URI` which is for other Google services (Search Console, Analytics, etc.)

---

## Google Cloud Console Configuration

### CRITICAL: Add Redirect URI

1. Go to [Google Cloud Console → Credentials](https://console.cloud.google.com/apis/credentials)
2. Click on OAuth client: **`1017078396252-4au60ogqmpjntrbi1d3guamjpld2a8b3`**
3. In **Authorized redirect URIs**, add:
   ```
   https://fieldsprout.io/ads-grader/connect/callback
   ```
4. **Click "Save"**

### Existing vs New Redirect URIs

You should have **both** of these:

```
✓ https://fieldsprout.io/account/google/callback     (existing - for GSC, Analytics, etc.)
✓ https://fieldsprout.io/ads-grader/connect/callback (NEW - for Ads Grader)
```

They serve different purposes and won't conflict.

---

## Deployment Steps

### 1. Set Environment Variables

Depending on your deployment method:

**Option A: Direct Export (for testing)**
```bash
export GOOGLE_ADS_CLIENT_ID="1017078396252-4au60ogqmpjntrbi1d3guamjpld2a8b3.apps.googleusercontent.com"
export GOOGLE_ADS_CLIENT_SECRET="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"
export GOOGLE_ADS_DEVELOPER_TOKEN="BVH9TCTe66hciT3TrMrKxg"
export GOOGLE_ADS_REDIRECT_URI="https://fieldsprout.io/ads-grader/connect/callback"
```

**Option B: Add to .env file**
```bash
# In your production .env file
GOOGLE_ADS_CLIENT_ID=1017078396252-4au60ogqmpjntrbi1d3guamjpld2a8b3.apps.googleusercontent.com
GOOGLE_ADS_CLIENT_SECRET=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
GOOGLE_ADS_DEVELOPER_TOKEN=BVH9TCTe66hciT3TrMrKxg
GOOGLE_ADS_REDIRECT_URI=https://fieldsprout.io/ads-grader/connect/callback
```

**Option C: Add to systemd service file** (if using systemd)
```ini
[Service]
Environment="GOOGLE_ADS_CLIENT_ID=1017078396252-4au60ogqmpjntrbi1d3guamjpld2a8b3.apps.googleusercontent.com"
Environment="GOOGLE_ADS_CLIENT_SECRET=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"
Environment="GOOGLE_ADS_DEVELOPER_TOKEN=BVH9TCTe66hciT3TrMrKxg"
Environment="GOOGLE_ADS_REDIRECT_URI=https://fieldsprout.io/ads-grader/connect/callback"
```

---

### 2. Deploy Code

```bash
# Pull latest code
cd /home/user/flaskapp
git pull origin claude/merge-multiple-changes-011CUUi91QMvUfH9emxb8aS4

# Install/verify dependencies
pip install -r flaskapp/requirements.txt

# Restart Flask application
sudo systemctl restart your-flask-service
# or
sudo systemctl restart gunicorn
# or however you restart your app
```

---

### 3. Test the Grader

1. **Visit**: `https://fieldsprout.io/ads-grader`
2. **Should see**: Landing page with "Connect Google Ads" button
3. **Click**: "Connect Google Ads"
4. **Expected**: Redirects to Google OAuth screen
5. **Sign in**: Authorize with Google account
6. **Expected**: Redirects back to `https://fieldsprout.io/ads-grader/connect/callback`
7. **Expected**: Shows account selection or goes to analysis
8. **Run analysis**: Should fetch real data from Google Ads account
9. **View report**: Should show real scores, charts, recommendations
10. **Download PDF**: Should generate professional PDF

---

## Troubleshooting

### Error: "redirect_uri_mismatch"

**Problem**: Google OAuth fails with redirect URI error

**Solution**:
1. Verify in Google Cloud Console that redirect URI is **exactly**:
   ```
   https://fieldsprout.io/ads-grader/connect/callback
   ```
2. Make sure there are NO:
   - Extra spaces
   - Trailing slashes
   - HTTP instead of HTTPS
   - Typos in domain or path

---

### Error: "GOOGLE_ADS_CLIENT_ID not configured"

**Problem**: Environment variables not loaded

**Solution**:
1. Verify variables are set:
   ```bash
   echo $GOOGLE_ADS_CLIENT_ID
   echo $GOOGLE_ADS_DEVELOPER_TOKEN
   ```
2. If empty, set them using one of the methods above
3. Restart Flask app after setting variables

---

### Error: "No Google Ads accounts found"

**Problem**: User authorized but no accounts returned

**Possible Causes**:
1. Developer token in test mode (only works with test accounts)
2. User doesn't have Google Ads account
3. User doesn't have admin access to account

**Solution**:
1. Check if developer token is approved at [Google Ads API Center](https://ads.google.com/aw/apicenter)
2. Try with a different Google account that has Google Ads
3. Verify user has Standard or Admin access level

---

### Grader falls back to demo mode

**Problem**: Real analysis doesn't run, shows demo data

**Causes**:
- Environment variables not set
- OAuth not configured
- API error occurred

**Debug**:
1. Check Flask logs for errors
2. Verify environment variables: `echo $GOOGLE_ADS_CLIENT_ID`
3. Test OAuth by clicking "Connect Google Ads"
4. Check browser console for JavaScript errors

---

## Verification Checklist

Before going live:

- [ ] Environment variables set in production
- [ ] Redirect URI added to Google Cloud Console
- [ ] Dependencies installed (`pip list | grep google-ads`)
- [ ] Flask app restarted
- [ ] Visited https://fieldsprout.io/ads-grader
- [ ] Landing page loads correctly
- [ ] "Connect Google Ads" button works
- [ ] OAuth authorization completes
- [ ] Redirects back to fieldsprout.io
- [ ] Analysis runs with real data
- [ ] Report displays correctly
- [ ] Charts render (Quality Score, CTR, Keywords)
- [ ] PDF download works
- [ ] SSL/HTTPS working properly

---

## URLs

### Production URLs:
- **Landing page**: https://fieldsprout.io/ads-grader
- **OAuth callback**: https://fieldsprout.io/ads-grader/connect/callback
- **Report example**: https://fieldsprout.io/ads-grader/report/1
- **History**: https://fieldsprout.io/ads-grader/history

### Navigation:
The grader is linked in:
- ✓ Public navigation (base_public.html)
- ✓ App navigation (base_app.html)
- Both show "FREE" badge

---

## Security Notes

### SSL/HTTPS
- ✅ Production uses HTTPS (fieldsprout.io)
- ✅ OAuth requires HTTPS in production
- ✅ Cookies secured with HTTPS

### Credentials
- ⚠️ Never commit credentials to git (already in .gitignore)
- ⚠️ Rotate developer token periodically
- ⚠️ Monitor API usage in Google Cloud Console
- ⚠️ Set up alerts for quota limits

### Data Privacy
- ✅ Read-only access to Google Ads (cannot modify)
- ✅ Session-based authentication
- ✅ Reports only visible to owner or admin
- ✅ Anonymous users can use grader but reports expire

---

## Monitoring

### What to Monitor:

**Google Ads API Quota**:
- Default: 15,000 operations per day
- Monitor at: [Google Cloud Console → APIs & Services → Google Ads API](https://console.cloud.google.com)
- Set up quota alerts

**Error Logs**:
```bash
# Check Flask logs for errors
tail -f /var/log/flask/error.log
# or
journalctl -u your-flask-service -f
```

**Database**:
```sql
-- Check report count
SELECT COUNT(*) FROM google_ads_grader_report;

-- Recent reports
SELECT id, google_ads_account_name, overall_score, created_at
FROM google_ads_grader_report
ORDER BY created_at DESC
LIMIT 10;

-- View/download stats
SELECT
    AVG(view_count) as avg_views,
    AVG(pdf_download_count) as avg_downloads
FROM google_ads_grader_report;
```

---

## Marketing & Usage

### Promote the Tool:
- ✅ Link in main navigation (done)
- ✅ FREE badge to attract attention (done)
- 📧 Email to existing customers
- 📱 Social media posts
- 📝 Blog post announcement
- 🔗 Add to pricing page as free value-add

### Track Conversions:
- How many people use grader
- How many download PDF
- How many sign up after using grader
- Average score by industry/size

### Lead Generation:
- Reports with low scores (<60) = high-priority leads
- High wasted spend = urgent opportunity
- Follow up with recommendations implementation

---

## Support

### Common User Questions:

**Q: Is it really free?**
A: Yes, completely free. No credit card required.

**Q: What data do you access?**
A: Read-only access to performance metrics. We cannot make changes.

**Q: How often should I run analysis?**
A: Monthly for active accounts, quarterly for stable accounts.

**Q: Can I share the PDF?**
A: Yes! It's designed to be shareable with stakeholders.

---

## Next Steps

1. **Add redirect URI** to Google Cloud Console (CRITICAL)
2. **Set environment variables** on production server
3. **Deploy code** to fieldsprout.io
4. **Test thoroughly** with test account first
5. **Announce** to users via email/social
6. **Monitor** usage and conversions
7. **Iterate** based on user feedback

---

**Production URL**: https://fieldsprout.io/ads-grader

**Ready to generate leads!** 🚀

Last Updated: October 26, 2024
