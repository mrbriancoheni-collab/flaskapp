# Admin Bypass for Paid Features

## Overview

Admins (users with role "owner" or "admin") can now bypass all plan restrictions and access all paid features regardless of their account's plan level.

This allows:
- **Development & Testing**: Admins can test paid features without upgrading
- **Customer Support**: Support admins can access any account's features to help customers
- **Internal Use**: Team members with admin access can use all features

## What Gets Bypassed

### 1. **Paid Feature Access**
- All features gated behind `is_paid` checks in templates
- Paid-only navigation items (Optimize Profiles, Ads Optimizer, etc.)
- API access and advanced features
- Custom integrations and white-label options

### 2. **Team Seat Limits**
- Free plan: 1 seat → **Unlimited for admins**
- Starter plan: 3 seats → **Unlimited for admins**
- Growth plan: 10 seats → **Unlimited for admins**
- Professional plan: 25 seats → **Unlimited for admins**

### 3. **Feature-Specific Gates**
Any feature requiring a specific plan tier is automatically accessible to admins:
- Team collaboration (normally starter+)
- Advanced analytics (normally growth+)
- API access (normally professional+)
- White label (normally enterprise)
- Priority support (normally professional+)
- Custom integrations (normally enterprise)

## How It Works

### Admin Detection

A user is considered an admin if:
```python
user.is_admin == True
```

Which checks if:
```python
user.role in ("owner", "admin")
```

### Modified Functions

#### 1. `is_paid_account()` - `/app/auth/utils.py`
Returns `True` for admins regardless of account plan.

```python
def is_paid_account() -> bool:
    """Check if account is paid (admins always True)"""
    # Check if current user is admin
    user = getattr(g, 'user', None)
    if user and getattr(user, 'is_admin', False):
        return True

    # Normal plan check...
```

**Impact**: All `is_paid` checks in templates now pass for admins.

#### 2. `can_add_team_member()` - `/app/models_team.py`
Bypasses seat limits for admins.

```python
def can_add_team_member(account, current_user=None):
    """Check if can add team member (admins bypass limits)"""
    if current_user and getattr(current_user, 'is_admin', False):
        return True, None

    # Normal seat limit check...
```

**Impact**: Admins can add unlimited team members.

#### 3. New Helper Module - `/app/auth/plan_helpers.py`
Comprehensive plan access helpers with admin bypass:

```python
from app.auth.plan_helpers import (
    is_admin_user,           # Check if user is admin
    has_plan_access,         # Check plan tier with admin bypass
    can_access_feature,      # Check feature access with admin bypass
    require_plan_or_admin,   # Decorator for plan-gated routes
    require_feature_or_admin # Decorator for feature-gated routes
)
```

## Usage Examples

### In Route Handlers

```python
from app.auth.plan_helpers import require_plan_or_admin, require_feature_or_admin

# Require professional plan (admins bypass)
@app.route("/api/v1/data")
@require_plan_or_admin("professional")
def api_endpoint():
    return jsonify({"data": "..."})

# Require specific feature (admins bypass)
@app.route("/custom-reports")
@require_feature_or_admin("custom_reporting")
def custom_reports():
    return render_template("custom_reports.html")
```

### In Business Logic

```python
from app.auth.plan_helpers import has_plan_access, can_access_feature

# Check plan access
if has_plan_access("professional", account, user):
    # User has professional plan OR is admin
    enable_api_access()

# Check feature access
has_access, error_msg = can_access_feature("api_access", account, user)
if has_access:
    # User can access feature OR is admin
    provide_api_key()
else:
    flash(error_msg, "error")
```

### In Templates

The existing `is_paid` variable now automatically includes admin bypass:

```html
<!-- This now works for admins even on free accounts -->
{% if is_paid %}
  <a href="{{ url_for('glsa_bp.optimize') }}">
    Optimize Profiles
  </a>
{% else %}
  <span class="opacity-40">
    Optimize Profiles
    <i class="fa-solid fa-lock"></i>
  </span>
{% endif %}
```

### Programmatic Checks

```python
from app.auth.plan_helpers import is_admin_user

# Check if current user is admin
if is_admin_user():
    # Bypass any restriction
    grant_unlimited_access()

# Check if specific user is admin
if is_admin_user(some_user):
    # User is admin
    pass
```

