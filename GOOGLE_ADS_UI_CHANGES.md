# Google Ads AI Actions UI - Implementation Guide

**Page:** https://fieldsprout.io/account/google/ads

## ✅ Changes Completed

### 1. **Backend API Endpoints**
**File:** `app/google/__init__.py`

#### GET `/account/google/ads/ai-actions`
Fetch AI actions with filtering and pagination.

**Query Parameters:**
- `status` - Filter by status (pending, executed, failed, undone)
- `action_type` - Filter by action type
- `limit` - Results per page (default 50, max 200)
- `offset` - Pagination offset

**Response:**
```json
{
  "ok": true,
  "actions": [{
    "id": 123,
    "action_type": "negative_keyword_added",
    "title": "Block Non-Purchase Intent: 'plumber jobs'",
    "description": "Blocked search term from triggering ads",
    "confidence_score": 0.92,
    "estimated_monthly_savings": 45.50,
    "reasoning": "Matches employment-seeking pattern; $45.50 spent, 0 conversions",
    "status": "executed",
    "executed_at": "2026-01-12T14:23:00Z",
    "can_undo": true,
    "campaign_name": "Plumbing Services - Austin",
    "before_value": null,
    "after_value": {"keyword": "plumber jobs", "match_type": "PHRASE"}
  }],
  "total": 127,
  "limit": 50,
  "offset": 0
}
```

#### GET `/account/google/ads/ai-actions/summary`
Get summary statistics for dashboard.

**Response:**
```json
{
  "ok": true,
  "summary": {
    "total_actions": 127,
    "total_savings": 3247.50,
    "recent_actions_7d": 23,
    "actions_by_type": {
      "negative_keyword_added": 80,
      "bid_adjusted": 30,
      "keyword_paused": 17
    },
    "recent_timeline": [/* last 10 actions */]
  }
}
```

#### POST `/account/google/ads/ai-actions/<id>/undo`
Undo an AI action by reversing it in Google Ads.

**Response:**
```json
{
  "ok": true,
  "message": "Successfully removed negative keyword 'plumber jobs'",
  "action": {/* updated action object with undone status */}
}
```

---

### 2. **Updated Page Routes**

#### `/account/google/ads` (redirects to decision screen)
Main Google Ads page - redirects to `/account/google/ads/decision-screen`

#### `/account/google/ads/decision-screen`
**Updated with real data** - Shows:
- Total AI actions taken
- Total wasted spend prevented (from estimated_monthly_savings)
- Blocked searches count
- Recent changes timeline (last 10 actions)
- Each timeline item includes:
  - Action title
  - Description
  - Estimated savings
  - Confidence score
  - Undo button (if undoable)
  - Time executed

**Data Source:**
```python
from app.models_ai_actions import AIAction

# Total actions
ai_actions_taken = AIAction.query.filter_by(
    account_id=aid, status='executed'
).count()

# Total savings
wasted_spend_prevented = db.session.query(
    func.sum(AIAction.estimated_monthly_savings)
).filter_by(account_id=aid, status='executed').scalar()

# Recent timeline
recent_actions = AIAction.query.filter_by(
    account_id=aid, status='executed'
).order_by(desc(AIAction.executed_at)).limit(10).all()
```

#### `/account/google/ads/ai-change-log`
**Updated with real data** - Complete AI action log page showing:
- Total actions
- Total savings
- Total blocks (negative keywords)
- Total optimizations (non-negative keyword actions)

**Data Source:** Same as decision screen, but for complete history.

---

### 3. **Database Models**
**File:** `app/models_ai_actions.py`

#### AIAction Model
Tracks all automated changes with:
- `action_type` - Type of change (negative_keyword_added, bid_adjusted, etc.)
- `title` - Human-readable title
- `description` - What changed
- `reasoning` - Why AI made this decision
- `confidence_score` - 0.0 to 1.0
- `estimated_monthly_savings` - Dollar amount
- `before_value` / `after_value` - JSON snapshots
- `status` - pending, executed, failed, undone
- `can_undo` - Boolean
- `executed_at` - Timestamp

---

## 🔨 Changes Needed

### 1. **Update Templates**

#### `templates/google/ads_decision_screen.html`
**What needs to be added:**

