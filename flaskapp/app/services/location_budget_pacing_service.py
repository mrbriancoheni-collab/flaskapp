# app/services/location_budget_pacing_service.py
"""
Location-Aware Budget Pacing Service
Adjusts budgets based on location-specific performance metrics.
"""
from datetime import datetime, date, timedelta
from sqlalchemy import text
from app import db


def calculate_location_pacing(budget_group_id, period_month=None):
    """
    Calculate pacing status for each location in a budget group.

    Args:
        budget_group_id: Budget group ID
        period_month: Month to analyze (defaults to current month)

    Returns:
        dict: Location pacing data with recommendations
    """
    if period_month is None:
        period_month = date.today().replace(day=1)

    # Get budget group details
    group_query = text("""
        SELECT
            id,
            name,
            monthly_budget_cents,
            daily_budget_cents
        FROM campaign_budget_groups
        WHERE id = :group_id
    """)

    with db.engine.connect() as conn:
        group_result = conn.execute(group_query, {"group_id": budget_group_id})
        group = group_result.first()

        if not group:
            return {"error": "Budget group not found"}

        group = dict(group._mapping)

        # Get location performance data
        location_query = text("""
            SELECT
                location_name,
                spend_cents,
                impressions,
                clicks,
                conversions,
                calls,
                ctr,
                cpc_cents,
                cpl_cents,
                conversion_rate,
                daily_avg_spend_cents,
                target_daily_spend_cents,
                pacing_status
            FROM budget_group_location_performance
            WHERE budget_group_id = :group_id
              AND period_month = :period_month
        """)

        location_result = conn.execute(location_query, {
            "group_id": budget_group_id,
            "period_month": period_month
        })
        locations = [dict(row._mapping) for row in location_result]

        # Get location rules (budget allocation per location)
        rules_query = text("""
            SELECT
                location_name,
                monthly_budget_cents,
                priority,
                max_cpl_cents,
                auto_pause_on_threshold,
                auto_increase_on_performance,
                increase_percentage
            FROM budget_group_location_rules
            WHERE budget_group_id = :group_id
              AND status = 'active'
        """)

        rules_result = conn.execute(rules_query, {"group_id": budget_group_id})
        rules = {row.location_name: dict(row._mapping) for row in rules_result}

    # Calculate pacing for each location
    days_in_month = (period_month.replace(day=28) + timedelta(days=4)).day
    current_day = datetime.now().day if period_month.month == datetime.now().month else days_in_month

    pacing_data = []
    for location in locations:
        location_name = location['location_name']
        rule = rules.get(location_name, {})

        # Get allocated budget for this location
        allocated_budget_cents = rule.get('monthly_budget_cents', 0)
        if allocated_budget_cents == 0:
            # If no rule, use proportional share of total budget
            allocated_budget_cents = group['monthly_budget_cents'] // max(len(locations), 1)

        # Calculate expected spend by this day
        daily_budget = allocated_budget_cents / days_in_month
        expected_spend = daily_budget * current_day
        actual_spend = location['spend_cents']

        # Calculate pacing percentage
        pacing_pct = (actual_spend / expected_spend * 100) if expected_spend > 0 else 0

        # Determine pacing status
        if pacing_pct < 80:
            pacing_status = 'underspending'
            recommendation = f"Increase daily budget by {int((100 - pacing_pct) / 2)}% to meet monthly target"
        elif pacing_pct > 120:
            pacing_status = 'overspending'
            recommendation = f"Reduce daily budget by {int((pacing_pct - 100) / 2)}% to avoid exhausting budget"
        else:
            pacing_status = 'on_track'
            recommendation = "Budget pacing is healthy"

        # Check CPL threshold
        max_cpl = rule.get('max_cpl_cents')
        cpl_warning = None
        if max_cpl and location['cpl_cents'] and location['cpl_cents'] > max_cpl:
            cpl_warning = f"CPL ${location['cpl_cents']/100:.2f} exceeds max ${max_cpl/100:.2f}"
            if rule.get('auto_pause_on_threshold'):
                recommendation = "Consider pausing campaigns - CPL threshold exceeded"

        # Calculate recommended adjustment
        if pacing_status == 'underspending' and rule.get('auto_increase_on_performance'):
            # Good performance + underspending = increase budget
            if location['conversion_rate'] and location['conversion_rate'] > 0.05:  # >5% conv rate
                increase_pct = rule.get('increase_percentage', 10)
                recommended_budget_adjustment = int(allocated_budget_cents * (increase_pct / 100))
            else:
                recommended_budget_adjustment = 0
        elif pacing_status == 'overspending':
            # Reduce to prevent overspend
            recommended_budget_adjustment = -int((pacing_pct - 100) / 100 * allocated_budget_cents)
        else:
            recommended_budget_adjustment = 0

        pacing_data.append({
            'location_name': location_name,
            'allocated_budget_cents': allocated_budget_cents,
            'actual_spend_cents': actual_spend,
            'expected_spend_cents': int(expected_spend),
            'remaining_budget_cents': allocated_budget_cents - actual_spend,
            'pacing_pct': round(pacing_pct, 1),
            'pacing_status': pacing_status,
            'recommendation': recommendation,
            'cpl_cents': location['cpl_cents'],
            'cpl_warning': cpl_warning,
            'conversion_rate': location['conversion_rate'],
            'recommended_budget_adjustment_cents': recommended_budget_adjustment,
            'priority': rule.get('priority', 0)
        })

    # Sort by priority (high to low) then by pacing status
    pacing_data.sort(key=lambda x: (-x['priority'], x['pacing_pct']))

    return {
        'budget_group': group,
        'period_month': period_month.strftime('%Y-%m'),
        'current_day': current_day,
        'days_in_month': days_in_month,
        'locations': pacing_data,
        'total_locations': len(pacing_data)
    }


