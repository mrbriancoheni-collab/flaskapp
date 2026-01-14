# Google Ads Navigation & UX Improvement Plan

## Current Google Ads Pages (Analysis)

### Primary Pages:
1. **`/account/google/ads`** (ads_ui) - Main dashboard
2. **`/account/google/ads/decision-screen`** - NEW: AI-powered decision dashboard
3. **`/account/google/ads/ai-change-log`** - Full log of all AI actions
4. **`/account/google/ads/opportunities`** - Optimization opportunities
5. **`/account/google/ads/structure`** - Account structure view
6. **`/account/google/ads/applied-optimizations`** - History of applied optimizations

### Support Pages:
- `/account/google/ads/start` - Getting started wizard
- `/account/google/ads/campaigns/paused` - Paused campaigns
- `/account/google/ads/campaign/wizard` - Campaign creation wizard

---

## Problem Identified

### Opportunities Page Confusion:
- **Before auto-executor**: Showed manual tasks users should do (add negative keywords, adjust bids, etc.)
- **After auto-executor**: Still showing tasks that are now handled automatically
- **Result**: User sees "Add negative keyword for 'plumber jobs'" but auto-executor already did it

### Navigation Flow Issues:
- No clear hierarchy or flow between pages
- Duplicate functionality (opportunities vs applied-optimizations vs ai-change-log)
- Users don't know where to go for what purpose

---

## Proposed Solution

### 1. **Redesign Opportunities Page**

**NEW Purpose:** Show ONLY manual tasks that require human decision-making

**Filter OUT (handled by auto-executor):**
- ✅ Negative keyword additions (auto-added every 4 hours)
- ✅ Pausing low-performing keywords (future: when confidence is high)
- ✅ Basic bid adjustments (future: when auto-enabled)

**Keep IN (require manual action):**
- ✅ Campaign structure improvements
- ✅ Ad copy suggestions
- ✅ Landing page recommendations
- ✅ New campaign creation
- ✅ Quality score fixes requiring content changes
- ✅ Geographic targeting adjustments
- ✅ Budget reallocation decisions (when amounts are significant)

**Add prominent banner:**
```
🤖 AI Auto-Protection Active
Your budget is being protected 24/7. Auto-executor has blocked 47 wasteful searches this month.
[View What AI Has Done →]
```

### 2. **Clear Page Hierarchy & Purpose**

```
┌─────────────────────────────────────────┐
│  /ads (Main Dashboard)                  │
│  → Overview, quick stats, status        │
│  → Primary landing page from nav        │
└─────────────────────────────────────────┘
           │
           ├─→ Decision Screen (NEW PRIMARY)
           │   Purpose: "What should I do today?"
           │   Shows: Status, AI actions, quick wins
           │   CTA: Manual tasks, AI log, structure
           │
           ├─→ Opportunities (Manual Tasks Only)
           │   Purpose: "What can I improve?"
           │   Shows: Tasks requiring human decision
           │   Filters out: Auto-executed tasks
           │
           ├─→ AI Change Log (Transparency)
           │   Purpose: "What has AI done for me?"
           │   Shows: All auto-executed actions
           │   Features: Undo, detailed reasoning
           │
           ├─→ Structure (Account Overview)
           │   Purpose: "How is my account organized?"
           │   Shows: Campaigns, ad groups, keywords
           │
           └─→ Applied Optimizations (History)
               Purpose: "What changes were made?"
               Shows: Manual + Auto actions history
```

### 3. **Navigation Improvements**

**Global Navigation Bar (in header):**
```
Google Ads ▼
  ├─ Dashboard          (/ads)
  ├─ Decision Screen    (/ads/decision-screen) ← NEW DEFAULT
  ├─ Opportunities      (/ads/opportunities)
  ├─ AI Actions Log     (/ads/ai-change-log)
  ├─ Account Structure  (/ads/structure)
  └─ Settings           (/ads/settings)
```

**Quick Actions Card (on decision-screen):**
```
┌──────────────────────────────────────┐
│ What would you like to do?           │
├──────────────────────────────────────┤
│ → See manual tasks to review         │ → /opportunities
│ → View all AI actions & undo         │ → /ai-change-log
│ → Explore account structure          │ → /structure
│ → Create new campaign                │ → /campaign/wizard
└──────────────────────────────────────┘
```

