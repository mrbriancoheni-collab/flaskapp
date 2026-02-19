# app/services/auto_budget_adjustment_service.py
"""
Auto-Budget Adjustment Service

Automatically adjusts campaign budgets to:
1. Hit user-specified monthly budget targets without overspending
2. Distribute budget optimally across campaigns based on performance
3. Factor in seasonality, weather, and capacity constraints
4. Send notifications to users about all changes
"""

from typing import Dict, List, Any, Tuple
from datetime import datetime, date, timedelta
from sqlalchemy import text
from app import db
import calendar


def auto_adjust_campaign_budgets(
    account_id: int,
    total_monthly_budget: float,
    campaigns: List[Dict[str, Any]],
    service_type: str = 'hvac_ac',
    enable_notifications: bool = True
) -> Dict[str, Any]:
    """
    Automatically adjust campaign budgets to hit monthly target without overspending.

    Args:
        account_id: Account ID
        total_monthly_budget: Total monthly budget target (dollars)
        campaigns: List of campaign data
        service_type: Service type for seasonality
        enable_notifications: Whether to send notifications

    Returns:
        Dict with adjustment results and actions taken
    """
    today = date.today()
    current_day = today.day
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    days_remaining = days_in_month - current_day + 1

    # Calculate total spend so far this month
    total_spend_mtd = sum(c.get('spend_mtd', 0) for c in campaigns)
    remaining_budget = total_monthly_budget - total_spend_mtd

    # Get seasonality adjustment for this month
    from app.services.budget_forecasting_service import get_seasonality_multiplier
    seasonality = get_seasonality_multiplier(service_type, today.month)
    seasonality_factor = seasonality['demand_multiplier']

    # Calculate performance scores for each campaign (for optimal distribution)
    campaign_scores = []
    for campaign in campaigns:
        # Performance score based on ROAS, conversion rate, and volume
        conversions = campaign.get('conversions_mtd', 0)
        cost = campaign.get('spend_mtd', 0)
        revenue = campaign.get('revenue_mtd', 0)

        roas = (revenue / cost) if cost > 0 else 0
        cpl = (cost / conversions) if conversions > 0 else 999999

        # Higher ROAS = better, Lower CPL = better
        # Normalize to 0-100 score
        performance_score = min(100, (roas * 10) + (100 / (cpl + 1)) + (conversions / 10))

        campaign_scores.append({
            'campaign_id': campaign['id'],
            'campaign_name': campaign.get('name', ''),
            'performance_score': performance_score,
            'current_daily_budget': campaign.get('daily_budget_cents', 0) / 100,
            'spend_mtd': cost,
            'conversions_mtd': conversions,
            'roas': roas
        })

    # Sort by performance score (best performers get more budget)
    campaign_scores.sort(key=lambda x: x['performance_score'], reverse=True)

    # Calculate total performance score
    total_performance = sum(c['performance_score'] for c in campaign_scores)

    # Distribute remaining budget based on performance
    adjustments = []
    total_new_daily_budget = 0

    for campaign_data in campaign_scores:
        # Allocate budget proportional to performance score
        budget_share = (campaign_data['performance_score'] / total_performance) if total_performance > 0 else (1 / len(campaign_scores))

        # Calculate optimal daily budget for this campaign
        campaign_monthly_allocation = remaining_budget * budget_share
        optimal_daily_budget = campaign_monthly_allocation / days_remaining

        # Apply seasonality factor
        adjusted_daily_budget = optimal_daily_budget * seasonality_factor

        # Don't reduce budget below 20% of current unless necessary
        min_budget = campaign_data['current_daily_budget'] * 0.2
        max_budget = campaign_data['current_daily_budget'] * 3.0  # Don't increase more than 3x

        final_daily_budget = max(min_budget, min(adjusted_daily_budget, max_budget))

        # Calculate change
        budget_change = final_daily_budget - campaign_data['current_daily_budget']
        budget_change_pct = (budget_change / campaign_data['current_daily_budget'] * 100) if campaign_data['current_daily_budget'] > 0 else 0

        adjustment = {
            'campaign_id': campaign_data['campaign_id'],
            'campaign_name': campaign_data['campaign_name'],
            'old_daily_budget': campaign_data['current_daily_budget'],
            'new_daily_budget': round(final_daily_budget, 2),
            'budget_change': round(budget_change, 2),
            'budget_change_pct': round(budget_change_pct, 1),
            'performance_score': round(campaign_data['performance_score'], 1),
            'reasoning': get_adjustment_reasoning(budget_change_pct, campaign_data, seasonality_factor)
        }

        adjustments.append(adjustment)
        total_new_daily_budget += final_daily_budget

    # Verify we won't overspend
    projected_monthly_spend = total_spend_mtd + (total_new_daily_budget * days_remaining)

    # If still over budget, reduce proportionally
    if projected_monthly_spend > total_monthly_budget:
        overspend_factor = total_monthly_budget / projected_monthly_spend
        for adjustment in adjustments:
            adjustment['new_daily_budget'] = round(adjustment['new_daily_budget'] * overspend_factor, 2)
            adjustment['budget_change'] = adjustment['new_daily_budget'] - adjustment['old_daily_budget']
            adjustment['budget_change_pct'] = (adjustment['budget_change'] / adjustment['old_daily_budget'] * 100) if adjustment['old_daily_budget'] > 0 else 0

    # Apply adjustments to database
    changes_applied = 0
    for adjustment in adjustments:
        # Only apply if change is significant (>5%)
        if abs(adjustment['budget_change_pct']) >= 5:
            success = apply_budget_adjustment(
                campaign_id=adjustment['campaign_id'],
                new_daily_budget_cents=int(adjustment['new_daily_budget'] * 100)
            )

            if success:
                changes_applied += 1

                # Log the change
                log_budget_change(
                    account_id=account_id,
                    campaign_id=adjustment['campaign_id'],
                    old_budget=adjustment['old_daily_budget'],
                    new_budget=adjustment['new_daily_budget'],
                    reason=adjustment['reasoning'],
                    auto_adjusted=True
                )

                # Send notification if enabled
                if enable_notifications:
                    send_budget_adjustment_notification(
                        account_id=account_id,
                        adjustment=adjustment
                    )

    return {
        "success": True,
        "total_monthly_budget": total_monthly_budget,
        "spend_mtd": total_spend_mtd,
        "remaining_budget": remaining_budget,
        "days_remaining": days_remaining,
        "seasonality_factor": seasonality_factor,
        "adjustments": adjustments,
        "changes_applied": changes_applied,
        "projected_monthly_spend": total_spend_mtd + (sum(a['new_daily_budget'] for a in adjustments) * days_remaining)
    }


