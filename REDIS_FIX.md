# Redis Connection Issue Fix

## Problem
The application was experiencing two issues:

### 1. Template Error (CRITICAL - FIXED)
**Error:** `jinja2.exceptions.UndefinedError: 'str object' has no attribute 'account'`

**Location:** `templates/google/account_setup_wizard.html:70`

**Cause:** The route `account_wizard_routes.py:wizard_home()` was passing `account_status` as a dictionary, but the template expected a list.

**Fix:** Changed `account_status` from a dictionary to a list containing one dictionary in `flaskapp/app/google/account_wizard_routes.py` line 43.

### 2. Redis DNS Resolution Failure (WARNING - NEEDS ENVIRONMENT FIX)
**Error:** `Error -2 connecting to redis-14047.c52.us-east-1-4.ec2.redns.redis-cloud.com:14047. Name or service not known.`

**Cause:** The REDIS_URL environment variable contains an invalid hostname. The domain appears to have a typo: `redns.redis-cloud.com` should likely be `redis.redis-cloud.com`.

**Impact:** Non-critical. The application is designed to handle Redis failures gracefully and falls back to in-memory storage for rate limiting.

## Required Action for Redis

The `REDIS_URL` environment variable needs to be corrected in the cPanel/hosting environment:

### Current (Incorrect):
```
redis://:<password>@redis-14047.c52.us-east-1-4.ec2.redns.redis-cloud.com:14047
```

### Should be (check with Redis Cloud dashboard):
```
redis://:<password>@redis-14047.c52.us-east-1-4.ec2.redis.redis-cloud.com:14047
```

**Note:** Verify the exact hostname in your Redis Cloud dashboard at https://app.redislabs.com/

## Steps to Fix Redis Connection

1. Log into your Redis Cloud account at https://app.redislabs.com/
2. Navigate to your database
3. Copy the correct connection string/endpoint
4. Update the `REDIS_URL` environment variable in cPanel:
   - Log into cPanel
   - Go to "Select PHP Version" or "MultiPHP Manager"
   - Click "Environment Variables" or "Options"
   - Update or add `REDIS_URL` with the correct connection string
5. Restart the application (touch tmp/restart.txt or restart through cPanel)

## Testing

After fixing the REDIS_URL, you should see in the logs:
```
[INFO] app: Connected to Redis
[INFO] app: Rate limit storage: redis://...
```

Instead of:
```
[WARNING] app: Redis probe failed: ...
[WARNING] app: Redis not available; continuing without app Redis client
[INFO] app: Rate limit storage: memory://
```

## Files Changed

- `flaskapp/app/google/account_wizard_routes.py` - Fixed template data structure
- `REDIS_FIX.md` - This documentation

## Verification

The template error has been fixed. To verify:
1. Restart the application
2. Navigate to `/account/google/ads/setup-wizard`
3. The page should load without errors
