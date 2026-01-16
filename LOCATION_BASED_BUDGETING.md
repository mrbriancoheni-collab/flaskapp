# Location-Based Budget Management

Comprehensive guide for managing Google Ads budgets by geographic location.

## Overview

The location-based budgeting system allows you to:
- Create budget groups targeted to specific locations (cities, states, DMAs, etc.)
- Allocate different budgets to different geographic markets
- Track performance metrics broken down by location
- Set location-specific rules and alerts
- Auto-adjust budgets based on location performance
- Monitor pacing by location to optimize spend

## Key Features

### 1. **Location-Targeted Budget Groups**

Create budget groups for specific geographic markets:

```
Examples:
- "Nashville Market - $10,000/mo" (City)
- "Tennessee Statewide - $15,000/mo" (State)
- "37203 ZIP - $5,000/mo" (ZIP Code)
- "Nashville DMA - $12,000/mo" (DMA/Metro Area)
- "10-mile radius from downtown - $8,000/mo" (Radius)
```

**Fields:**
- `target_location`: Geographic target name (e.g., "Nashville, TN")
- `location_type`: Type of targeting (city, state, zip, dma, radius, country, custom)
- `location_radius_miles`: Radius in miles (for radius targeting)
- `location_criteria_ids`: Google Ads location criterion IDs for auto-assignment

### 2. **Location Performance Tracking**

Track performance metrics by location within each budget group:

**Metrics Tracked:**
- Spend (by location)
- Impressions
- Clicks
- Conversions
- Calls
- CTR (Click-through rate)
- CPC (Cost per click)
- CPL (Cost per lead)
- Conversion rate
- Pacing status (under, on_track, over, paused)

**Table:** `budget_group_location_performance`

### 3. **Location-Specific Rules**

Define custom rules for each location:

**Rule Options:**
- Monthly budget allocation per location
- Priority (higher priority locations get budget first)
- Max CPL threshold (alert if exceeded)
- Min conversion rate threshold
- Target ROAS
- Auto-pause on threshold breach
- Auto-increase budget when performing well
- Budget increase percentage

**Table:** `budget_group_location_rules`

**Example:**
```json
{
  "location_name": "Nashville, TN",
  "monthly_budget_cents": 1000000,  // $10,000
  "max_cpl_cents": 5000,            // $50 max CPL
  "auto_pause_on_threshold": true,
  "auto_increase_on_performance": true,
  "increase_percentage": 15.0       // 15% increase
}
```

### 4. **Location-Based Alerts**

Automatic alerts for location performance issues:

**Alert Types:**
- `overspend`: Budget exceeded for location
- `underspend`: Not spending enough to hit target
- `high_cpl`: CPL exceeded maximum threshold
- `low_conversions`: Conversion rate dropped
- `pacing_issue`: Off-pace to meet monthly budget

**Severity Levels:**
- `low`: Informational
- `medium`: Needs attention
- `high`: Urgent action required
- `critical`: Auto-action may be triggered

**Table:** `budget_group_location_alerts`

### 5. **Campaign Location Targeting Cache**

Cached Google Ads location targets for faster filtering:

**Table:** `campaign_location_targets`