def get_adjustment_reasoning(change_pct: float, campaign_data: Dict[str, Any], seasonality: float) -> str:
    """Generate human-readable reasoning for budget adjustment."""
    reasons = []

    if change_pct > 20:
        reasons.append(f"Increasing budget by {abs(change_pct):.0f}%")
        if campaign_data['performance_score'] > 70:
            reasons.append("strong performer (high ROAS/conversions)")
        if seasonality > 1.2:
            reasons.append(f"peak season ({seasonality:.1f}x demand)")
    elif change_pct < -20:
        reasons.append(f"Reducing budget by {abs(change_pct):.0f}%")
        if campaign_data['performance_score'] < 30:
            reasons.append("underperforming (low ROAS)")
        reasons.append("prevent monthly overspend")
    else:
        reasons.append("minor adjustment to optimize spend")

    return " - ".join(reasons)


def apply_budget_adjustment(campaign_id: int, new_daily_budget_cents: int) -> bool:
    """Apply budget adjustment to campaign in database."""
    try:
        query = text("""
            UPDATE ads_campaigns
            SET daily_budget_cents = :new_budget,
                updated_at = NOW()
            WHERE id = :campaign_id
        """)

        with db.engine.begin() as conn:
            conn.execute(query, {
                "campaign_id": campaign_id,
                "new_budget": new_daily_budget_cents
            })

        return True
    except Exception as e:
        print(f"Error applying budget adjustment: {str(e)}")
        return False


