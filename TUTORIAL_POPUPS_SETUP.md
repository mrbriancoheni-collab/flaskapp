# Tutorial Popups System - Setup Guide

A Pendo-style interactive onboarding and tutorial system for FieldSprout.

## Quick Start

### 1. Run Database Migration

```bash
# Apply the migration
psql -U your_user -d your_database -f migrations_sql/015_add_tutorial_popups_tables.sql
```

This creates:
- `tutorial_popups` table - stores popup definitions
- `tutorial_user_progress` table - tracks user views/dismissals
- Sample popups for the demo page

### 2. Access Admin Interface

Navigate to `/admin/tutorials` to manage your tutorial popups.

**Admin Features:**
- ✅ Create/edit/delete popups
- ✅ Toggle active status with one click
- ✅ Filter by page path or status
- ✅ View analytics (views, dismissals, completion rates)

### 3. Add to Any Page

To enable tutorial popups on a page, add this to your template:

```html
<!-- Include the library -->
<script src="{{ url_for('static', filename='js/tutorial-popups.js') }}"></script>

<!-- Initialize on page load -->
<script nonce="{{ g.csp_nonce }}">
  if (typeof TutorialPopups !== 'undefined') {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', function() {
        TutorialPopups.init();
      });
    } else {
      TutorialPopups.init();
    }
  }
</script>
```

## Creating a Tutorial Popup

### Via Admin UI

1. Go to `/admin/tutorials`
2. Click "New Popup"
3. Fill in the form:
   - **Unique Key**: `demo-feature-x` (lowercase, hyphens only)
   - **Title**: "Welcome to Feature X!"
   - **Content**: HTML content (p, strong, ul, li supported)
   - **Page Path**: `/account/google/ads/opportunities/demo`
   - **Target Selector**: `#myButton` or leave blank for modal
   - **Position**: top, bottom, left, right, or center
   - **Sequence Order**: 0, 1, 2... (for multi-step tours)
   - **Trigger Type**: page_load, click, hover, scroll, delay
   - **Theme**: default, primary, success, warning, info
   - **CTA Text**: "Got it!" (optional)
   - **Show Once**: Check to show only once per user

### Example: Welcome Modal

```
Key: welcome-modal
Title: Welcome! 👋
Content: <p>This is your <strong>dashboard</strong>. Here you can:</p>
         <ul class="list-disc pl-5">
           <li>View your campaigns</li>
           <li>Track performance</li>
           <li>Optimize ads</li>
         </ul>
Page Path: /dashboard
Target Selector: (blank for modal)
Position: center
Sequence Order: 0
Trigger Type: page_load
Theme: primary
CTA Text: Let's go!
Show Once: ✓
```

### Example: Feature Highlight

```
Key: new-feature-button
Title: Try Our New Feature! ⚡
Content: <p>Click here to access our brand new automation tools.</p>
Page Path: /account/campaigns
Target Selector: #automationButton
Position: bottom
Sequence Order: 0
Trigger Type: page_load
Theme: success
CTA Text: Check it out
Show Once: ✓
```

## Popup Properties

### Positioning
- **Modal (centered)**: Leave `Target Selector` blank and set `Position` to "center"
- **Attached to element**: Provide CSS selector in `Target Selector` (e.g., `#myButton`, `.feature-card`)

### Trigger Types
- **page_load**: Show immediately when page loads (default)
- **delay**: Show after N milliseconds (set in Trigger Value, e.g., `2000`)
- **click**: Show when target element is clicked (set selector in Trigger Value)
- **hover**: Show when hovering over target element
- **scroll**: Show when user scrolls to N% of page (e.g., `50` for 50%)

### Themes
- **default**: Gray header
- **primary**: Indigo gradient header
- **success**: Green gradient header
- **warning**: Orange gradient header
- **info**: Blue gradient header

### Sequence Order
Create multi-step tours by setting sequence order:
- Popup with `sequence_order: 0` shows first
- After dismissal, popup with `sequence_order: 1` shows
- And so on...

## Analytics

View popup performance at `/admin/tutorials/analytics`:

- **Unique Views**: Number of users who saw the popup
- **Total Impressions**: Total times shown (may be > views if shown multiple times)
- **Dismissals**: Users who completed/dismissed the popup
- **Completion Rate**: % of users who dismissed vs viewed

Good completion rates:
- ✅ 80%+ = Excellent
- ⚠️ 50-79% = Good
- ❌ <50% = Needs improvement

## API Endpoints

### Get Popups for Page
```javascript
GET /admin/api/tutorials/for-page?page_path=/your/page

Response:
[
  {
    "id": 1,
    "key": "welcome",
    "title": "Welcome!",
    "content": "<p>Hello</p>",
    "page_path": "/dashboard",
    "target_selector": null,
    "position": "center",
    "theme": "primary",
    // ... more fields
  }
]
```

### Track View
```javascript
POST /admin/api/tutorials/{popup_id}/track-view

Response:
{
  "success": true
}
```

### Track Dismissal
```javascript
POST /admin/api/tutorials/{popup_id}/track-dismiss
Content-Type: application/json

{
  "action": "close_button" | "cta_click" | "auto_dismiss" | "backdrop_click"
}

Response:
{
  "success": true
}
```

## Sample Popups

The migration includes 3 sample popups for the demo page:

1. **Welcome Modal** - Centered modal introducing the page
2. **Bulk Selection Tools** - Attached to the selection buttons
3. **Sticky Footer** - Explains the value tracking footer

## Customization

### Styling
Edit `/static/js/tutorial-popups.js` to customize:
- Colors and gradients
- Animation timing
- Shadow and border styles
- Font sizes

### Behavior
Modify `TutorialPopups` object in the JavaScript file to:
- Change animation durations
- Add new trigger types
- Customize positioning logic
- Add custom callbacks

## Best Practices

1. **Keep it short**: 2-3 sentences max per popup
2. **Use sequences**: Break long tours into 3-5 steps
3. **Show once**: Enable for introductory popups
4. **Target wisely**: Attach to the actual feature being explained
5. **Test themes**: Match popup theme to content urgency
6. **Monitor analytics**: Remove low-completion popups

## Troubleshooting

### Popup not showing?
- ✅ Check popup is active (`is_active = true`)
- ✅ Verify page path matches exactly
- ✅ If targeted, ensure CSS selector is correct
- ✅ Check browser console for errors
- ✅ Verify user hasn't already seen it (if `show_once = true`)

### Poor completion rates?
- 📝 Shorten content (aim for <50 words)
- 🎯 Improve targeting (attach to correct element)
- ⏱️ Adjust timing (maybe delay 2-3 seconds)
- 🎨 Try different theme
- ❌ Make dismissible if currently non-dismissible

### Script not loading?
- Verify file exists: `/static/js/tutorial-popups.js`
- Check CSP nonce is included in inline scripts
- Look for JavaScript errors in console

## Migration Rollback

If you need to remove the tutorial popup system:

```bash
psql -U your_user -d your_database -f migrations_sql/015_add_tutorial_popups_tables_rollback.sql
```

This will:
- Drop both tables
- Remove all popup data
- Remove triggers and functions

---

## Support

For questions or issues with the tutorial popup system:
1. Check admin logs for errors
2. Review browser console
3. Verify database migration completed successfully
4. Test with a simple modal popup first before complex sequences
