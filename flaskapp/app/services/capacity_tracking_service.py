# app/services/capacity_tracking_service.py
"""
Capacity Tracking Service (No CRM Required)

Tracks tech capacity and booking status through:
1. Manual capacity entry (techs available per day)
2. Simple booking form (track appointments)
3. Google Calendar integration (optional)
4. Phone call logging
"""

from typing import Dict, List, Any, Optional
from datetime import datetime, date, timedelta
from sqlalchemy import text
from app import db


def update_daily_capacity(
    account_id: int,
    service_type: str,
    target_date: date,
    total_techs: int,
    slots_per_tech: int = 4,
    booked_slots: Optional[int] = None
) -> Dict[str, Any]:
    """
    Update daily capacity for a service type.

    Args:
        account_id: Account ID
        service_type: Service type (hvac, plumbing, electrical, roofing)
        target_date: Date to update
        total_techs: Number of techs available
        slots_per_tech: Appointment slots per tech per day (default 4)
        booked_slots: Number of slots already booked (if known)

    Returns:
        Updated capacity data
    """
    total_slots = total_techs * slots_per_tech

    # Get current booked count if not provided
    if booked_slots is None:
        booked_slots = get_booked_count(account_id, service_type, target_date)

    capacity_utilization = (booked_slots / total_slots) if total_slots > 0 else 0

    # Calculate budget recommendation
    should_reduce = capacity_utilization >= 0.90
    should_increase = capacity_utilization <= 0.50
    adjustment_pct = 0

    if should_reduce:
        # At 90%+ capacity, reduce budget significantly
        adjustment_pct = -40 + ((capacity_utilization - 0.90) * -100)
    elif should_increase:
        # Below 50% capacity, increase budget
        adjustment_pct = 30

    # Calculate days booked out
    days_booked_out = calculate_days_booked_out(account_id, service_type, target_date)

    # Upsert capacity record
    query = text("""
        INSERT INTO capacity_tracking
            (account_id, date, service_type, total_techs_available,
             total_appointment_slots, booked_slots, capacity_utilization,
             should_reduce_budget, should_increase_budget, recommended_budget_adjustment_pct,
             days_booked_out)
        VALUES
            (:account_id, :date, :service_type, :total_techs,
             :total_slots, :booked_slots, :utilization,
             :should_reduce, :should_increase, :adjustment_pct,
             :days_booked_out)
        ON DUPLICATE KEY UPDATE
            total_techs_available = :total_techs,
            total_appointment_slots = :total_slots,
            booked_slots = :booked_slots,
            capacity_utilization = :utilization,
            should_reduce_budget = :should_reduce,
            should_increase_budget = :should_increase,
            recommended_budget_adjustment_pct = :adjustment_pct,
            days_booked_out = :days_booked_out,
            updated_at = NOW()
    """)

    with db.engine.begin() as conn:
        conn.execute(query, {
            "account_id": account_id,
            "date": target_date,
            "service_type": service_type,
            "total_techs": total_techs,
            "total_slots": total_slots,
            "booked_slots": booked_slots,
            "utilization": capacity_utilization,
            "should_reduce": should_reduce,
            "should_increase": should_increase,
            "adjustment_pct": adjustment_pct,
            "days_booked_out": days_booked_out
        })

    return {
        "success": True,
        "date": target_date.isoformat(),
        "total_techs": total_techs,
        "total_slots": total_slots,
        "booked_slots": booked_slots,
        "capacity_utilization": capacity_utilization,
        "budget_recommendation": get_capacity_based_recommendation(capacity_utilization)
    }


def log_booking(
    account_id: int,
    service_type: str,
    booking_date: date,
    booking_time: str,
    customer_name: str,
    customer_phone: str,
    service_description: str,
    source: str = 'google_ads'  # google_ads, organic, referral, direct
) -> Dict[str, Any]:
    """
    Log a new booking to track capacity.

    Args:
        account_id: Account ID
        service_type: Service type
        booking_date: Date of appointment
        booking_time: Time of appointment
        customer_name: Customer name
        customer_phone: Customer phone
        service_description: Brief description
        source: Lead source

    Returns:
        Booking confirmation
    """
    # Insert booking record
    query = text("""
        INSERT INTO capacity_bookings
            (account_id, service_type, booking_date, booking_time,
             customer_name, customer_phone, service_description, source,
             status, created_at)
        VALUES
            (:account_id, :service_type, :booking_date, :booking_time,
             :customer_name, :customer_phone, :service_description, :source,
             'scheduled', NOW())
    """)

    with db.engine.begin() as conn:
        result = conn.execute(query, {
            "account_id": account_id,
            "service_type": service_type,
            "booking_date": booking_date,
            "booking_time": booking_time,
            "customer_name": customer_name,
            "customer_phone": customer_phone,
            "service_description": service_description,
            "source": source
        })

        booking_id = result.lastrowid

    # Update capacity tracking for this date
    update_booked_count(account_id, service_type, booking_date)

    return {
        "success": True,
        "booking_id": booking_id,
        "booking_date": booking_date.isoformat(),
        "message": "Booking logged successfully"
    }


