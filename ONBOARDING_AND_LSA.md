# Onboarding & LSA Missed Call Alerts - Complete Documentation

## 📋 Overview

This document covers two major features added to FieldSprout:

1. **5-Minute Onboarding Flow** - Simplified setup for new users
2. **LSA Missed Call Alerts** - Automated detection and notification system

Both features align with the comprehensive UI/UX overhaul focused on SMB operators in the home services industry.

---

## 🚀 Feature 1: 5-Minute Onboarding Flow

### Purpose

Reduce signup friction and time-to-value for new users. Previous onboarding required too many steps and technical knowledge. New flow focuses on essentials only.

### User Flow

**Step 1: Business Basics** (Required: 2 fields)
- Business name
- Industry (dropdown: Plumbing, HVAC, Electrical, Pest Control, etc.)
- Phone number
- Website (optional)

**Step 2: Service Area** (Required: 2 fields)
- Service area (e.g., "Austin, TX metro")
- Primary goal (More calls / Reduce waste / Both)

**Step 3: Connect Google Ads**
- One-click Google Ads connection
- Can skip and connect later
- Redirects to OAuth flow if clicked

**Completion:**
- Auto-saves industry to account for vertical personalization
- Redirects to decision screen (`/account/google/ads/decision-screen`)
- Total time: ~3-5 minutes

### Technical Implementation

**New Template:**
- `flaskapp/templates/onboarding/quick_setup.html`
- Beautiful gradient design (indigo to purple)
- Progress bar with percentage (0%, 50%, 100%)
- Client-side validation before advancing steps
- AJAX save to `/onboarding/save` endpoint

**New Route:**
```python
@onboarding_bp.route("/quick-setup", methods=["GET"])
@login_required
def quick_setup():
    """5-minute onboarding flow"""
```

**New API Endpoint:**
```python
@api_bp.route('/account/update-industry', methods=['POST'])
@login_required
def update_industry():
    """Update account.industry field"""
```

**Blueprint Registration:**
- Added `api_bp` blueprint to `app/__init__.py`
- Registered at `/api` prefix
- Imported from `app.account`

### Industry Detection

The industry field enables vertical-specific language throughout the app:

- **Plumbing:** "emergency calls", "leak searches", "water heater intent"
- **HVAC:** "install requests", "emergency repair", "seasonal demand"
- **Pest Control:** "infestation calls", "inspection bookings", "seasonal pests"
- **Electrical:** "emergency electrician", "panel upgrades"
- **Default:** "service calls", "high-intent searches"

This personalization appears on:
- Decision screen
- AI change log
- Email notifications
- All Google Ads pages

### Key Features

✅ **Progress Tracking:** Visual bar shows 0%, 50%, 100%
✅ **Client-Side Validation:** Blocks advancement if required fields empty
✅ **Auto-Save Industry:** Updates `accounts.industry` via AJAX
✅ **Beautiful Design:** Gradient backgrounds, smooth transitions
✅ **Skip Option:** Can skip Google Ads connection
✅ **Mobile Responsive:** Works on all screen sizes

### Usage

**Direct Access:**
```
https://fieldsprout.io/onboarding/quick-setup
```

**After Signup:**
Redirect new users to this page instead of full dashboard

**Testing:**
```bash
# Visit in browser
open https://fieldsprout.io/onboarding/quick-setup

# Should see:
# - Step 1: Business basics
# - Progress bar at 0%
# - Beautiful gradient design
```

---

## 🚨 Feature 2: LSA Missed Call Alerts

### Purpose

Notify business owners immediately when they miss calls from Google Local Services Ads (LSA). Quick follow-up is critical - response within 5 minutes increases conversion by 400%.

### How It Works

**1. Detection:**
- Monitors `glsa_call_records` table
- Identifies missed calls by:
  - `outcome_label` contains: "missed", "no_answer", "voicemail", "abandoned"
  - `duration_sec` < 10 seconds (likely hung up)
  - Not yet `reviewed` (prevents duplicate alerts)

**2. Severity Classification:**
- **High:** Last 24 hours - immediate action required
- **Medium:** Last 7 days - follow up recommended
- **Low:** Older than 7 days - informational

**3. Email Notification:**
- Beautiful HTML email with gradient header
- Lists all missed calls with details:
  - Caller name
  - Phone number
  - Job type (e.g., "Plumbing Emergency")
  - City/location
  - Time of call
  - Call duration
- High-priority calls shown first with red badges
- Includes "Pro Tips" for callback best practices
- CTA button: "View All Missed Calls"

**4. Dashboard Alert:**
- Prominent widget on decision screen
- Red border with animated pulse/bounce
- Shows total missed calls count
- Lists up to 3 high-priority calls
- "Response within 5 minutes = 400% better conversion" tip
- Automatically turns status indicator RED when present

