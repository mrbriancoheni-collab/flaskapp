# Testing Checklist - Google SSO & Facebook Ads Grader

## Table of Contents
- [Pre-Deployment Checklist](#pre-deployment-checklist)
- [Environment Verification](#environment-verification)
- [Database Migration Tests](#database-migration-tests)
- [Google SSO Testing](#google-sso-testing)
- [Facebook Ads Grader Testing](#facebook-ads-grader-testing)
- [Integration Tests](#integration-tests)
- [Performance Tests](#performance-tests)
- [Security Tests](#security-tests)

---

## Pre-Deployment Checklist

### Required Environment Variables

Run this verification script:

```bash
#!/bin/bash
# test_env_vars.sh

echo "=== Environment Variables Check ==="

# Google OAuth (User Authentication)
if [ -z "$GOOGLE_CLIENT_ID" ]; then
  echo "❌ GOOGLE_CLIENT_ID not set"
else
  echo "✅ GOOGLE_CLIENT_ID: ${GOOGLE_CLIENT_ID:0:10}..."
fi

if [ -z "$GOOGLE_CLIENT_SECRET" ]; then
  echo "❌ GOOGLE_CLIENT_SECRET not set"
else
  echo "✅ GOOGLE_CLIENT_SECRET: ${GOOGLE_CLIENT_SECRET:0:10}..."
fi

# Facebook App
if [ -z "$FB_APP_ID" ]; then
  echo "❌ FB_APP_ID not set"
else
  echo "✅ FB_APP_ID: $FB_APP_ID"
fi

if [ -z "$FB_APP_SECRET" ]; then
  echo "❌ FB_APP_SECRET not set"
else
  echo "✅ FB_APP_SECRET: ${FB_APP_SECRET:0:10}..."
fi

# Redirect URIs
if [ -z "$FB_ADS_GRADER_REDIRECT_URI" ]; then
  echo "⚠️  FB_ADS_GRADER_REDIRECT_URI not set (will use demo mode)"
else
  echo "✅ FB_ADS_GRADER_REDIRECT_URI: $FB_ADS_GRADER_REDIRECT_URI"
fi

# Database
if [ -z "$DATABASE_URL" ]; then
  echo "⚠️  DATABASE_URL not set (using default)"
else
  echo "✅ DATABASE_URL: ${DATABASE_URL:0:20}..."
fi

echo "==================================="
```

**Run**: `chmod +x test_env_vars.sh && ./test_env_vars.sh`

### Python Dependencies Check

```bash
#!/bin/bash
# test_dependencies.sh

echo "=== Python Dependencies Check ==="

python3 -c "import flask; print('✅ Flask:', flask.__version__)" || echo "❌ Flask not installed"
python3 -c "import flask_sqlalchemy; print('✅ Flask-SQLAlchemy')" || echo "❌ Flask-SQLAlchemy not installed"
python3 -c "import werkzeug; print('✅ Werkzeug')" || echo "❌ Werkzeug not installed"
python3 -c "import requests; print('✅ Requests')" || echo "❌ Requests not installed"
python3 -c "import weasyprint; print('✅ WeasyPrint')" || echo "❌ WeasyPrint not installed"

# Facebook SDK
python3 -c "from facebook_business.api import FacebookAdsApi; print('✅ Facebook Business SDK')" || echo "❌ Facebook Business SDK not installed"

echo "==================================="
```

**Run**: `chmod +x test_dependencies.sh && ./test_dependencies.sh`

---

## Environment Verification

### 1. Check Blueprint Registration

```python
# test_blueprints.py
from app import create_app

app = create_app()

print("=== Registered Blueprints ===")
for blueprint_name, blueprint in app.blueprints.items():
    print(f"✅ {blueprint_name}: {blueprint.url_prefix}")

# Expected output should include:
# ✅ auth_bp: /auth
# ✅ fb_ads_grader_bp: /fb-ads-grader
# ✅ ads_grader_bp: /ads-grader (if exists)
```

**Run**: `python test_blueprints.py`

### 2. Check Database Connection

```python
# test_database.py
from app import create_app, db
from app.models import User
from app.models_oauth import UserOAuthProvider
from app.models_fb_ads_grader import FacebookAdsGraderReport

app = create_app()

with app.app_context():
    print("=== Database Connection Test ===")

    try:
        # Test connection
        db.session.execute('SELECT 1')
        print("✅ Database connection successful")

        # Check tables exist
        inspector = db.inspect(db.engine)
        tables = inspector.get_table_names()

        expected_tables = [
            'users',
            'user_oauth_providers',
            'facebook_ads_grader_reports',
            'google_ads_grader_reports'  # if exists
        ]

        for table in expected_tables:
            if table in tables:
                print(f"✅ Table exists: {table}")
            else:
                print(f"❌ Table missing: {table}")

    except Exception as e:
        print(f"❌ Database error: {e}")
```

**Run**: `python test_database.py`

---

## Database Migration Tests

### Manual Verification

```sql
-- Test migrations applied correctly

-- 1. Check user_oauth_providers table
DESCRIBE user_oauth_providers;
-- Expected columns: id, user_id, provider, provider_user_id, email, name, picture,
--                   access_token, refresh_token, token_expires_at, created_at, updated_at

-- 2. Check unique constraints
SHOW INDEX FROM user_oauth_providers;
-- Expected: uq_user_provider (user_id, provider)
--           uq_provider_user_id (provider, provider_user_id)

-- 3. Check facebook_ads_grader_reports table
DESCRIBE facebook_ads_grader_reports;
-- Expected: 12 section score columns (wasted_spend_score, creative_optimization_score, etc.)

-- 4. Test foreign key constraints
SELECT
    TABLE_NAME,
    COLUMN_NAME,
    CONSTRAINT_NAME,
    REFERENCED_TABLE_NAME,
    REFERENCED_COLUMN_NAME
FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME IN ('user_oauth_providers', 'facebook_ads_grader_reports')
  AND REFERENCED_TABLE_NAME IS NOT NULL;
```

### Rollback Test (Optional)

```sql
-- Test rollback capability
DROP TABLE IF EXISTS `user_oauth_providers`;
DROP TABLE IF EXISTS `facebook_ads_grader_reports`;

-- Re-run migrations
SOURCE migrations_sql/002_add_facebook_ads_grader_report.sql;
SOURCE migrations_sql/003_add_user_oauth_providers.sql;

-- Verify tables recreated successfully
SHOW TABLES LIKE '%oauth%';
SHOW TABLES LIKE '%facebook%';
```

---

## Google SSO Testing

### Test 1: Login Page Displays Google Button

**Manual Test**:
1. Navigate to `/login`
2. Verify "Sign in with Google" button appears
3. Verify Google logo SVG renders correctly
4. Verify divider text: "Or continue with email"
5. Verify email/password form still works

**Expected**:
- ✅ Google button at top
- ✅ Blue/white styling consistent with brand
- ✅ Divider separates OAuth from email login
- ✅ Email/password login still functional

### Test 2: Register Page Displays Google Button

**Manual Test**:
1. Navigate to `/register`
2. Verify "Sign up with Google" button appears
3. Verify same styling as login page
4. Verify email/password registration still works

**Expected**:
- ✅ Google button at top
- ✅ Consistent styling with login page
- ✅ Email/password registration functional

### Test 3: Google OAuth Flow - New User

**Manual Test**:
1. Click "Sign in with Google" on login page
2. Select Google account (use test account with no existing record)
3. Authorize permissions (email, profile)
4. Verify redirect to callback URL
5. Check user created in database

**Expected**:
- ✅ Redirects to Google OAuth consent screen
- ✅ Returns to `/auth/google/callback`
- ✅ User created in `users` table
- ✅ OAuth record created in `user_oauth_providers` table
- ✅ User logged in and redirected to dashboard
- ✅ Flash message: "Welcome! Your account has been created."

**Database Verification**:
```sql
-- Check user created
SELECT id, email, name, email_verified FROM users WHERE email = 'test@gmail.com';

-- Check OAuth provider linked
SELECT provider, provider_user_id, email, name
FROM user_oauth_providers
WHERE provider = 'google' AND email = 'test@gmail.com';
```

### Test 4: Google OAuth Flow - Existing User (Same Email)

**Manual Test**:
1. Create user with email `existing@gmail.com` via email/password
2. Sign out
3. Click "Sign in with Google" and use Google account with same email
4. Verify account linking

**Expected**:
- ✅ Google account linked to existing user
- ✅ User logged in to same account
- ✅ Flash message: "Your Google account has been linked."
- ✅ No duplicate user created

**Database Verification**:
```sql
-- Should be one user with two records: password auth + Google OAuth
SELECT COUNT(*) FROM users WHERE email = 'existing@gmail.com';
-- Expected: 1

SELECT provider FROM user_oauth_providers WHERE user_id = (
    SELECT id FROM users WHERE email = 'existing@gmail.com'
);
-- Expected: 'google'
```

### Test 5: Google OAuth Flow - Returning User

**Manual Test**:
1. User who previously signed up with Google
2. Sign out
3. Click "Sign in with Google" again
4. Verify seamless login

**Expected**:
- ✅ Existing user recognized
- ✅ Logged in immediately
- ✅ No duplicate records
- ✅ Redirected to intended page (if `next` parameter set)

### Test 6: CSRF Protection

**Security Test**:
1. Intercept OAuth callback URL
2. Modify `state` parameter
3. Submit modified URL

**Expected**:
- ✅ Error: "Invalid state parameter"
- ✅ User not logged in
- ✅ Logs security warning

### Test 7: Next Parameter Redirect

**Manual Test**:
1. Navigate to protected page: `/dashboard`
2. Get redirected to `/login?next=/dashboard`
3. Click "Sign in with Google"
4. Complete OAuth flow

**Expected**:
- ✅ After OAuth, redirected to `/dashboard` (not home)
- ✅ `next` parameter preserved through OAuth flow

### Test 8: Email Verified Flag

**Database Test**:
```sql
-- Users who sign up with Google should have email_verified=1
SELECT email, email_verified
FROM users
WHERE id IN (
    SELECT user_id FROM user_oauth_providers WHERE provider = 'google'
);
-- Expected: email_verified = 1 for all
```

---

## Facebook Ads Grader Testing

### Test 1: Landing Page Access

**Manual Test**:
1. Navigate to `/fb-ads-grader`
2. Verify page loads
3. Check "Connect Facebook Account" button
4. Verify responsive design (mobile/desktop)

**Expected**:
- ✅ Page renders without errors
- ✅ Facebook blue branding (#1877f2)
- ✅ CTA button prominent
- ✅ Mobile responsive

### Test 2: Demo Mode (No API Keys)

**Manual Test**:
1. Unset `FB_APP_ID` in environment
2. Restart app
3. Navigate to `/fb-ads-grader`
4. Click "Try Demo" button
5. Verify sample report generates

**Expected**:
- ✅ Demo button appears when API not configured
- ✅ Sample report with realistic data
- ✅ All 12 category scores displayed
- ✅ Charts render with demo data
- ✅ Grade: B (75/100) or similar

**Console Check**:
```python
# Should see in logs:
# "FB_APP_ID not configured, using demo mode"
```

### Test 3: OAuth Flow - Connect Facebook

**Manual Test** (requires real Facebook account):
1. Set `FB_APP_ID`, `FB_APP_SECRET`, `FB_ADS_GRADER_REDIRECT_URI`
2. Navigate to `/fb-ads-grader`
3. Click "Connect Facebook Account"
4. Authorize app with Facebook
5. Verify callback handling

**Expected**:
- ✅ Redirects to Facebook OAuth consent screen
- ✅ Permissions requested: `ads_read`, `ads_management`, `read_insights`
- ✅ Returns to `/fb-ads-grader/connect/callback`
- ✅ Access token stored in session
- ✅ Redirected to account selection (if multiple accounts)

### Test 4: Single Account - Direct Analysis

**Manual Test**:
1. Complete OAuth with account having only 1 ad account
2. Verify automatic redirect to analysis

**Expected**:
- ✅ Skips account selection page
- ✅ Immediately starts analysis
- ✅ Progress indicator during API fetching

### Test 5: Multiple Accounts - Selection Page

**Manual Test**:
1. Complete OAuth with account having 2+ ad accounts
2. Verify account selection page appears

**Expected**:
- ✅ `/fb-ads-grader/select-account` page loads
- ✅ All ad accounts listed with names and IDs
- ✅ Radio buttons or cards for selection
- ✅ "Analyze Account" button enabled on selection

### Test 6: Report Generation (Real API)

**Manual Test**:
1. Select ad account with 365 days of data
2. Submit analysis request
3. Wait for report generation

**Expected**:
- ✅ Loading indicator (30-60 seconds)
- ✅ API fetches data without errors
- ✅ Report generated and saved to database
- ✅ Redirected to `/fb-ads-grader/report/<report_id>`

**Performance**:
- ⏱️ Should complete in <2 minutes
- ⏱️ No timeout errors

### Test 7: Report Display - 12 Categories

**Manual Test**:
1. View generated report
2. Verify all sections present

**Expected Sections**:
- ✅ Overall Score and Grade (large display)
- ✅ Wasted Spend Analysis
- ✅ Creative Optimization
- ✅ Audience Targeting
- ✅ Relevance Score Optimization
- ✅ CTR Optimization
- ✅ Account Activity
- ✅ Ad Format Diversity
- ✅ Campaign Structure
- ✅ Landing Page Optimization
- ✅ Mobile Optimization
- ✅ Conversion Tracking
- ✅ ROAS Performance

**Each Section Should Have**:
- Score (0-100)
- Grade badge (color-coded)
- Description
- Recommendations (if applicable)

### Test 8: Chart Visualizations

**Manual Test**:
1. View report page
2. Scroll through charts
3. Verify all charts render

**Expected Charts** (4 total):
1. ✅ **Relevance Score Distribution** (bar chart)
   - X-axis: Score ranges (1-3, 4-6, 7-8, 9-10)
   - Y-axis: Number of ads
   - Data from `detailed_metrics.relevance_distribution`

2. ✅ **CTR by Device** (horizontal bar chart)
   - Mobile vs Desktop vs Tablet
   - Data from `detailed_metrics.device_performance`

3. ✅ **Performance by Placement** (bar chart)
   - Feed, Stories, Audience Network, etc.
   - Data from `detailed_metrics.placement_performance`

4. ✅ **ROAS by Campaign** (bar chart)
   - Top 10 campaigns by ROAS
   - Data from `detailed_metrics.campaigns`

**Interactivity**:
- ✅ Hover tooltips show exact values
- ✅ Responsive on mobile
- ✅ Chart.js renders without console errors

### Test 9: PDF Export

**Manual Test**:
1. On report page, click "Download PDF Report"
2. Verify PDF downloads

**Expected**:
- ✅ PDF file downloads (filename: `facebook-ads-report-<id>.pdf`)
- ✅ PDF contains all report content
- ✅ Charts rendered as images in PDF
- ✅ Formatting maintained (headers, colors, layout)
- ✅ File size reasonable (<5MB)

**PDF Content Checklist**:
- ✅ Report header with logo
- ✅ Overall score and grade
- ✅ All 12 category scores
- ✅ Charts included
- ✅ Recommendations section
- ✅ Footer with generation date

**Database Tracking**:
```sql
-- PDF download count should increment
SELECT pdf_download_count FROM facebook_ads_grader_reports WHERE id = <report_id>;
-- Before: 0, After: 1
```

### Test 10: Report History (Logged-in Users)

**Manual Test**:
1. Login as user
2. Generate 2+ Facebook Ads reports
3. Navigate to `/fb-ads-grader/history`

**Expected**:
- ✅ All user's reports listed
- ✅ Sorted by date (newest first)
- ✅ Shows: account name, date, overall score, grade
- ✅ "View Report" links work
- ✅ Empty state if no reports

### Test 11: Anonymous User Report Access

**Manual Test**:
1. Generate report without logging in
2. Note the report URL
3. Sign out (clear session)
4. Try to access same report URL

**Expected**:
- ✅ Report accessible via direct URL
- ✅ No authentication required
- ✅ Session-based access control (if implemented)

### Test 12: 365 Days Data Verification

**Database Test**:
```python
# test_365_days_data.py
from app import create_app, db
from app.models_fb_ads_grader import FacebookAdsGraderReport
import json

app = create_app()

with app.app_context():
    report = FacebookAdsGraderReport.query.first()

    if report:
        print("=== 365 Days Data Verification ===")

        # Check date range
        start = report.date_range_start
        end = report.date_range_end
        days = (end - start).days

        print(f"Date range: {start} to {end}")
        print(f"Days of data: {days}")

        if days >= 365:
            print("✅ 365+ days of data collected")
        else:
            print(f"❌ Only {days} days of data")

        # Check detailed_metrics has comprehensive data
        if report.detailed_metrics:
            metrics = json.loads(report.detailed_metrics)

            expected_keys = [
                'account_info',
                'performance',
                'campaigns',
                'ad_sets',
                'ads',
                'creative_performance',
                'placement_performance',
                'device_performance'
            ]

            for key in expected_keys:
                if key in metrics:
                    print(f"✅ {key} data present")
                else:
                    print(f"❌ {key} data missing")
```

**Run**: `python test_365_days_data.py`

---

## Integration Tests

### Test 1: Google SSO + Facebook Ads Grader

**User Journey Test**:
1. New user clicks "Sign in with Google" from `/fb-ads-grader`
2. Complete Google OAuth
3. Immediately start Facebook Ads analysis
4. Generate report
5. View report history

**Expected**:
- ✅ Seamless flow from landing page → SSO → analysis → report
- ✅ User created and authenticated
- ✅ Report associated with user account
- ✅ Report appears in user's history

### Test 2: Cross-Tool Navigation

**Manual Test**:
1. Navigate to `/ads-grader` (Google Ads Grader)
2. Use navigation menu to access `/fb-ads-grader`
3. Verify both tools accessible from nav

**Expected**:
- ✅ Both graders in "Free Tools" section
- ✅ Color-coded links (Google green, Facebook blue)
- ✅ FREE badges displayed
- ✅ Desktop and mobile navigation work

### Test 3: Logged-in vs Anonymous Experience

**Test Scenarios**:

**Scenario A: Logged-in User**
1. Login with email/password or Google SSO
2. Generate Facebook Ads report
3. Check report saved to history

**Scenario B: Anonymous User**
1. Access `/fb-ads-grader` without login
2. Generate report
3. Verify report accessible but not in persistent history

**Expected Differences**:
- ✅ Logged-in: `user_id` populated in database
- ✅ Anonymous: `user_id` NULL in database
- ✅ Both can generate and view reports
- ✅ Only logged-in users see history page

---

## Performance Tests

### Load Time Benchmarks

```bash
#!/bin/bash
# test_performance.sh

echo "=== Performance Benchmarks ==="

# Landing page load
echo "Testing /fb-ads-grader..."
time curl -s https://fieldsprout.io/fb-ads-grader > /dev/null
# Target: <2 seconds

# Report generation (with real API)
echo "Testing report generation..."
# Start timer, trigger analysis, end timer
# Target: <90 seconds for full 365-day analysis

# PDF generation
echo "Testing PDF generation..."
# Target: <10 seconds for PDF export
```

### Database Query Performance

```sql
-- Test index effectiveness

-- 1. Find reports by user (should use idx_user_id)
EXPLAIN SELECT * FROM facebook_ads_grader_reports WHERE user_id = 123;
-- Expected: Using index

-- 2. Find reports by ad account (should use idx_fb_ad_account_id)
EXPLAIN SELECT * FROM facebook_ads_grader_reports WHERE fb_ad_account_id = 'act_123';
-- Expected: Using index

-- 3. Recent reports (should use idx_created_at)
EXPLAIN SELECT * FROM facebook_ads_grader_reports ORDER BY created_at DESC LIMIT 10;
-- Expected: Using index for sorting
```

### API Rate Limit Handling

**Manual Test**:
1. Generate 10 Facebook Ads reports rapidly
2. Monitor for rate limit errors
3. Verify retry logic works

**Expected**:
- ✅ Graceful handling if rate limit hit
- ✅ Exponential backoff retry logic
- ✅ User sees informative error message
- ✅ Reports eventually succeed

---

## Security Tests

### Test 1: SQL Injection Protection

**Test Inputs**:
```python
# Try malicious inputs in forms
malicious_inputs = [
    "' OR '1'='1",
    "'; DROP TABLE users; --",
    "1' UNION SELECT * FROM users--"
]

# Test in:
# - Login email field
# - Register email/name fields
# - Report search/filter (if implemented)
```

**Expected**:
- ✅ All malicious inputs sanitized
- ✅ SQLAlchemy ORM prevents injection
- ✅ No database errors logged

### Test 2: CSRF Protection

**Manual Test**:
1. Inspect login/register forms
2. Verify CSRF token present
3. Try submitting form without token

**Expected**:
- ✅ CSRF token in all forms
- ✅ Submission fails without valid token
- ✅ Error: "CSRF token missing or invalid"

### Test 3: OAuth State Validation

**Security Test**:
1. Initiate Google OAuth flow
2. Note state parameter in session
3. Modify state in callback URL
4. Submit modified callback

**Expected**:
- ✅ Error: "Invalid state parameter"
- ✅ User not authenticated
- ✅ Security event logged

### Test 4: Password-less User Security

**Database Test**:
```sql
-- Users created via Google SSO should have random password hash
SELECT email, LENGTH(password_hash) AS hash_length
FROM users
WHERE id IN (
    SELECT user_id FROM user_oauth_providers WHERE provider = 'google'
);

-- Expected: hash_length > 50 (bcrypt hash of random token)
```

**Login Test**:
1. Create user with Google SSO
2. Note email address
3. Try to login with email/password (any password)

**Expected**:
- ✅ Login fails (no password set)
- ✅ User must use "Sign in with Google"
- ✅ Or use "Forgot Password" to set password

### Test 5: Session Security

**Manual Test**:
1. Login as user
2. Copy session cookie
3. Logout
4. Try to reuse old session cookie

**Expected**:
- ✅ Old session invalidated
- ✅ Cookie not accepted
- ✅ Redirected to login

### Test 6: Access Control

**Authorization Tests**:

**Test 6a: View Other User's Report**
1. User A generates report (ID: 123)
2. User B tries to access `/fb-ads-grader/report/123`

**Expected**:
- If report is anonymous: ✅ Accessible (public)
- If report tied to user: ⚠️ May need access control logic

**Test 6b: Admin Functions** (if implemented)
1. Regular user tries to access `/admin/reports`
2. Verify unauthorized

**Expected**:
- ✅ 403 Forbidden or redirect to login
- ✅ Admin-only routes protected

---

## Automated Test Suite

### Unit Tests

```python
# tests/test_google_oauth.py
import unittest
from app.auth.google_oauth import GoogleAuthHelper

class TestGoogleOAuth(unittest.TestCase):

    def test_get_authorization_url(self):
        """Test Google OAuth URL generation"""
        with app.test_request_context():
            url = GoogleAuthHelper.get_authorization_url()

            self.assertIn('accounts.google.com/o/oauth2/v2/auth', url)
            self.assertIn('client_id=', url)
            self.assertIn('redirect_uri=', url)
            self.assertIn('state=', url)

    def test_state_token_security(self):
        """Test state token is random and stored in session"""
        with app.test_request_context():
            from flask import session

            url1 = GoogleAuthHelper.get_authorization_url()
            state1 = session.get('google_auth_state')

            url2 = GoogleAuthHelper.get_authorization_url()
            state2 = session.get('google_auth_state')

            # State tokens should be different each time
            self.assertNotEqual(state1, state2)

            # State should be 32+ characters (secure)
            self.assertGreater(len(state1), 32)

if __name__ == '__main__':
    unittest.main()
```

### Integration Tests

```python
# tests/test_fb_ads_grader_flow.py
import unittest
from app import create_app, db
from app.models_fb_ads_grader import FacebookAdsGraderReport

class TestFacebookAdsGraderFlow(unittest.TestCase):

    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()

    def tearDown(self):
        db.session.remove()
        self.app_context.pop()

    def test_landing_page(self):
        """Test landing page loads"""
        response = self.client.get('/fb-ads-grader')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Facebook Ads Grader', response.data)

    def test_demo_mode(self):
        """Test demo mode when API not configured"""
        # Unset FB_APP_ID in test config
        response = self.client.get('/fb-ads-grader/demo')
        self.assertEqual(response.status_code, 200)

        # Check demo report created
        report = FacebookAdsGraderReport.query.filter_by(
            fb_ad_account_id='DEMO'
        ).first()
        self.assertIsNotNone(report)
        self.assertEqual(report.overall_grade, 'B')

    def test_report_persistence(self):
        """Test report is saved to database"""
        # Create test report
        report = FacebookAdsGraderReport(
            fb_ad_account_id='act_test_123',
            overall_score=85.5,
            overall_grade='B+',
            wasted_spend_score=90,
            # ... other fields
        )
        db.session.add(report)
        db.session.commit()

        # Retrieve and verify
        retrieved = FacebookAdsGraderReport.query.filter_by(
            fb_ad_account_id='act_test_123'
        ).first()

        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.overall_score, 85.5)
        self.assertEqual(retrieved.overall_grade, 'B+')

if __name__ == '__main__':
    unittest.main()
```

---

## Final Checklist

Before pushing to production:

### Code Quality
- [ ] All Python files follow PEP 8
- [ ] No hardcoded secrets in code
- [ ] Environment variables documented
- [ ] Error handling comprehensive
- [ ] Logging implemented for key actions

### Database
- [ ] All migrations applied successfully
- [ ] Foreign keys and indexes working
- [ ] Backup strategy in place
- [ ] Test data can be cleared

### Security
- [ ] CSRF protection enabled
- [ ] OAuth state validation working
- [ ] Session cookies secure (HttpOnly, Secure flags)
- [ ] No sensitive data in client-side code
- [ ] API credentials in environment variables only

### Functionality
- [ ] Google SSO works (new user, existing user, returning user)
- [ ] Facebook Ads Grader generates reports
- [ ] Charts render correctly
- [ ] PDF export works
- [ ] Report history accessible
- [ ] Navigation links functional
- [ ] Mobile responsive

### Performance
- [ ] Page load <3 seconds
- [ ] Report generation <2 minutes
- [ ] PDF generation <10 seconds
- [ ] Database queries optimized (indexes used)

### Documentation
- [ ] README updated
- [ ] API documentation complete
- [ ] Environment variables documented
- [ ] Troubleshooting guide available

### Monitoring
- [ ] Error logging configured
- [ ] Performance monitoring setup
- [ ] OAuth flow tracked
- [ ] Report generation success rate tracked

---

## Post-Deployment Verification

After deploying to production:

```bash
#!/bin/bash
# post_deploy_check.sh

echo "=== Post-Deployment Verification ==="

# 1. Health check
curl -I https://fieldsprout.io/fb-ads-grader
# Expected: 200 OK

# 2. Check Google SSO redirect
curl -I "https://fieldsprout.io/auth/google"
# Expected: 302 Redirect to accounts.google.com

# 3. Check Facebook OAuth redirect
curl -I "https://fieldsprout.io/fb-ads-grader/connect"
# Expected: 302 Redirect to facebook.com

# 4. Database connection
# (Run from app server)
python -c "from app import db; db.session.execute('SELECT 1'); print('✅ DB Connected')"

# 5. Check logs for errors
tail -n 100 /var/log/flaskapp/error.log | grep -i error

echo "==================================="
```

### Smoke Tests (First 24 Hours)

- [ ] 10+ successful Google SSO logins
- [ ] 5+ Facebook Ads reports generated
- [ ] 3+ PDF downloads
- [ ] No critical errors in logs
- [ ] Average response time <3s
- [ ] No database connection issues

---

## Support

For issues during testing:
- **Database errors**: Check migration files and connection string
- **OAuth errors**: Verify redirect URIs match exactly
- **API errors**: Check Facebook App status and permissions
- **Chart errors**: Verify Chart.js CDN accessible and data format
- **PDF errors**: Check WeasyPrint dependencies installed

**Test Environment**: Use staging environment with test Facebook App and Google OAuth Client

**Production Rollout**: Consider phased rollout (10% → 50% → 100% of users)