**Fields:**
- Campaign ID
- Location criterion ID (Google's location identifier)
- Location name
- Location type (City, State, ZIP, etc.)
- Target type (included vs excluded)
- Last synced timestamp

## API Endpoints

### Create Budget Group with Location

```http
POST /account/google/ads/budget/api/groups
Content-Type: application/json

{
  "name": "Nashville Market",
  "description": "HVAC campaigns for Nashville metro area",
  "target_location": "Nashville, TN",
  "location_type": "dma",
  "location_radius_miles": null,
  "location_criteria_ids": "1023191",
  "monthly_budget": 10000,
  "priority": 10,
  "auto_pause_on_overspend": true,
  "alert_threshold_pct": 0.80
}
```

### Get Location Performance

```http
GET /account/google/ads/budget/api/groups/{group_id}/locations

Response:
{
  "success": true,
  "group": {
    "id": 1,
    "target_location": "Nashville, TN",
    "location_type": "dma"
  },
  "locations": [
    {
      "location_name": "Nashville",
      "spend_cents": 450000,
      "conversions": 23,
      "cpl_cents": 1956,
      "conversion_rate": 0.0456,
      "pacing_status": "on_track"
    },
    {
      "location_name": "Murfreesboro",
      "spend_cents": 180000,
      "conversions": 9,
      "cpl_cents": 2000,
      "conversion_rate": 0.0401,
      "pacing_status": "underspending"
    }
  ],
  "period": "2025-01"
}
```

### Filter Campaigns by Location

```http
POST /account/google/ads/budget/api/campaigns/by-location
Content-Type: application/json

{
  "location_name": "Nashville"
}

Response:
{
  "success": true,
  "location": "Nashville",
  "campaigns": [
    {
      "id": 123,
      "name": "HVAC - Nashville",
      "status": "active",
      "daily_budget_cents": 33333,
      "group_name": "Nashville Market"
    }
  ],
  "count": 1
}
```

### Create Location Rule

```http
POST /account/google/ads/budget/api/location-rules
Content-Type: application/json

{
  "budget_group_id": 1,
  "location_name": "Nashville, TN",
  "monthly_budget": 10000,
  "priority": 10,
  "max_cpl_cents": 50.00,
  "auto_pause_on_threshold": true
}
```

### Get Location Alerts

```http
GET /account/google/ads/budget/api/location-alerts/{group_id}

Response:
{
  "success": true,
  "alerts": [
    {
      "location_name": "Nashville, TN",
      "alert_type": "high_cpl",
      "severity": "high",
      "message": "CPL $62.50 exceeds max $50.00",
      "current_value": 62.50,
      "threshold_value": 50.00,
      "action_taken": "none",
      "alert_date": "2025-01-16T10:30:00"
    }
  ]
}
```

## Location-Aware Pacing Algorithms

### Service: `location_budget_pacing_service.py`

#### 1. Calculate Location Pacing

```python
from app.services.location_budget_pacing_service import calculate_location_pacing

pacing = calculate_location_pacing(budget_group_id=1)

# Returns:
{
  "budget_group": {...},
  "period_month": "2025-01",
  "current_day": 16,
  "days_in_month": 31,
  "locations": [
    {
      "location_name": "Nashville, TN",
      "allocated_budget_cents": 1000000,
      "actual_spend_cents": 450000,
      "expected_spend_cents": 516129,  # Based on day 16/31
      "remaining_budget_cents": 550000,
      "pacing_pct": 87.2,
      "pacing_status": "underspending",
      "recommendation": "Increase daily budget by 6% to meet monthly target",
      "recommended_budget_adjustment_cents": 60000
    }
  ]
}
```

**Pacing Logic:**
- **Underspending (<80%)**: Recommend increasing budget
- **On Track (80-120%)**: No action needed
- **Overspending (>120%)**: Recommend reducing budget

#### 2. Apply Budget Adjustments

```python
from app.services.location_budget_pacing_service import apply_location_budget_adjustments

# Dry run (preview)
result = apply_location_budget_adjustments(budget_group_id=1, dry_run=True)

# Actually apply
result = apply_location_budget_adjustments(budget_group_id=1, dry_run=False)

# Returns:
{
  "dry_run": false,
  "adjustments": [
    {
      "location_name": "Nashville, TN",
      "current_budget_cents": 1000000,
      "adjustment_cents": 60000,
      "new_budget_cents": 1060000,
      "reason": "Increase daily budget by 6% to meet monthly target",
      "pacing_status": "underspending"
    }
  ],
  "total_adjustments": 1
}
```

#### 3. Detect Performance Anomalies

```python
from app.services.location_budget_pacing_service import detect_location_performance_anomalies

anomalies = detect_location_performance_anomalies(
    budget_group_id=1,
    sensitivity='medium'  # 'low', 'medium', or 'high'
)

# Returns:
[
  {
    "location_name": "Memphis, TN",
    "type": "cpl_spike",
    "severity": "high",
    "message": "CPL increased 45.2% ($42.00 → $61.00)",
    "current_value": 61.00,
    "previous_value": 42.00
  },
  {
    "location_name": "Knoxville, TN",
    "type": "conversion_drop",
    "severity": "medium",
    "message": "Conversion rate dropped 28.5% (5.2% → 3.7%)",
    "current_value": 3.7,
    "previous_value": 5.2
  }
]
```

**Anomaly Types:**
- `cpl_spike`: CPL increased significantly
- `conversion_drop`: Conversion rate decreased
- `ctr_drop`: Click-through rate decreased

**Sensitivity Thresholds:**

| Sensitivity | CPL Spike | Conv Drop | CTR Drop |
|------------|-----------|-----------|----------|
| Low        | 50%       | 40%       | 40%      |
| Medium     | 30%       | 25%       | 25%      |
| High       | 15%       | 15%       | 15%      |

## Use Cases

### Use Case 1: Multi-Market HVAC Company

**Scenario:** HVAC company operates in Nashville, Memphis, and Knoxville

**Setup:**
```
Budget Group 1: "Nashville Market - $10,000/mo"
  - Target: Nashville DMA
  - Campaigns: HVAC-Nashville-AC, HVAC-Nashville-Heating
  - Rules: Max CPL $50, auto-pause on threshold

Budget Group 2: "Memphis Market - $5,000/mo"
  - Target: Memphis DMA
  - Campaigns: HVAC-Memphis-AC, HVAC-Memphis-Heating
  - Rules: Max CPL $45, auto-pause on threshold

Budget Group 3: "Knoxville Market - $3,000/mo"
  - Target: Knoxville DMA
  - Campaigns: HVAC-Knoxville-AC
  - Rules: Max CPL $40, auto-increase on good performance
```

**Benefits:**
- Allocate more budget to Nashville (largest market)
- Different CPL thresholds based on market competitiveness
- Auto-increase Knoxville budget if performing well
- Independent pacing for each market

### Use Case 2: ZIP Code Targeting for Premium Services

**Scenario:** Luxury home services targeting high-income ZIP codes

**Setup:**
```
Budget Group: "Premium ZIPs - $15,000/mo"
  - Target: "37215,37205,37212" (wealthy Nashville ZIPs)
  - Location Type: ZIP
  - Priority: 10 (highest)
  - Rules:
    - 37215: $6,000/mo (highest income)
    - 37205: $5,000/mo
    - 37212: $4,000/mo
```

### Use Case 3: Radius-Based Service Area

**Scenario:** Plumber with 20-mile service radius

**Setup:**
```
Budget Group: "Service Area - $8,000/mo"
  - Target: "Nashville, TN"
  - Location Type: radius
  - Radius: 20 miles
  - Lat/Lng: 36.1627, -86.7816
```

## Database Schema

### campaign_budget_groups (Extended)

```sql
ALTER TABLE campaign_budget_groups ADD COLUMN target_location VARCHAR(255);
ALTER TABLE campaign_budget_groups ADD COLUMN location_type ENUM(...);
ALTER TABLE campaign_budget_groups ADD COLUMN location_radius_miles INT;
ALTER TABLE campaign_budget_groups ADD COLUMN location_criteria_ids TEXT;
```

### New Tables

- `budget_group_location_performance` - Performance by location
- `budget_group_location_rules` - Location-specific budget rules
- `budget_group_location_alerts` - Location-based alerts
- `campaign_location_targets` - Cached campaign location targeting

## Migration

Run the migration:

```bash
mysql -u admin -p fieldsprout < flaskapp/migrations/add_location_based_budgeting.sql
```

## UI Usage

### Creating a Location-Based Budget Group

1. Navigate to **Budget Management** in the Google Ads section
2. Click **Create Budget Group**
3. Fill in basic info:
   - Name: "Nashville Market"
   - Description: "HVAC campaigns for Nashville metro"
   - Monthly Budget: $10,000
4. Expand **Location Targeting** section:
   - Target Location: "Nashville, TN"
   - Location Type: "DMA (Metro Area)"
   - (Optional) Google Ads Criterion IDs: "1023191"
5. Set priority and auto-pause settings
6. Click **Save Group**

### Assigning Campaigns

Campaigns can be auto-assigned based on their Google Ads location targeting:

1. Click **Assign Campaigns** on a budget group
2. Filter shows campaigns targeting that location
3. Select campaigns and assign to group

### Viewing Location Performance

1. Open a budget group
2. Click **View Location Breakdown**
3. See spend, conversions, CPL by location
4. Monitor pacing status per location
5. Review auto-adjustment recommendations

## Advanced Features

### Auto-Pacing Agent

Create a scheduled task to auto-adjust budgets:

```python
from app.services.location_budget_pacing_service import apply_location_budget_adjustments

# Run daily at 2 AM
@scheduler.task('cron', id='location_budget_pacing', hour=2)
def auto_pace_location_budgets():
    budget_groups = get_all_budget_groups_with_locations()
    for group in budget_groups:
        apply_location_budget_adjustments(
            budget_group_id=group.id,
            dry_run=False  # Actually apply
        )
```

### Anomaly Detection Agent

Monitor for performance issues:

```python
from app.services.location_budget_pacing_service import (
    detect_location_performance_anomalies,
    create_location_alert
)

@scheduler.task('cron', id='location_anomaly_detection', hour='*/6')
def detect_anomalies():
    budget_groups = get_all_budget_groups_with_locations()
    for group in budget_groups:
        anomalies = detect_location_performance_anomalies(
            budget_group_id=group.id,
            sensitivity='medium'
        )
        for anomaly in anomalies:
            create_location_alert(
                budget_group_id=group.id,
                location_name=anomaly['location_name'],
                alert_type=anomaly['type'],
                severity=anomaly['severity'],
                message=anomaly['message'],
                current_value=anomaly['current_value'],
                threshold_value=anomaly.get('previous_value')
            )
```

## Best Practices

1. **Set Realistic Budgets**: Allocate budgets proportional to market size
2. **Use Priority Wisely**: High-priority locations get budget first
3. **Monitor CPL Thresholds**: Set max CPL based on average job value
4. **Enable Auto-Pause**: Protect against runaway spend
5. **Review Pacing Weekly**: Check if locations are on track
6. **Test Auto-Adjustments**: Use dry_run=True first
7. **Combine with Forecasting**: Use weather/seasonal data for location adjustments

## Troubleshooting

**Q: Campaigns not auto-assigning to location groups?**
- Ensure `campaign_location_targets` table is populated
- Run location sync from Google Ads API
- Check that location criterion IDs match

**Q: Pacing shows "underspending" but spend is high?**
- Check if budget was recently changed
- Verify current_day calculation is correct
- Ensure allocated_budget matches rule

**Q: Alerts not triggering?**
- Check alert threshold settings
- Verify budget_group_location_performance has recent data
- Run anomaly detection manually to test

## Future Enhancements

- [ ] Auto-sync location targets from Google Ads API
- [ ] Location-based forecasting (weather, events, seasonality)
- [ ] Competitive intelligence by location
- [ ] Dynamic budget reallocation across locations
- [ ] Machine learning for optimal budget distribution
- [ ] Location performance dashboard with charts
- [ ] SMS/Slack alerts for critical location issues
- [ ] Location-based A/B testing for ad copy

## See Also

- [Budget Management Documentation](./BUDGET_MANAGEMENT.md)
- [Forecasting Service](./FORECASTING.md)
- [Google Ads API Integration](./GOOGLE_ADS_API.md)