### Technical Implementation

**New Service File:**
`flaskapp/app/services/lsa_missed_call_service.py`

**Key Classes and Functions:**

```python
class MissedCallAlert:
    """Data model for a missed call"""

    @property
    def is_missed(self) -> bool:
        """Check if call was truly missed"""

    @property
    def is_short_duration(self) -> bool:
        """Check if duration < 10 seconds"""

    @property
    def severity(self) -> str:
        """Returns: 'high', 'medium', or 'low'"""

def detect_missed_calls(account_id: int, lookback_hours: int = 24) -> List[MissedCallAlert]:
    """Detect missed calls for account"""

def send_missed_call_notification(
    account_id: int,
    to_email: str,
    missed_calls: List[MissedCallAlert]
) -> bool:
    """Send beautiful HTML email notification"""

def check_and_notify_missed_calls(account_id: int, notification_email: str) -> int:
    """Main cron job function - check and notify"""

def get_recent_missed_calls_summary(account_id: int, days: int = 7) -> Dict:
    """Get summary for dashboard display"""
```

**Modified Files:**

1. **`app/google/__init__.py`** - Decision screen route updated:
```python
@google_bp.route("/ads/decision-screen")
def ads_decision_screen():
    # Check for LSA missed calls
    lsa_missed_calls = get_recent_missed_calls_summary(aid, days=7)

    # Change status to RED if high-priority missed calls exist
    if lsa_missed_calls and lsa_missed_calls.get('high_priority', 0) > 0:
        status = 'red'

    return render_template(
        "google/ads_decision_screen.html",
        lsa_missed_calls=lsa_missed_calls,
        ...
    )
```

2. **`templates/google/ads_decision_screen.html`** - Added alert widget:
```html
{% if lsa_missed_calls and lsa_missed_calls.total_missed > 0 %}
  <div class="rounded-xl border-2 border-red-300 bg-gradient-to-br from-red-50 to-orange-50 p-6 shadow-lg animate-pulse-slow">
    <!-- Alert content -->
  </div>
{% endif %}
```

### Database Schema

Uses existing tables - no migration required:

**`glsa_call_records` table:**
- `id` - Primary key
- `account_id` - Account identifier
- `lead_id` - Foreign key to `glsa_leads`
- `storage_url` - Recording URL
- `duration_sec` - Call duration in seconds
- `outcome_label` - "missed", "answered", "voicemail", etc.
- `outcome_reason` - Detailed reason
- `reviewed` - Boolean flag (prevents duplicate alerts)
- `created_at` - Timestamp

**`glsa_leads` table:**
- `id` - Primary key
- `name` - Caller name
- `phone` - Phone number
- `email` - Email address
- `job_type` - Service requested
- `city` - Location
- `lead_ts` - Lead timestamp

### Email Template

The email notification includes:

**Header:**
- Gradient background (red to orange)
- "🚨 Missed Call Alert - LSA" title
- Total missed calls count

**Content:**
- Alert box: "⚠️ Action Required"
- High-priority section (last 24 hours)
- Medium-priority section (this week)
- Each call shows:
  - Caller name with severity badge
  - Phone, job type, city
  - Duration and outcome
  - Timestamp

**Pro Tips Section:**
- Call back within 5 minutes for best results
- Reference the job type
- Have calendar ready
- Leave detailed voicemail + follow-up text

**Footer:**
- Link to dashboard
- Notification settings option

**Plain Text Version:**
Also includes plain text fallback for email clients that don't support HTML.

### Dashboard Widget

**Visual Design:**
- Red border (2px)
- Gradient background (red-50 to orange-50)
- Animated pulse effect
- Phone-slash icon with bounce animation

**Content:**
- Title: "🚨 Missed LSA Calls - Follow Up Now!"
- Badge with total count
- Explanation text
- High-priority calls list (up to 3)
- CTA button: "View All Missed Calls"
- Tip: "Response within 5 minutes = 400% better conversion"

**Behavior:**
- Only shows if `lsa_missed_calls.total_missed > 0`
- Automatically sets decision screen status to RED if high-priority calls exist
- Positioned prominently after Trust & Protection section
- Above the key metrics cards

### Cron Job Setup

**Recommended Schedule:** Every 15 minutes

**Script:**
```python
# scripts/check_lsa_missed_calls.py
from app import create_app
from app.services.lsa_missed_call_service import check_and_notify_missed_calls
from app.models import User, Account

app = create_app()

with app.app_context():
    # Get all active accounts
    accounts = Account.query.filter_by(status='active').all()

    for account in accounts:
        # Get owner user email
        owner = User.query.filter_by(
            account_id=account.id,
            role='owner'
        ).first()

        if owner and owner.email:
            # Check and notify
            missed_count = check_and_notify_missed_calls(
                account_id=account.id,
                notification_email=owner.email
            )

            if missed_count > 0:
                print(f"Account {account.id}: Sent notification for {missed_count} missed calls")
```