def apply_location_budget_adjustments(budget_group_id, dry_run=True):
    """
    Apply recommended budget adjustments for locations based on pacing.

    Args:
        budget_group_id: Budget group ID
        dry_run: If True, only return recommendations without applying

    Returns:
        list: Applied adjustments
    """
    pacing = calculate_location_pacing(budget_group_id)
    adjustments = []

    for location in pacing['locations']:
        adjustment_cents = location['recommended_budget_adjustment_cents']

        if adjustment_cents == 0:
            continue

        adjustment = {
            'location_name': location['location_name'],
            'current_budget_cents': location['allocated_budget_cents'],
            'adjustment_cents': adjustment_cents,
            'new_budget_cents': location['allocated_budget_cents'] + adjustment_cents,
            'reason': location['recommendation'],
            'pacing_status': location['pacing_status']
        }

        adjustments.append(adjustment)

        if not dry_run:
            # Apply the adjustment to budget_group_location_rules
            update_query = text("""
                UPDATE budget_group_location_rules
                SET monthly_budget_cents = monthly_budget_cents + :adjustment
                WHERE budget_group_id = :group_id
                  AND location_name = :location_name
            """)

            with db.engine.begin() as conn:
                conn.execute(update_query, {
                    "group_id": budget_group_id,
                    "location_name": location['location_name'],
                    "adjustment": adjustment_cents
                })

    return {
        'dry_run': dry_run,
        'adjustments': adjustments,
        'total_adjustments': len(adjustments)
    }