def update_booking_status(
    booking_id: int,
    status: str  # scheduled, completed, cancelled, no_show
) -> Dict[str, Any]:
    """Update booking status and adjust capacity accordingly."""
    # Get booking details
    query = text("""
        SELECT account_id, service_type, booking_date
        FROM capacity_bookings
        WHERE id = :booking_id
    """)

    with db.engine.connect() as conn:
        result = conn.execute(query, {"booking_id": booking_id}).first()

        if not result:
            return {"success": False, "error": "Booking not found"}

        account_id = result.account_id
        service_type = result.service_type
        booking_date = result.booking_date

    # Update booking status
    update_query = text("""
        UPDATE capacity_bookings
        SET status = :status, updated_at = NOW()
        WHERE id = :booking_id
    """)

    with db.engine.begin() as conn:
        conn.execute(update_query, {
            "booking_id": booking_id,
            "status": status
        })

    # Update capacity tracking
    update_booked_count(account_id, service_type, booking_date)

    # Update completed/cancelled counts in capacity_tracking
    if status == 'completed':
        increment_completed(account_id, service_type, booking_date)
    elif status == 'cancelled':
        increment_cancelled(account_id, service_type, booking_date)

    return {
        "success": True,
        "booking_id": booking_id,
        "new_status": status
    }


def get_booked_count(account_id: int, service_type: str, target_date: date) -> int:
    """Get count of booked slots for a date."""
    query = text("""
        SELECT COUNT(*) as count
        FROM capacity_bookings
        WHERE account_id = :account_id
          AND service_type = :service_type
          AND booking_date = :date
          AND status IN ('scheduled', 'completed')
    """)

    with db.engine.connect() as conn:
        result = conn.execute(query, {
            "account_id": account_id,
            "service_type": service_type,
            "date": target_date
        }).first()

        return result.count if result else 0


def update_booked_count(account_id: int, service_type: str, target_date: date) -> None:
    """Update booked count in capacity_tracking table."""
    booked_count = get_booked_count(account_id, service_type, target_date)

    query = text("""
        UPDATE capacity_tracking
        SET booked_slots = :booked_count,
            capacity_utilization = booked_slots / total_appointment_slots,
            updated_at = NOW()
        WHERE account_id = :account_id
          AND service_type = :service_type
          AND date = :date
    """)

    with db.engine.begin() as conn:
        conn.execute(query, {
            "account_id": account_id,
            "service_type": service_type,
            "date": target_date,
            "booked_count": booked_count
        })


def increment_completed(account_id: int, service_type: str, target_date: date) -> None:
    """Increment completed jobs count."""
    query = text("""
        UPDATE capacity_tracking
        SET completed_jobs = completed_jobs + 1,
            booking_rate = completed_jobs / (booked_slots + cancelled_jobs),
            updated_at = NOW()
        WHERE account_id = :account_id
          AND service_type = :service_type
          AND date = :date
    """)

    with db.engine.begin() as conn:
        conn.execute(query, {
            "account_id": account_id,
            "service_type": service_type,
            "date": target_date
        })


def increment_cancelled(account_id: int, service_type: str, target_date: date) -> None:
    """Increment cancelled jobs count."""
    query = text("""
        UPDATE capacity_tracking
        SET cancelled_jobs = cancelled_jobs + 1,
            updated_at = NOW()
        WHERE account_id = :account_id
          AND service_type = :service_type
          AND date = :date
    """)

    with db.engine.begin() as conn:
        conn.execute(query, {
            "account_id": account_id,
            "service_type": service_type,
            "date": target_date
        })


def calculate_days_booked_out(account_id: int, service_type: str, start_date: date) -> int:
    """
    Calculate how many days out the business is fully booked.

    Returns:
        Number of days until next available slot
    """
    query = text("""
        SELECT date, capacity_utilization
        FROM capacity_tracking
        WHERE account_id = :account_id
          AND service_type = :service_type
          AND date >= :start_date
        ORDER BY date ASC
        LIMIT 30
    """)

    days_booked_out = 0

    with db.engine.connect() as conn:
        result = conn.execute(query, {
            "account_id": account_id,
            "service_type": service_type,
            "start_date": start_date
        })

        for row in result:
            if row.capacity_utilization >= 0.95:  # 95%+ is considered fully booked
                days_booked_out += 1
            else:
                break  # Found available day

    return days_booked_out


def get_capacity_based_recommendation(utilization: float) -> str:
    """Get budget recommendation based on capacity utilization."""
    if utilization >= 0.95:
        return "CRITICAL: Fully booked - reduce budget by 50%+ to avoid wasted leads"
    elif utilization >= 0.90:
        return "HIGH CAPACITY: 90%+ booked - reduce budget by 30-40%"
    elif utilization >= 0.80:
        return "GOOD CAPACITY: 80%+ booked - reduce budget by 10-20%"
    elif utilization >= 0.60:
        return "OPTIMAL: 60-80% capacity - maintain current budget"
    elif utilization >= 0.40:
        return "LOW CAPACITY: Below 60% - increase budget by 20-30%"
    else:
        return "VERY LOW: Below 40% capacity - increase budget by 50%+"