def log_budget_change(
    account_id: int,
    campaign_id: int,
    old_budget: float,
    new_budget: float,
    reason: str,
    auto_adjusted: bool = True
) -> None:
    """Log budget change for audit trail."""
    try:
        query = text("""
            INSERT INTO budget_change_log
                (account_id, campaign_id, old_daily_budget_cents, new_daily_budget_cents,
                 change_reason, auto_adjusted, changed_at)
            VALUES
                (:account_id, :campaign_id, :old_budget, :new_budget,
                 :reason, :auto_adjusted, NOW())
        """)

        with db.engine.begin() as conn:
            conn.execute(query, {
                "account_id": account_id,
                "campaign_id": campaign_id,
                "old_budget": int(old_budget * 100),
                "new_budget": int(new_budget * 100),
                "reason": reason,
                "auto_adjusted": auto_adjusted
            })
    except Exception as e:
        # Don't fail if logging fails
        print(f"Error logging budget change: {str(e)}")


def send_budget_adjustment_notification(account_id: int, adjustment: Dict[str, Any]) -> None:
    """Send notification to user about budget adjustment."""
    try:
        # Create notification record
        query = text("""
            INSERT INTO user_notifications
                (account_id, notification_type, title, message, data, created_at, read)
            VALUES
                (:account_id, :type, :title, :message, :data, NOW(), FALSE)
        """)

        import json

        title = f"Budget adjusted: {adjustment['campaign_name']}"

        if adjustment['budget_change_pct'] > 0:
            message = f"Daily budget increased by {adjustment['budget_change_pct']:.0f}% to ${adjustment['new_daily_budget']:.2f}"
        else:
            message = f"Daily budget reduced by {abs(adjustment['budget_change_pct']):.0f}% to ${adjustment['new_daily_budget']:.2f}"

        message += f" - {adjustment['reasoning']}"

        with db.engine.begin() as conn:
            conn.execute(query, {
                "account_id": account_id,
                "type": "budget_adjustment",
                "title": title,
                "message": message,
                "data": json.dumps(adjustment)
            })
    except Exception as e:
        print(f"Error sending notification: {str(e)}")


