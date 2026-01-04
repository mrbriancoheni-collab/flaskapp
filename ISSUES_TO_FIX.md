# Issues to Fix

## Summary
User reported several issues across different pages that need attention.

## Issues List

### 1. ✅ Remove non-core 20 lead campaigns from database
**Status:** Script created
**File:** `cleanup_old_campaigns.py`
**Action Required:** Run the script in production to clean up old campaigns
```bash
python3 cleanup_old_campaigns.py
```

### 2. ✅ Bulk action buttons on lead campaigns page
**Status:** Already implemented
**Location:** `/admin/lead-campaigns/`
**Details:** Buttons for bulk scrape, enrich, and send emails are already at the top of the page and functional.

### 3. 🔧 Non-working buttons on Google Ads page
**Status:** Investigating
**URL:** `https://fieldsprout.io/account/google/ads`
**File:** `/home/user/flaskapp/flaskapp/templates/google/ads/optimize.html`
**Action Required:** Need to identify which specific buttons aren't working

### 4. 🔧 List all GMB accounts with access
**Status:** Pending
**URL:** `https://fieldsprout.io/account/gmb/`
**Action Required:** Ensure all GMB accounts user has access to are displayed for editing

### 5. 🔧 LinkedIn posts not displaying after form submit
**Status:** Pending
**URL:** `https://fieldsprout.io/account/linkedin/post-generator?...`
**Action Required:** Fix post generator to display generated posts after form submission

### 6. 🔧 500 error on LinkedIn categories page
**Status:** Pending
**URL:** `https://fieldsprout.io/account/linkedin/categories`
**Action Required:** Debug and fix 500 internal server error

### 7. 🔧 QA all pages
**Status:** Pending
**Action Required:** Run through all pages and test functionality

## Priority Order
1. Fix 500 error on LinkedIn categories (critical error)
2. Fix LinkedIn post generator (broken UX)
3. Fix GMB account listing (data access issue)
4. Fix Google Ads buttons (functionality issue)
5. QA all pages (general quality check)

## Next Steps
1. Investigate each issue systematically
2. Create fixes
3. Test locally if possible
4. Commit and push changes
5. Deploy to production