**Crontab Entry:**
```bash
# Run every 15 minutes
*/15 * * * * cd /path/to/flaskapp && /path/to/venv/bin/python scripts/check_lsa_missed_calls.py >> /var/log/lsa_missed_calls.log 2>&1
```

**Systemd Timer (Alternative):**
```ini
# /etc/systemd/system/lsa-missed-calls.timer
[Unit]
Description=Check LSA missed calls every 15 minutes

[Timer]
OnCalendar=*:0/15
Persistent=true

[Install]
WantedBy=timers.target
```

```ini
# /etc/systemd/system/lsa-missed-calls.service
[Unit]
Description=LSA Missed Call Checker

[Service]
Type=oneshot
User=www-data
WorkingDirectory=/path/to/flaskapp
ExecStart=/path/to/venv/bin/python scripts/check_lsa_missed_calls.py
```

### API Integration

**Get Missed Calls Summary (Dashboard):**
```python
from app.services.lsa_missed_call_service import get_recent_missed_calls_summary

summary = get_recent_missed_calls_summary(account_id=123, days=7)

# Returns:
{
    'total_missed': 5,
    'high_priority': 2,
    'medium_priority': 3,
    'missed_calls': [
        {
            'id': 456,
            'account_id': 123,
            'lead_name': 'John Smith',
            'lead_phone': '(512) 555-1234',
            'job_type': 'Emergency Plumbing',
            'city': 'Austin',
            'outcome_label': 'missed',
            'outcome_reason': 'No answer',
            'duration_sec': 8,
            'created_at': '2026-01-07T14:30:00',
            'severity': 'high',
            'recording_url': 'https://...'
        },
        # ... up to 10 most recent
    ],
    'period_days': 7
}
```

**Manual Notification Trigger:**
```python
from app.services.lsa_missed_call_service import (
    detect_missed_calls,
    send_missed_call_notification
)

# Detect missed calls
missed_calls = detect_missed_calls(account_id=123, lookback_hours=24)

if missed_calls:
    # Send notification
    success = send_missed_call_notification(
        account_id=123,
        to_email='owner@business.com',
        missed_calls=missed_calls
    )
```

### Testing

**1. Create Test Missed Call:**
```python
from app.models_glsa import GLSACallRecord, GLSALead
from app import db

# Create test lead
lead = GLSALead(
    account_id=123,
    glsa_account_id=1,
    lead_id='test-123',
    name='Test Customer',
    phone='(555) 123-4567',
    job_type='Plumbing Emergency',
    city='Austin'
)
db.session.add(lead)
db.session.flush()

# Create missed call record
call = GLSACallRecord(
    account_id=123,
    lead_id=lead.id,
    duration_sec=5,  # Short duration
    outcome_label='missed',
    outcome_reason='No answer',
    reviewed=False
)
db.session.add(call)
db.session.commit()
```

**2. Test Detection:**
```python
from app.services.lsa_missed_call_service import detect_missed_calls

missed = detect_missed_calls(account_id=123, lookback_hours=24)
print(f"Found {len(missed)} missed calls")

for call in missed:
    print(f"  - {call.lead.name}: {call.severity} severity")
```

**3. Test Email Notification:**
```python
from app.services.lsa_missed_call_service import send_missed_call_notification

success = send_missed_call_notification(
    account_id=123,
    to_email='your-email@example.com',
    missed_calls=missed
)

print(f"Email sent: {success}")
```

**4. Test Dashboard Display:**
```bash
# Navigate to decision screen
open https://fieldsprout.io/account/google/ads/decision-screen

# Should see:
# - Red alert widget if missed calls exist
# - Badge with count
# - List of high-priority calls
# - Status indicator should be RED
```

### Performance Considerations

**Query Optimization:**
- Indexed on `account_id`, `created_at`, `reviewed`
- Only queries last 24 hours by default
- Limits to 10 most recent for dashboard

**Email Rate Limiting:**
- Marks calls as `reviewed=True` after notification
- Prevents duplicate emails for same missed call
- Cron runs every 15 minutes (96 times/day max)

**Memory Usage:**
- Processes accounts one at a time
- Commits after each account
- No bulk loading of all calls

### Troubleshooting

**Issue: No emails being sent**

Check:
1. Brevo email service configured
2. `BREVO_API_KEY` in environment
3. Email logs: `grep -i "missed call" /var/log/flaskapp.log`
4. Cron job running: `systemctl status lsa-missed-calls.timer`