## Testing Admin Bypass

### 1. Check Admin Status

Visit `/admin` - if you can access this, you're an admin.

### 2. Test Paid Features

1. Set your account plan to "free" in database:
```sql
UPDATE accounts SET plan = 'free' WHERE id = <your_account_id>;
```

2. As an admin user, you should still be able to:
   - Access all navigation items (no locks)
   - Add unlimited team members
   - Use API endpoints
   - Access advanced features

### 3. Verify Team Limits

```python
from app.models_team import can_add_team_member
from app.models import Account, User

account = Account.query.get(1)
admin_user = User.query.filter_by(role='admin').first()
normal_user = User.query.filter_by(role='member').first()

# Admin bypasses
can_add, _ = can_add_team_member(account, admin_user)
assert can_add == True  # Always true for admins

# Normal user respects limits
can_add, msg = can_add_team_member(account, normal_user)
# May be False if seat limit reached
```

## Security Considerations

### ✅ Safe Bypasses
- Internal testing and development
- Customer support scenarios
- Admin users are trusted team members

### ⚠️ Important Notes
1. **Billing still applies**: Admins bypass feature gates, but billing/payments still process normally
2. **Audit logs**: Admin actions are still logged for compliance
3. **Role management**: Only grant admin role to trusted team members
4. **Production caution**: Be careful when admins modify production data

### Admin Role Assignment

Only users with these roles bypass restrictions:
- **owner**: Account owner (highest privilege)
- **admin**: Administrator with elevated access
- **member**: Regular user (NO bypass)

Change a user's role:
```sql
UPDATE users SET role = 'admin' WHERE email = 'support@yourcompany.com';
```

## Migration Guide

### Existing Plan Checks

If you have existing plan checks in your code, you can:

#### Option 1: Use new helpers (recommended)
```python
# Old code
if account.plan in ['professional', 'enterprise']:
    enable_feature()

# New code
from app.auth.plan_helpers import has_plan_access
if has_plan_access('professional', account, user):
    enable_feature()  # Now includes admin bypass!
```

#### Option 2: Manual admin check
```python
# Add admin check to existing logic
if user.is_admin or account.plan in ['professional', 'enterprise']:
    enable_feature()
```

#### Option 3: Use decorators
```python
# Old code
@app.route("/premium-feature")
def premium_feature():
    if account.plan != 'professional':
        flash("Requires professional plan")
        return redirect(url_for('billing'))
    # ... feature logic

# New code
from app.auth.plan_helpers import require_plan_or_admin

@app.route("/premium-feature")
@require_plan_or_admin("professional")
def premium_feature():
    # Admins bypass automatically!
    # ... feature logic
```

## Troubleshooting

### Admin bypass not working?

1. **Check user role**:
```python
from flask import g
print(g.user.role)  # Should be 'owner' or 'admin'
print(g.user.is_admin)  # Should be True
```

2. **Verify database**:
```sql
SELECT id, email, role FROM users WHERE email = 'your@email.com';
```

3. **Clear session and re-login**:
Session may have cached old role value.

### Feature still locked?

1. **Check if using new helpers**: Old plan checks won't include bypass
2. **Template caching**: Restart Flask app to clear template cache
3. **JavaScript checks**: Client-side checks may still restrict UI

## Files Modified

1. `/app/auth/utils.py` - Updated `is_paid_account()` with admin bypass
2. `/app/models_team.py` - Updated `can_add_team_member()` with admin bypass
3. `/app/auth/permissions.py` - Pass `current_user` to seat check
4. `/app/team/routes.py` - Pass `current_user` to seat check
5. `/app/auth/plan_helpers.py` - New comprehensive helper module (NEW)

## Future Enhancements

Potential additions:
- **Temporary admin access**: Time-limited admin bypass for support
- **Feature-specific bypass**: Admin can access some features but not others
- **Bypass audit trail**: Log when admins use bypass to access features
- **Admin dashboard**: Show what features are being accessed via bypass

## Support

For questions about admin bypass:
- Check `/admin` dashboard for user role
- Review `ADMIN_BYPASS_README.md` (this file)
- Email: cs@fieldsprout.io