```html
<!-- Update the timeline section to include undo buttons -->
{% for change in recent_changes %}
<div class="timeline-item">
  <div class="timeline-icon {{ change.color }}">
    <i class="fas {{ change.icon }}"></i>
  </div>
  <div class="timeline-content">
    <div class="timeline-header">
      <h4>{{ change.title }}</h4>
      <span class="time">{{ change.time }}</span>
    </div>
    <p>{{ change.description }}</p>

    <!-- Add confidence score -->
    {% if change.confidence %}
    <div class="confidence-badge">
      <i class="fas fa-chart-line"></i> {{ (change.confidence * 100)|int }}% confidence
    </div>
    {% endif %}

    <!-- Add reasoning -->
    {% if change.reasoning %}
    <div class="reasoning">
      <strong>Why:</strong> {{ change.reasoning }}
    </div>
    {% endif %}

    <!-- Add savings -->
    {% if change.saved > 0 %}
    <div class="savings">
      <i class="fas fa-piggy-bank"></i> Saves ${{ change.saved|round(2) }}/month
    </div>
    {% endif %}

    <!-- Add undo button -->
    {% if change.can_undo %}
    <button class="btn btn-sm btn-outline-danger undo-action-btn"
            data-action-id="{{ change.action_id }}"
            data-title="{{ change.title }}">
      <i class="fas fa-undo"></i> Undo This Change
    </button>
    {% endif %}
  </div>
</div>
{% endfor %}

<!-- Add JavaScript for undo functionality -->
<script>
document.querySelectorAll('.undo-action-btn').forEach(btn => {
  btn.addEventListener('click', async function() {
    const actionId = this.dataset.actionId;
    const title = this.dataset.title;

    if (!confirm(`Are you sure you want to undo: "${title}"?`)) {
      return;
    }

    try {
      const response = await fetch(`/account/google/ads/ai-actions/${actionId}/undo`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        }
      });

      const data = await response.json();

      if (data.ok) {
        alert('Change undone successfully!');
        location.reload(); // Refresh to show updated state
      } else {
        alert('Error: ' + data.error);
      }
    } catch (error) {
      alert('Error undoing change: ' + error.message);
    }
  });
});
</script>
```

#### `templates/google/ai_change_log.html`
**What needs to be added:**

```html
<!-- Add filters -->
<div class="filters">
  <select id="action-type-filter">
    <option value="">All Actions</option>
    <option value="negative_keyword_added">Negative Keywords</option>
    <option value="bid_adjusted">Bid Adjustments</option>
    <option value="keyword_paused">Paused Keywords</option>
  </select>

  <select id="status-filter">
    <option value="executed">Executed</option>
    <option value="undone">Undone</option>
    <option value="failed">Failed</option>
  </select>
</div>

<!-- Add actions table with AJAX loading -->
<div id="actions-container">
  <!-- Actions will be loaded here via JavaScript -->
</div>

<!-- Add pagination -->
<div id="pagination-controls">
  <!-- Pagination will be added via JavaScript -->
</div>

<script>
let currentPage = 0;
const pageSize = 50;

async function loadActions() {
  const actionType = document.getElementById('action-type-filter').value;
  const status = document.getElementById('status-filter').value;

  const params = new URLSearchParams({
    limit: pageSize,
    offset: currentPage * pageSize,
    ...(actionType && { action_type: actionType }),
    ...(status && { status: status })
  });

  try {
    const response = await fetch(`/account/google/ads/ai-actions?${params}`);
    const data = await response.json();

    if (data.ok) {
      renderActions(data.actions);
      renderPagination(data.total);
    }
  } catch (error) {
    console.error('Error loading actions:', error);
  }
}

function renderActions(actions) {
  const container = document.getElementById('actions-container');

  if (actions.length === 0) {
    container.innerHTML = '<p class="text-muted">No actions found.</p>';
    return;
  }

  container.innerHTML = actions.map(action => `
    <div class="action-card">
      <div class="action-header">
        <h5>${action.title}</h5>
        <span class="badge badge-${getBadgeColor(action.status)}">${action.status}</span>
      </div>
      <p class="action-description">${action.description}</p>

      ${action.reasoning ? `
        <div class="action-reasoning">
          <strong>Reasoning:</strong> ${action.reasoning}
        </div>
      ` : ''}

      <div class="action-metrics">
        ${action.confidence_score ? `
          <span class="metric">
            <i class="fas fa-chart-line"></i> ${(action.confidence_score * 100).toFixed(0)}% confidence
          </span>
        ` : ''}

        ${action.estimated_monthly_savings ? `
          <span class="metric">
            <i class="fas fa-piggy-bank"></i> $${action.estimated_monthly_savings.toFixed(2)}/mo saved
          </span>
        ` : ''}

        ${action.executed_at ? `
          <span class="metric">
            <i class="far fa-clock"></i> ${new Date(action.executed_at).toLocaleString()}
          </span>
        ` : ''}
      </div>

      ${action.can_undo ? `
        <button class="btn btn-sm btn-outline-danger undo-btn"
                onclick="undoAction(${action.id}, '${action.title}')">
          <i class="fas fa-undo"></i> Undo
        </button>
      ` : ''}
    </div>
  `).join('');
}

function getBadgeColor(status) {
  const colors = {
    'executed': 'success',
    'pending': 'warning',
    'failed': 'danger',
    'undone': 'secondary'
  };
  return colors[status] || 'info';
}

async function undoAction(actionId, title) {
  if (!confirm(`Undo: "${title}"?`)) return;

  try {
    const response = await fetch(`/account/google/ads/ai-actions/${actionId}/undo`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'}
    });

    const data = await response.json();

    if (data.ok) {
      alert('Action undone successfully!');
      loadActions(); // Reload list
    } else {
      alert('Error: ' + data.error);
    }
  } catch (error) {
    alert('Error: ' + error.message);
  }
}

// Event listeners
document.getElementById('action-type-filter').addEventListener('change', () => {
  currentPage = 0;
  loadActions();
});

document.getElementById('status-filter').addEventListener('change', () => {
  currentPage = 0;
  loadActions();
});

// Load on page load
loadActions();
</script>
```