**Issue: Duplicate emails**

Check:
- `reviewed` flag being set correctly
- Database commits succeeding
- Cron not running multiple times

**Issue: Dashboard widget not showing**

Check:
1. `lsa_missed_calls` passed to template
2. `total_missed > 0` in summary
3. Template syntax correct
4. Browser console for errors

**Issue: Detection not finding calls**

Check:
1. `outcome_label` values in database
2. `reviewed` flag (should be False)
3. `created_at` timestamp (must be recent)
4. Account ID matching correctly

### Security Considerations

**Email Addresses:**
- Only send to verified account owners
- Check `email_verified` flag before sending
- Rate limit emails per account (max 1 per 15 min)

**PII Protection:**
- Phone numbers only in emails, not logs
- Recording URLs only accessible to account owner
- Caller names sanitized (no SQL injection)

**Access Control:**
- All routes require `@login_required`
- Check account ownership before showing data
- API endpoints validate account_id matches current_user

### Metrics to Track

**Email Performance:**
- Open rate
- Click-through rate to dashboard
- Time from email sent to callback made
- Conversion rate after callback

**Business Impact:**
- Missed calls detected per week
- Percentage of missed calls followed up
- Revenue recovered from callbacks
- Customer satisfaction scores

**System Performance:**
- Cron job execution time
- Email delivery rate
- Query performance (< 100ms ideal)
- False positive rate

---

## 📦 Deployment Checklist

### 1. Database Migration

Already completed - `industry` field added to `accounts` table.

```bash
# Verify migration
mysql -u [user] -p -e "DESCRIBE accounts;" | grep industry
```

### 2. Code Deployment

```bash
cd /path/to/flaskapp
git pull origin claude/limit-scraping-campaigns-0JNOv
```

### 3. Restart Application

```bash
sudo systemctl restart flaskapp
```

### 4. Set Up Cron Job

Create `/path/to/flaskapp/scripts/check_lsa_missed_calls.py` (see above)

Add to crontab:
```bash
*/15 * * * * cd /path/to/flaskapp && /path/to/venv/bin/python scripts/check_lsa_missed_calls.py >> /var/log/lsa_missed_calls.log 2>&1
```

### 5. Test Onboarding

1. Visit: `https://fieldsprout.io/onboarding/quick-setup`
2. Complete all 3 steps
3. Verify industry saved to account
4. Check redirect to decision screen

### 6. Test LSA Alerts

1. Create test missed call (see Testing section)
2. Run cron manually: `python scripts/check_lsa_missed_calls.py`
3. Check email inbox
4. Visit decision screen
5. Verify alert widget shows

### 7. Monitor Logs

```bash
# Watch for errors
tail -f /var/log/flaskapp.log | grep -i "lsa\|onboarding"

# Check cron job
tail -f /var/log/lsa_missed_calls.log
```

---

## 🎯 Success Metrics

### Onboarding

- **Goal:** Reduce time-to-value for new users
- **Target:** 90% completion rate
- **Metric:** Average completion time < 5 minutes
- **Track:** Conversions from onboarding to first campaign

### LSA Alerts

- **Goal:** Increase callback rate on missed calls
- **Target:** 60% callback rate within 1 hour
- **Metric:** Revenue recovered from callbacks
- **Track:** Email open rate, dashboard visits, call logs

---

## 💡 Future Enhancements

### Onboarding

- [ ] AI-powered business description generator
- [ ] Automatic service area detection (geolocation)
- [ ] Pre-fill from Google Business Profile
- [ ] Video tutorial integration
- [ ] Progress save/resume functionality

### LSA Alerts

- [ ] SMS notifications (in addition to email)
- [ ] Push notifications via mobile app
- [ ] Auto-dialer integration (click to call)
- [ ] AI-generated callback scripts
- [ ] Missed call trends and analytics dashboard
- [ ] Integration with CRM systems

---

## 📞 Support

### Documentation
- Main docs: `UI_UX_OVERHAUL.md`
- This file: `ONBOARDING_AND_LSA.md`
- API docs: (to be created)

### Logging
```bash
# Onboarding logs
grep -i "onboarding" /var/log/flaskapp.log

# LSA logs
grep -i "missed call" /var/log/flaskapp.log

# Email logs
grep -i "lsa.*email" /var/log/flaskapp.log
```

### Common Issues
See Troubleshooting sections above

---

**Created:** 2026-01-07
**Author:** Claude Code
**Branch:** `claude/limit-scraping-campaigns-0JNOv`
**Commits:**
- Onboarding & LSA: `fd4072a`
- UI/UX Overhaul: `cfe2bf2`
- Documentation: `27beb5a`