def distribute_budget_group_budgets(
    account_id: int,
    budget_group_id: int,
    campaigns_in_group: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Distribute a budget group's budget optimally across campaigns in the group.

    Args:
        account_id: Account ID
        budget_group_id: Budget group ID
        campaigns_in_group: Campaigns in this group

    Returns:
        Distribution results
    """
    # Get budget group details
    query = text("""
        SELECT monthly_budget_cents, name
        FROM campaign_budget_groups
        WHERE id = :group_id AND account_id = :account_id
    """)

    with db.engine.connect() as conn:
        result = conn.execute(query, {
            "group_id": budget_group_id,
            "account_id": account_id
        }).first()

        if not result:
            return {"success": False, "error": "Budget group not found"}

        group_monthly_budget = result.monthly_budget_cents / 100
        group_name = result.name

    # Use the same auto-adjustment logic but only for this group
    return auto_adjust_campaign_budgets(
        account_id=account_id,
        total_monthly_budget=group_monthly_budget,
        campaigns=campaigns_in_group,
        enable_notifications=True
    )


def calculate_optimal_budget_allocation(
    campaigns: List[Dict[str, Any]],
    total_budget: float,
    optimization_goal: str = 'roas'  # roas, conversions, balanced
) -> List[Dict[str, Any]]:
    """
    Calculate optimal budget allocation using performance-based algorithm.

    Args:
        campaigns: Campaign performance data
        total_budget: Total budget to allocate
        optimization_goal: What to optimize for (roas, conversions, balanced)

    Returns:
        List of budget allocations per campaign
    """
    allocations = []

    # Calculate scores based on goal
    for campaign in campaigns:
        conversions = campaign.get('conversions', 0)
        cost = campaign.get('cost', 1)
        revenue = campaign.get('revenue', 0)

        roas = revenue / cost if cost > 0 else 0
        conversion_rate = campaign.get('conversion_rate', 0)

        if optimization_goal == 'roas':
            score = roas
        elif optimization_goal == 'conversions':
            score = conversions * conversion_rate
        else:  # balanced
            score = (roas * 0.5) + (conversions * 0.3) + (conversion_rate * 0.2)

        allocations.append({
            'campaign_id': campaign['id'],
            'campaign_name': campaign.get('name', ''),
            'score': score,
            'current_budget': campaign.get('daily_budget', 0)
        })

    # Normalize scores and allocate budget
    total_score = sum(a['score'] for a in allocations)

    for allocation in allocations:
        if total_score > 0:
            budget_share = (allocation['score'] / total_score)
            allocation['recommended_budget'] = total_budget * budget_share
            allocation['budget_change_pct'] = ((allocation['recommended_budget'] - allocation['current_budget']) / allocation['current_budget'] * 100) if allocation['current_budget'] > 0 else 0
        else:
            # Equal distribution if no performance data
            allocation['recommended_budget'] = total_budget / len(allocations)
            allocation['budget_change_pct'] = 0

    return allocations


def get_adjustment_history(
    account_id: int,
    days: int = 30,
    campaign_id: int = None
) -> List[Dict[str, Any]]:
    """
    Get budget adjustment history for an account.

    Args:
        account_id: Account ID
        days: Days of history to fetch
        campaign_id: Optional campaign ID to filter

    Returns:
        List of budget adjustments
    """
    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    query_parts = ["""
        SELECT
            bcl.*,
            ac.name as campaign_name
        FROM budget_change_log bcl
        JOIN ads_campaigns ac ON ac.id = bcl.campaign_id
        WHERE bcl.account_id = :account_id
          AND bcl.changed_at >= :start_date
    """]

    params = {
        "account_id": account_id,
        "start_date": start_date
    }

    if campaign_id:
        query_parts.append("AND bcl.campaign_id = :campaign_id")
        params["campaign_id"] = campaign_id

    query_parts.append("ORDER BY bcl.changed_at DESC LIMIT 100")
    query = text(" ".join(query_parts))

    with db.engine.connect() as conn:
        result = conn.execute(query, params)
        history = [dict(row._mapping) for row in result]

    return history


def get_budget_status(account_id: int) -> Dict[str, Any]:
    """
    Get current budget status for an account.

    Returns:
        Budget pacing info (spend MTD, remaining budget, on/off track)
    """
    # Get auto-budget settings
    settings_query = text("""
        SELECT total_monthly_budget_cents
        FROM auto_budget_settings
        WHERE account_id = :account_id
    """)

    with db.engine.connect() as conn:
        result = conn.execute(settings_query, {"account_id": account_id})
        settings = result.first()

        if not settings:
            return {
                "configured": False,
                "message": "Auto-budget not configured"
            }

        total_monthly_budget = settings.total_monthly_budget_cents / 100

    # Get current month's spend
    today = date.today()
    month_start = date(today.year, today.month, 1)
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    days_elapsed = today.day
    days_remaining = days_in_month - days_elapsed + 1

    # Calculate spend MTD
    spend_query = text("""
        SELECT SUM(cost_cents) as total_spend
        FROM campaign_performance_history
        WHERE account_id = :account_id
          AND date >= :month_start
          AND date <= :today
    """)

    with db.engine.connect() as conn:
        result = conn.execute(spend_query, {
            "account_id": account_id,
            "month_start": month_start,
            "today": today
        })
        spend_row = result.first()
        spend_mtd = (spend_row.total_spend / 100) if spend_row and spend_row.total_spend else 0

    # Calculate pacing
    expected_spend = (total_monthly_budget / days_in_month) * days_elapsed
    remaining_budget = total_monthly_budget - spend_mtd
    pace_pct = (spend_mtd / expected_spend * 100) if expected_spend > 0 else 0

    # Determine status
    if pace_pct > 110:
        status = "overspending"
    elif pace_pct < 90:
        status = "underspending"
    else:
        status = "on_track"

    return {
        "configured": True,
        "total_monthly_budget": total_monthly_budget,
        "spend_mtd": round(spend_mtd, 2),
        "remaining_budget": round(remaining_budget, 2),
        "expected_spend": round(expected_spend, 2),
        "days_elapsed": days_elapsed,
        "days_remaining": days_remaining,
        "pace_pct": round(pace_pct, 1),
        "status": status,
        "projected_monthly_spend": round((spend_mtd / days_elapsed) * days_in_month if days_elapsed > 0 else 0, 2)
    }