---

### 2. **Add CSS Styles**

Add to your main CSS or in template `<style>` block:

```css
/* Timeline styles */
.timeline-item {
  display: flex;
  gap: 1rem;
  margin-bottom: 1.5rem;
  padding-bottom: 1.5rem;
  border-bottom: 1px solid #eee;
}

.timeline-icon {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  flex-shrink: 0;
}

.timeline-icon.red { background: #dc3545; }
.timeline-icon.green { background: #28a745; }
.timeline-icon.yellow { background: #ffc107; }
.timeline-icon.blue { background: #007bff; }

.timeline-content {
  flex: 1;
}

.timeline-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.5rem;
}

.timeline-header h4 {
  margin: 0;
  font-size: 1rem;
  font-weight: 600;
}

.timeline-header .time {
  color: #6c757d;
  font-size: 0.875rem;
}

.confidence-badge, .reasoning, .savings {
  margin-top: 0.5rem;
  font-size: 0.875rem;
}

.confidence-badge {
  color: #007bff;
  font-weight: 500;
}

.reasoning {
  color: #6c757d;
  font-style: italic;
}

.savings {
  color: #28a745;
  font-weight: 600;
}

.undo-action-btn {
  margin-top: 0.5rem;
}

/* Action card styles */
.action-card {
  background: white;
  border: 1px solid #dee2e6;
  border-radius: 0.375rem;
  padding: 1rem;
  margin-bottom: 1rem;
}

.action-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.5rem;
}

.action-description {
  color: #6c757d;
  margin-bottom: 0.5rem;
}

.action-reasoning {
  background: #f8f9fa;
  padding: 0.5rem;
  border-left: 3px solid #007bff;
  margin: 0.5rem 0;
  font-size: 0.875rem;
}

.action-metrics {
  display: flex;
  gap: 1rem;
  flex-wrap: wrap;
  margin-top: 0.5rem;
}

.action-metrics .metric {
  font-size: 0.875rem;
  color: #6c757d;
}

.action-metrics .metric i {
  margin-right: 0.25rem;
}
```

---

### 3. **Test the Integration**

**Manual Testing Steps:**

1. **Run Database Migration**
```bash
python scripts/create_ai_tables.py
```

2. **Run Auto-Executor** (to generate test data)
```bash
python scripts/auto_execute_google_ads.py
```

3. **Visit Pages**
- https://fieldsprout.io/account/google/ads (should redirect to decision screen)
- https://fieldsprout.io/account/google/ads/decision-screen (should show real data)
- https://fieldsprout.io/account/google/ads/ai-change-log (should show full log)

4. **Test API Endpoints**
```bash
# Get actions
curl https://fieldsprout.io/account/google/ads/ai-actions

# Get summary
curl https://fieldsprout.io/account/google/ads/ai-actions/summary

# Undo action (replace 123 with real action ID)
curl -X POST https://fieldsprout.io/account/google/ads/ai-actions/123/undo
```

5. **Test Undo Functionality**
- Click "Undo" button on a timeline item
- Confirm the action
- Verify it's reversed in Google Ads
- Verify status changes to "undone" in UI

---

## 📊 Data Flow

```
Cron (Hourly)
    ↓
auto_execute_google_ads.py
    ↓
GoogleAdsAutoExecutor.auto_add_negative_keywords()
    ↓
Creates AIAction records in database
    ↓
Executes via Google Ads API
    ↓
Marks as 'executed'

User visits /account/google/ads
    ↓
Loads ads_decision_screen
    ↓
Queries AIAction model
    ↓
Displays recent timeline with undo buttons

User clicks "Undo"
    ↓
POST /ads/ai-actions/<id>/undo
    ↓
GoogleAdsAutoExecutor.undo_action()
    ↓
Reverses change via Google Ads API
    ↓
Marks action as 'undone'
    ↓
Returns success
```

---

## 🎯 Summary

### ✅ Completed
1. API endpoints for fetching, summarizing, and undoing AI actions
2. Database models for tracking all AI changes
3. Updated decision screen to show real data
4. Updated AI change log to show real statistics
5. Timeline data includes confidence, reasoning, savings

### 🔨 Still Needed
1. Update HTML templates to include undo buttons
2. Add JavaScript for AJAX loading of actions
3. Add CSS styling for timeline and action cards
4. Test complete flow end-to-end
5. Add error handling and loading states in UI

### 📝 Next Steps
1. Update `templates/google/ads_decision_screen.html` with undo UI
2. Update `templates/google/ai_change_log.html` with filtering/pagination
3. Test with real Google Ads account
4. Deploy to production