def bulk_update_capacity(
    account_id: int,
    service_type: str,
    start_date: date,
    end_date: date,
    daily_techs: int,
    slots_per_tech: int = 4
) -> Dict[str, Any]:
    """
    Bulk update capacity for a date range.

    Useful for setting weekly schedules.

    Args:
        account_id: Account ID
        service_type: Service type
        start_date: Start date
        end_date: End date
        daily_techs: Techs available each day
        slots_per_tech: Slots per tech

    Returns:
        Summary of updates
    """
    current_date = start_date
    days_updated = 0

    while current_date <= end_date:
        update_daily_capacity(
            account_id=account_id,
            service_type=service_type,
            target_date=current_date,
            total_techs=daily_techs,
            slots_per_tech=slots_per_tech
        )

        days_updated += 1
        current_date += timedelta(days=1)

    return {
        "success": True,
        "days_updated": days_updated,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat()
    }


def get_capacity_summary(account_id: int, service_type: str, days: int = 7) -> Dict[str, Any]:
    """
    Get capacity summary for next N days.

    Args:
        account_id: Account ID
        service_type: Service type
        days: Number of days to look ahead

    Returns:
        Capacity summary
    """
    start_date = date.today()
    end_date = start_date + timedelta(days=days)

    query = text("""
        SELECT
            date,
            total_techs_available,
            total_appointment_slots,
            booked_slots,
            capacity_utilization,
            days_booked_out,
            should_reduce_budget,
            should_increase_budget,
            recommended_budget_adjustment_pct
        FROM capacity_tracking
        WHERE account_id = :account_id
          AND service_type = :service_type
          AND date BETWEEN :start_date AND :end_date
        ORDER BY date ASC
    """)

    with db.engine.connect() as conn:
        result = conn.execute(query, {
            "account_id": account_id,
            "service_type": service_type,
            "start_date": start_date,
            "end_date": end_date
        })

        daily_capacity = [dict(row._mapping) for row in result]

    # Calculate averages
    avg_utilization = sum(d['capacity_utilization'] for d in daily_capacity) / len(daily_capacity) if daily_capacity else 0

    return {
        "success": True,
        "service_type": service_type,
        "daily_capacity": daily_capacity,
        "avg_utilization": round(avg_utilization, 2),
        "days_booked_out": daily_capacity[0]['days_booked_out'] if daily_capacity else 0,
        "budget_recommendation": get_capacity_based_recommendation(avg_utilization)
    }


def get_capacity_status(
    account_id: int,
    days: int = 7,
    service_type: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Get capacity status for date range (wrapper for compatibility with routes).

    Args:
        account_id: Account ID
        days: Days to look ahead
        service_type: Optional service type filter

    Returns:
        List of capacity data by service type
    """
    if service_type:
        # Single service type
        summary = get_capacity_summary(account_id, service_type, days)
        return [summary]
    else:
        # All service types
        service_types = ['hvac_ac', 'hvac_heat', 'plumbing', 'electrical', 'roofing']
        results = []

        for svc_type in service_types:
            try:
                summary = get_capacity_summary(account_id, svc_type, days)
                if summary['daily_capacity']:  # Only include if there's data
                    results.append(summary)
            except Exception:
                pass  # Skip service types with no data

        return results


def get_capacity_recommendations(account_id: int) -> List[Dict[str, Any]]:
    """
    Get budget recommendations based on current capacity across all service types.

    Args:
        account_id: Account ID

    Returns:
        List of recommendations by service type
    """
    service_types = ['hvac_ac', 'hvac_heat', 'plumbing', 'electrical', 'roofing']
    recommendations = []

    for service_type in service_types:
        try:
            # Get capacity for next 7 days
            summary = get_capacity_summary(account_id, service_type, days=7)

            if not summary['daily_capacity']:
                continue  # Skip if no data

            avg_utilization = summary['avg_utilization']
            days_booked_out = summary['days_booked_out']

            # Determine urgency
            urgency = "low"
            action = "maintain"

            if avg_utilization >= 0.90:
                urgency = "high"
                action = "reduce"
            elif avg_utilization >= 0.80:
                urgency = "medium"
                action = "reduce_slightly"
            elif avg_utilization < 0.50:
                urgency = "medium"
                action = "increase"

            recommendations.append({
                'service_type': service_type,
                'avg_utilization': round(avg_utilization * 100, 1),
                'days_booked_out': days_booked_out,
                'action': action,
                'urgency': urgency,
                'recommendation': summary['budget_recommendation']
            })

        except Exception:
            pass  # Skip service types with errors

    return recommendations
