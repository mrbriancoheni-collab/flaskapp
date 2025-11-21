# app/services/capacity_tracking_service.py
"""
Capacity Tracking Service (No CRM Required!)

Track technician capacity and adjust budgets when fully booked.

Features:
- Manual capacity entry (# techs, slots per tech)
- Simple booking log
- Auto-calculated utilization
- Budget recommendations based on capacity
- No CRM integration needed - standalone system
"""

from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta, date
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)


class CapacityTrackingService:
    """Service for tracking technician capacity and utilization."""

    def __init__(self, db_connection):
        """
        Initialize the service.

        Args:
            db_connection: Database connection object
        """
        self.db = db_connection

    def set_daily_capacity(
        self,
        account_id: int,
        tracking_date: date,
        num_technicians: int,
        slots_per_tech: int,
        notes: Optional[str] = None
    ) -> bool:
        """
        Set daily capacity for a date.

        Args:
            account_id: Account ID
            tracking_date: Date to track
            num_technicians: Number of technicians working
            slots_per_tech: Appointment slots per technician
            notes: Optional notes

        Returns:
            True if successful
        """
        cursor = self.db.cursor()

        try:
            total_capacity = num_technicians * slots_per_tech

            cursor.execute("""
                INSERT INTO capacity_tracking (
                    account_id, tracking_date, total_capacity,
                    num_technicians, slots_per_tech, notes
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    total_capacity = VALUES(total_capacity),
                    num_technicians = VALUES(num_technicians),
                    slots_per_tech = VALUES(slots_per_tech),
                    notes = VALUES(notes),
                    updated_at = CURRENT_TIMESTAMP
            """, (account_id, tracking_date, total_capacity, num_technicians, slots_per_tech, notes))

            self.db.commit()

            # Recalculate utilization
            self._recalculate_utilization(account_id, tracking_date)

            cursor.close()
            return True

        except Exception as e:
            logger.error(f"Error setting daily capacity: {e}")
            self.db.rollback()
            cursor.close()
            return False

    def add_booking(
        self,
        account_id: int,
        booking_date: date,
        booking_time: str,
        customer_name: Optional[str] = None,
        service_type: Optional[str] = None,
        lead_source: str = 'other',
        campaign_id: Optional[str] = None,
        technician_assigned: Optional[str] = None,
        notes: Optional[str] = None
    ) -> Optional[int]:
        """
        Add a booking to the log.

        Args:
            account_id: Account ID
            booking_date: Date of appointment
            booking_time: Time of appointment (HH:MM format)
            customer_name: Optional customer name
            service_type: Optional service type
            lead_source: Where the lead came from
            campaign_id: Optional Google Ads campaign ID
            technician_assigned: Optional tech name
            notes: Optional notes

        Returns:
            Booking ID if successful, None otherwise
        """
        # First, ensure capacity tracking exists for this date
        capacity_id = self._get_or_create_capacity_tracking(account_id, booking_date)
        if not capacity_id:
            return None

        cursor = self.db.cursor()

        try:
            cursor.execute("""
                INSERT INTO capacity_bookings (
                    capacity_tracking_id, account_id, booking_date, booking_time,
                    customer_name, service_type, lead_source, campaign_id,
                    technician_assigned, notes, status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'scheduled')
            """, (
                capacity_id, account_id, booking_date, booking_time,
                customer_name, service_type, lead_source, campaign_id,
                technician_assigned, notes
            ))

            booking_id = cursor.lastrowid
            self.db.commit()

            # Recalculate utilization for this date
            self._recalculate_utilization(account_id, booking_date)

            cursor.close()
            return booking_id

        except Exception as e:
            logger.error(f"Error adding booking: {e}")
            self.db.rollback()
            cursor.close()
            return None

    def _get_or_create_capacity_tracking(self, account_id: int, tracking_date: date) -> Optional[int]:
        """Get or create capacity tracking record for a date."""
        cursor = self.db.cursor(dictionary=True)

        # Check if exists
        cursor.execute("""
            SELECT id FROM capacity_tracking
            WHERE account_id = %s AND tracking_date = %s
        """, (account_id, tracking_date))

        result = cursor.fetchone()

        if result:
            cursor.close()
            return result['id']

        # Create with default capacity (0 - needs to be set)
        try:
            cursor.execute("""
                INSERT INTO capacity_tracking (
                    account_id, tracking_date, total_capacity,
                    num_technicians, slots_per_tech
                ) VALUES (%s, %s, 0, 0, 0)
            """, (account_id, tracking_date))

            capacity_id = cursor.lastrowid
            self.db.commit()
            cursor.close()
            return capacity_id

        except Exception as e:
            logger.error(f"Error creating capacity tracking: {e}")
            self.db.rollback()
            cursor.close()
            return None

    def _recalculate_utilization(self, account_id: int, tracking_date: date) -> bool:
        """Recalculate utilization and budget recommendation for a date."""
        cursor = self.db.cursor(dictionary=True)

        try:
            # Get capacity
            cursor.execute("""
                SELECT id, total_capacity FROM capacity_tracking
                WHERE account_id = %s AND tracking_date = %s
            """, (account_id, tracking_date))

            capacity_record = cursor.fetchone()
            if not capacity_record:
                cursor.close()
                return False

            capacity_id = capacity_record['id']
            total_capacity = capacity_record['total_capacity']

            # Count booked slots (scheduled or completed)
            cursor.execute("""
                SELECT COUNT(*) as booked_count
                FROM capacity_bookings
                WHERE capacity_tracking_id = %s
                AND status IN ('scheduled', 'completed')
            """, (capacity_id,))

            booked_result = cursor.fetchone()
            booked_slots = booked_result['booked_count'] if booked_result else 0

            # Calculate utilization
            available_slots = total_capacity - booked_slots
            utilization_pct = (booked_slots / total_capacity * 100) if total_capacity > 0 else 0

            # Determine budget recommendation
            budget_rec, budget_change_pct = self._get_budget_recommendation(utilization_pct)

            # Update capacity tracking
            cursor.execute("""
                UPDATE capacity_tracking
                SET booked_slots = %s,
                    available_slots = %s,
                    utilization_pct = %s,
                    budget_recommendation = %s,
                    recommended_budget_change_pct = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (booked_slots, available_slots, utilization_pct, budget_rec, budget_change_pct, capacity_id))

            self.db.commit()
            cursor.close()
            return True

        except Exception as e:
            logger.error(f"Error recalculating utilization: {e}")
            self.db.rollback()
            cursor.close()
            return False

    def _get_budget_recommendation(self, utilization_pct: float) -> tuple:
        """
        Get budget recommendation based on utilization.

        Args:
            utilization_pct: Current utilization percentage

        Returns:
            Tuple of (recommendation, change_pct)
        """
        if utilization_pct >= 90:
            return ('decrease', -40.0)  # Reduce budget 40%
        elif utilization_pct >= 80:
            return ('decrease', -15.0)  # Reduce budget 15%
        elif utilization_pct >= 60:
            return ('maintain', 0.0)    # Optimal range
        elif utilization_pct >= 30:
            return ('increase', 15.0)   # Increase budget 15%
        else:
            return ('increase', 30.0)   # Increase budget 30%

    def get_capacity_for_date(self, account_id: int, tracking_date: date) -> Optional[Dict[str, Any]]:
        """
        Get capacity data for a specific date.

        Args:
            account_id: Account ID
            tracking_date: Date to retrieve

        Returns:
            Capacity data dict or None
        """
        cursor = self.db.cursor(dictionary=True)
        cursor.execute("""
            SELECT * FROM capacity_tracking
            WHERE account_id = %s AND tracking_date = %s
        """, (account_id, tracking_date))

        capacity = cursor.fetchone()
        cursor.close()
        return capacity

    def get_capacity_range(
        self,
        account_id: int,
        start_date: date,
        end_date: date
    ) -> List[Dict[str, Any]]:
        """
        Get capacity data for a date range.

        Args:
            account_id: Account ID
            start_date: Start date
            end_date: End date

        Returns:
            List of capacity records
        """
        cursor = self.db.cursor(dictionary=True)
        cursor.execute("""
            SELECT * FROM capacity_tracking
            WHERE account_id = %s
            AND tracking_date BETWEEN %s AND %s
            ORDER BY tracking_date DESC
        """, (account_id, start_date, end_date))

        capacities = cursor.fetchall()
        cursor.close()
        return capacities

    def get_bookings_for_date(self, account_id: int, booking_date: date) -> List[Dict[str, Any]]:
        """
        Get all bookings for a specific date.

        Args:
            account_id: Account ID
            booking_date: Date to retrieve

        Returns:
            List of bookings
        """
        cursor = self.db.cursor(dictionary=True)
        cursor.execute("""
            SELECT b.* FROM capacity_bookings b
            JOIN capacity_tracking c ON b.capacity_tracking_id = c.id
            WHERE b.account_id = %s AND b.booking_date = %s
            ORDER BY b.booking_time
        """, (account_id, booking_date))

        bookings = cursor.fetchall()
        cursor.close()
        return bookings

    def update_booking_status(
        self,
        booking_id: int,
        account_id: int,
        status: str
    ) -> bool:
        """
        Update booking status.

        Args:
            booking_id: Booking ID
            account_id: Account ID (for security)
            status: New status (scheduled, completed, cancelled, no_show)

        Returns:
            True if successful
        """
        cursor = self.db.cursor(dictionary=True)

        try:
            # Get the booking to recalculate utilization
            cursor.execute("""
                SELECT booking_date FROM capacity_bookings
                WHERE id = %s AND account_id = %s
            """, (booking_id, account_id))

            booking = cursor.fetchone()
            if not booking:
                cursor.close()
                return False

            booking_date = booking['booking_date']

            # Update status
            cursor.execute("""
                UPDATE capacity_bookings
                SET status = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s AND account_id = %s
            """, (status, booking_id, account_id))

            self.db.commit()

            # Recalculate utilization
            self._recalculate_utilization(account_id, booking_date)

            cursor.close()
            return True

        except Exception as e:
            logger.error(f"Error updating booking status: {e}")
            self.db.rollback()
            cursor.close()
            return False

    def get_current_utilization(self, account_id: int) -> Optional[float]:
        """
        Get current day's capacity utilization.

        Args:
            account_id: Account ID

        Returns:
            Utilization percentage or None
        """
        today = datetime.now().date()
        capacity = self.get_capacity_for_date(account_id, today)

        if capacity:
            return float(capacity.get('utilization_pct', 0))

        return None

    def get_lead_source_breakdown(
        self,
        account_id: int,
        start_date: date,
        end_date: date
    ) -> List[Dict[str, Any]]:
        """
        Get breakdown of bookings by lead source.

        Args:
            account_id: Account ID
            start_date: Start date
            end_date: End date

        Returns:
            List of lead source stats
        """
        cursor = self.db.cursor(dictionary=True)
        cursor.execute("""
            SELECT
                lead_source,
                COUNT(*) as booking_count,
                COUNT(CASE WHEN status = 'completed' THEN 1 END) as completed_count,
                COUNT(CASE WHEN status = 'cancelled' THEN 1 END) as cancelled_count,
                COUNT(CASE WHEN status = 'no_show' THEN 1 END) as no_show_count
            FROM capacity_bookings
            WHERE account_id = %s
            AND booking_date BETWEEN %s AND %s
            GROUP BY lead_source
            ORDER BY booking_count DESC
        """, (account_id, start_date, end_date))

        breakdown = cursor.fetchall()
        cursor.close()
        return breakdown