### 4. **Code Changes Required**

#### A. Update `ads_opportunities` route:

```python
# In app/google/__init__.py around line 3355

def is_auto_applicable(opp):
    """
    Determine if this optimization is handled by auto-executor.
    If True, it should NOT show on opportunities page.
    """
    opt_type = opp.get("optimization_type", "")
    title = opp.get("title", "").lower()

    # Auto-executor handles these automatically
    AUTO_EXECUTOR_TYPES = [
        'negative_keyword',           # Auto-added every 4 hours
        'starter_negative_keywords',  # Auto-added for new campaigns
    ]

    if opt_type in AUTO_EXECUTOR_TYPES:
        return True

    # Check for negative keyword variations in title
    if 'negative keyword' in title or 'block search' in title:
        return True

    return False

# Filter opportunities to EXCLUDE auto-executed tasks
manual_opportunities = [opp for opp in all_opportunities if not is_auto_applicable(opp)]

analysis["opportunities"] = manual_opportunities
analysis["auto_handled_count"] = len([o for o in all_opportunities if is_auto_applicable(o)])
```

#### B. Update `ads_opportunities.html` template:

Add banner at top:
```html
{% if connected and auto_handled_count > 0 %}
<div class="bg-blue-50 border-l-4 border-blue-400 p-4 mb-6">
  <div class="flex items-center justify-between">
    <div class="flex items-center">
      <i class="fa-solid fa-robot text-blue-600 text-2xl mr-3"></i>
      <div>
        <h3 class="font-semibold text-blue-900">AI Auto-Protection Active</h3>
        <p class="text-sm text-blue-700">
          Auto-executor is handling {{auto_handled_count}} optimizations automatically.
          Below are tasks that need your review.
        </p>
      </div>
    </div>
    <a href="{{ url_for('google_bp.ai_change_log') }}" class="btn-secondary">
      View AI Actions →
    </a>
  </div>
</div>
{% endif %}
```

#### C. Update Decision Screen navigation:

Make it the primary landing page for most users:
```python
# When user clicks "Google Ads" in nav, send them to decision-screen instead of /ads
# Update base template navigation
```

---

## Implementation Checklist

### Phase 1: Opportunities Page (Immediate)
- [ ] Update `is_auto_applicable()` to filter out auto-executor tasks
- [ ] Add `auto_handled_count` to template context
- [ ] Add banner showing AI is handling optimizations
- [ ] Add prominent link to AI Change Log
- [ ] Test with real data

### Phase 2: Navigation Flow (Next)
- [ ] Update global nav to make decision-screen more prominent
- [ ] Add breadcrumbs to all Google Ads pages
- [ ] Add "Quick Actions" card to decision-screen
- [ ] Ensure consistent back/next flow between pages

### Phase 3: Polish (Final)
- [ ] Add empty states for pages with no data
- [ ] Add loading states
- [ ] Add tooltips explaining each page's purpose
- [ ] Mobile responsive testing
- [ ] User testing & feedback

---

## Expected User Experience

### Before:
1. User clicks "Google Ads" → Goes to /ads (old dashboard)
2. Clicks "Opportunities" → Sees "Add negative keyword for 'plumber jobs'"
3. Confused: "Didn't AI do this already?"

### After:
1. User clicks "Google Ads" → Goes to decision-screen
2. Sees: "AI blocked 47 searches this month, $156 saved"
3. Clicks "Manual Tasks" → Only sees things requiring human decision
4. Clicks "What AI Did" → Full transparency log with undo option

---

## Metrics to Track

- Time to complete a task (should decrease)
- % of users visiting each page (understand primary flows)
- Undo rate on AI actions (measure trust)
- Support tickets about "duplicate tasks" (should go to zero)

---

## Priority: HIGH

This directly impacts:
- User trust in automation
- Platform differentiation
- Customer retention
- Support burden

Confusion about what's automated vs manual is a major UX issue that needs immediate fixing.