def detect_location_performance_anomalies(budget_group_id, sensitivity='medium'):
    """
    Detect performance anomalies by location (sudden CPL spikes, conversion drops, etc.).

    Args:
        budget_group_id: Budget group ID
        sensitivity: 'low', 'medium', or 'high'

    Returns:
        list: Detected anomalies
    """
    # Get last 3 months of data for comparison
    current_month = date.today().replace(day=1)
    last_month = (current_month - timedelta(days=1)).replace(day=1)
    two_months_ago = (last_month - timedelta(days=1)).replace(day=1)

    query = text("""
        SELECT
            location_name,
            period_month,
            spend_cents,
            cpl_cents,
            conversion_rate,
            ctr
        FROM budget_group_location_performance
        WHERE budget_group_id = :group_id
          AND period_month IN (:current, :last, :two_ago)
        ORDER BY location_name, period_month DESC
    """)

    with db.engine.connect() as conn:
        result = conn.execute(query, {
            "group_id": budget_group_id,
            "current": current_month,
            "last": last_month,
            "two_ago": two_months_ago
        })
        rows = [dict(row._mapping) for row in result]

    # Set sensitivity thresholds
    thresholds = {
        'low': {'cpl_spike': 0.50, 'conv_drop': 0.40, 'ctr_drop': 0.40},
        'medium': {'cpl_spike': 0.30, 'conv_drop': 0.25, 'ctr_drop': 0.25},
        'high': {'cpl_spike': 0.15, 'conv_drop': 0.15, 'ctr_drop': 0.15}
    }
    thresh = thresholds.get(sensitivity, thresholds['medium'])

    # Group by location
    locations = {}
    for row in rows:
        loc = row['location_name']
        if loc not in locations:
            locations[loc] = []
        locations[loc].append(row)

    anomalies = []

    for loc, data in locations.items():
        if len(data) < 2:
            continue  # Need at least 2 months for comparison

        current = data[0]  # Most recent
        previous = data[1]  # Previous month

        # CPL spike
        if current['cpl_cents'] and previous['cpl_cents']:
            cpl_change = (current['cpl_cents'] - previous['cpl_cents']) / previous['cpl_cents']
            if cpl_change > thresh['cpl_spike']:
                anomalies.append({
                    'location_name': loc,
                    'type': 'cpl_spike',
                    'severity': 'high' if cpl_change > 0.50 else 'medium',
                    'message': f"CPL increased {cpl_change*100:.1f}% (${previous['cpl_cents']/100:.2f} → ${current['cpl_cents']/100:.2f})",
                    'current_value': current['cpl_cents'] / 100,
                    'previous_value': previous['cpl_cents'] / 100
                })

        # Conversion rate drop
        if current['conversion_rate'] and previous['conversion_rate']:
            conv_change = (previous['conversion_rate'] - current['conversion_rate']) / previous['conversion_rate']
            if conv_change > thresh['conv_drop']:
                anomalies.append({
                    'location_name': loc,
                    'type': 'conversion_drop',
                    'severity': 'high' if conv_change > 0.40 else 'medium',
                    'message': f"Conversion rate dropped {conv_change*100:.1f}% ({previous['conversion_rate']*100:.2f}% → {current['conversion_rate']*100:.2f}%)",
                    'current_value': current['conversion_rate'] * 100,
                    'previous_value': previous['conversion_rate'] * 100
                })

        # CTR drop
        if current['ctr'] and previous['ctr']:
            ctr_change = (previous['ctr'] - current['ctr']) / previous['ctr']
            if ctr_change > thresh['ctr_drop']:
                anomalies.append({
                    'location_name': loc,
                    'type': 'ctr_drop',
                    'severity': 'medium' if ctr_change > 0.30 else 'low',
                    'message': f"CTR dropped {ctr_change*100:.1f}% ({previous['ctr']*100:.3f}% → {current['ctr']*100:.3f}%)",
                    'current_value': current['ctr'] * 100,
                    'previous_value': previous['ctr'] * 100
                })

    return anomalies


def create_location_alert(budget_group_id, location_name, alert_type, severity, message, current_value=None, threshold_value=None, action_taken='none'):
    """
    Create a location-specific alert.

    Args:
        budget_group_id: Budget group ID
        location_name: Location name
        alert_type: Type of alert (overspend, high_cpl, etc.)
        severity: low, medium, high, critical
        message: Alert message
        current_value: Current metric value
        threshold_value: Threshold that was exceeded
        action_taken: Action taken (none, paused_campaigns, etc.)
    """
    query = text("""
        INSERT INTO budget_group_location_alerts
            (budget_group_id, location_name, alert_type, severity, message,
             current_value, threshold_value, action_taken)
        VALUES
            (:group_id, :location, :type, :severity, :message,
             :current_val, :threshold_val, :action)
    """)

    with db.engine.begin() as conn:
        conn.execute(query, {
            "group_id": budget_group_id,
            "location": location_name,
            "type": alert_type,
            "severity": severity,
            "message": message,
            "current_val": current_value,
            "threshold_val": threshold_value,
            "action": action_taken
        })
