# Email Workflow Conditional Branching

## Overview

This feature adds conditional branching to email workflows, allowing you to send different emails based on recipient engagement with previous emails in the workflow.

## Key Features

### 1. **Engagement-Based Branching**
Send different follow-up emails depending on whether recipients:
- ✅ Opened the previous email
- ❌ Did NOT open the previous email
- 🔗 Clicked a link in the previous email

### 2. **Flexible Wait Times**
Configure how long to wait before checking engagement conditions (default: 24 hours).

### 3. **Alternative Templates**
Specify a different email template to send if the condition is not met.

## How It Works

### Example Workflow

**Step 1:** Welcome Email (sent immediately)
- Template: "Welcome to FieldSprout"

**Step 2:** Check if Welcome Email was opened (wait 24 hours)
- **Condition:** `email_opened`
- **If opened:** Send "Getting Started Guide" (engaged users)
- **If NOT opened:** Send "Did you miss our welcome email?" (re-engagement)

**Step 3:** Check if link was clicked (wait 48 hours)
- **Condition:** `link_clicked`
- **If clicked:** Send "Advanced Features Tour"
- **If NOT clicked:** Send "Quick Start Video"

## Database Changes

### New Fields in `workflow_steps` Table

```sql
-- Condition type: what to check
condition_type ENUM('none', 'email_opened', 'email_not_opened', 'link_clicked')

-- How long to wait before checking the condition (in hours)
condition_wait_hours INT DEFAULT 24

-- Alternative template to send if condition is not met
alt_email_template_id INT NULL

-- Additional condition data (e.g., specific URL for link clicks)
condition_data JSON NULL
```

### New Fields in `workflow_enrollments` Table

```sql
-- Track which emails were sent at each step
step_history JSON NULL

-- Reference to the last email sent (for tracking opens/clicks)
last_email_sent_id INT NULL
```

## Configuration

### In the Admin UI

1. **Navigate to:** `/admin/email-workflows`
2. **Create or edit a workflow**
3. **Add a step** and configure:

#### Basic Settings
- **Email Template:** Primary template to send
- **Delay Days/Hours:** Base delay before sending

#### Conditional Branching (Optional)
- **Condition Type:**
  - `None` - No condition (always send primary template)
  - `Email was opened` - Send primary if previous email opened
  - `Email was NOT opened` - Send primary if previous email NOT opened
  - `Link was clicked` - Send primary if link clicked

- **Wait Time:** Hours to wait before checking condition (default: 24)
- **Alternative Template:** Template to send if condition NOT met
- **Specific URL:** (For `link_clicked` only) Check for specific URL

### Example JSON Configuration

```json
{
  "workflow_id": 1,
  "step_order": 2,
  "email_template_id": 5,
  "delay_days": 0,
  "delay_hours": 0,
  "condition_type": "email_opened",
  "condition_wait_hours": 24,
  "alt_email_template_id": 6,
  "condition_data": null
}
```

## Workflow Processing

### Automated Processing (Cron)

The workflow processor runs every minute and:

1. **Finds due enrollments** (`next_email_scheduled_at <= now`)
2. **Gets the next step** for each enrollment
3. **Checks conditions** (if any):
   - Queries `email_opens` table for open tracking
   - Queries `email_clicks` table for click tracking
4. **Determines which template** to send based on condition result
5. **Sends the email** with tracking enabled
6. **Updates enrollment** with:
   - New `current_step`
   - `last_email_sent_id` (for next condition check)
   - `step_history` (audit trail)
   - `next_email_scheduled_at` (for next step)

### Manual Trigger

```bash
# Process workflows immediately (useful for testing)
python -m flask cron-minutely
```

## Email Tracking Integration

### Tracking Pixel
All workflow emails include a 1x1 transparent GIF:
```html
<img src="https://yourdomain.com/track/pixel/TOKEN.gif" width="1" height="1" />
```

When opened, the tracking endpoint logs an `EmailOpen` record.

### Click Tracking
All links are automatically wrapped:
```html
<!-- Original -->
<a href="https://example.com/page">Click here</a>

<!-- Wrapped -->
<a href="https://yourdomain.com/track/click/TOKEN?url=https://example.com/page">Click here</a>
```

When clicked, the tracking endpoint logs an `EmailClick` record and redirects.

## Code Architecture

### Key Files

#### Models (`app/models.py`)
- `WorkflowStep` - Extended with conditional fields
- `WorkflowEnrollment` - Extended with tracking fields
- `EmailSent` - Tracks sent emails
- `EmailOpen` - Tracks email opens
- `EmailClick` - Tracks link clicks

#### Services
- `app/services/workflow_processor.py` - Main processing logic
- `app/services/email_service.py` - Email sending with tracking
- `app/services/email_tracking.py` - Tracking pixel/link helpers

#### Routes
- `app/admin/email_workflow_routes.py` - Admin UI endpoints

#### Templates
- `templates/admin/email_workflow/workflow_form.html` - Workflow editor UI

#### Cron
- `app/cron_tasks.py` - Scheduled workflow processing

### Processing Flow

```
1. Cron (every minute)
   └─> process_workflow_enrollments()
       └─> _process_enrollment() [for each due enrollment]
           ├─> _determine_template_for_step()
           │   └─> _check_condition()
           │       ├─> Query EmailOpen for opens
           │       └─> Query EmailClick for clicks
           ├─> _send_workflow_email()
           │   └─> send_tracked_email_to_crm_contact()
           │       ├─> Generate tracking token
           │       ├─> Inject tracking pixel
           │       ├─> Wrap links for click tracking
           │       └─> Send via email service
           └─> _schedule_next_email()
```

## Migration

### Run the Migration

```bash
# Apply the migration
mysql -u username -p database_name < migrations_sql/020_add_workflow_conditional_branching.sql

# Rollback if needed
mysql -u username -p database_name < migrations_sql/020_add_workflow_conditional_branching_rollback.sql
```

### Backward Compatibility

- Existing workflows continue to work without changes
- `condition_type` defaults to `'none'` for all existing steps
- No data migration required

## Use Cases

### 1. Lead Nurture Campaign
```
Day 0: Welcome email
Day 1: If opened → Product tour | If not → Re-send welcome
Day 3: If clicked → Demo booking | If not → Case studies
Day 7: If opened → Pricing info | If not → Unsubscribe warning
```

### 2. Onboarding Sequence
```
Day 0: Account created email
Day 1: If opened → Setup guide | If not → "Getting started" reminder
Day 3: If clicked setup link → Advanced features | If not → Video tutorial
Day 7: If engaged → Pro features | If not → Basic tips
```

### 3. Re-engagement Campaign
```
Day 0: "We miss you" email
Day 2: If opened → Special offer | If not → Stronger call-to-action
Day 5: If clicked → Reactivation bonus | If not → Final goodbye
```

## Performance Considerations

- **Cron Frequency:** Every minute (configurable)
- **Batch Size:** 50 emails per run (configurable via `max_per_run`)
- **Condition Checks:** Efficient indexed queries on `email_sent_id`
- **Tracking:** Minimal overhead (1 pixel + link wrapping)

## Testing

### Test a Simple Workflow

1. Create two email templates:
   - "Test Email 1" with subject "Hello {{first_name}}"
   - "Test Email 2" with subject "Follow-up for {{first_name}}"

2. Create a workflow:
   - Step 1: Send "Test Email 1" immediately
   - Step 2: Wait 1 hour, check if opened
     - If opened: Send "Test Email 2"
     - If NOT opened: Send "Test Email 1" again

3. Create a test contact in CRM
4. Enroll the contact in the workflow
5. Check email within 1 hour (open it)
6. Wait 1 hour
7. Verify you receive "Test Email 2"

### Test Conditional Logic

```python
# In Flask shell
from app.models import WorkflowEnrollment, EmailOpen
from app.services.workflow_processor import process_workflow_enrollments
from flask import current_app

# Process workflows manually
emails_sent = process_workflow_enrollments(current_app, max_per_run=10)
print(f"Sent {emails_sent} emails")

# Check enrollment status
enrollment = WorkflowEnrollment.query.get(1)
print(f"Current step: {enrollment.current_step}")
print(f"Step history: {enrollment.step_history}")
```

## Monitoring

### Check Workflow Status

```sql
-- Active enrollments
SELECT w.name, COUNT(*) as active_count
FROM workflow_enrollments e
JOIN email_workflows w ON e.workflow_id = w.id
WHERE e.status = 'active'
GROUP BY w.id, w.name;

-- Engagement rates
SELECT
  ws.workflow_id,
  ws.step_order,
  ws.condition_type,
  COUNT(DISTINCT we.id) as total_sent,
  COUNT(DISTINCT eo.email_sent_id) as opened,
  ROUND(COUNT(DISTINCT eo.email_sent_id) * 100.0 / COUNT(DISTINCT we.id), 2) as open_rate
FROM workflow_steps ws
JOIN workflow_enrollments we ON we.workflow_id = ws.workflow_id
  AND we.current_step >= ws.step_order
LEFT JOIN email_opens eo ON eo.email_sent_id = we.last_email_sent_id
WHERE ws.condition_type != 'none'
GROUP BY ws.workflow_id, ws.step_order, ws.condition_type;
```

## Troubleshooting

### Emails Not Sending

1. **Check cron is running:**
   ```bash
   # Manually trigger
   python -m flask cron-minutely
   ```

2. **Check enrollment status:**
   ```sql
   SELECT * FROM workflow_enrollments
   WHERE status = 'active'
   AND next_email_scheduled_at <= NOW();
   ```

3. **Check logs:**
   ```bash
   tail -f ~/app_error.log | grep WORKFLOW
   ```

### Conditions Not Working

1. **Verify tracking is enabled** in email templates
2. **Check EmailOpen records:**
   ```sql
   SELECT * FROM email_opens WHERE email_sent_id = <last_email_sent_id>;
   ```

3. **Check condition_wait_hours** hasn't expired yet

## Security Considerations

- ✅ Tracking tokens are cryptographically secure (64 bytes)
- ✅ All email content is sanitized before sending
- ✅ Rate limiting prevents abuse (50 emails/minute)
- ✅ Admin-only access to workflow configuration
- ✅ CSRF protection on all admin endpoints

## Future Enhancements

Potential improvements:
- [ ] A/B testing support (random template selection)
- [ ] Time-based conditions (send only during business hours)
- [ ] Lead score-based branching
- [ ] Multi-condition logic (AND/OR combinations)
- [ ] Workflow analytics dashboard
- [ ] Email preview before sending
- [ ] Pause/resume individual enrollments

## Support

For issues or questions:
- Check logs in `~/app_error.log`
- Review workflow configuration in admin UI
- Test with small batch first
- Contact development team if issues persist
