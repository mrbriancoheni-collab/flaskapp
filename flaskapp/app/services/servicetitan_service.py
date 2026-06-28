"""
ServiceTitan API Service
Handles all interactions with the ServiceTitan API for data synchronization.

ServiceTitan API Documentation:
https://developer.servicetitan.io/

OAuth 2.0 Flow:
1. Get access token using client credentials
2. Use access token for API requests
3. Refresh token when expired
"""
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import requests
from requests.exceptions import RequestException

from app import db
from app.models import (
    ServiceTitanConnection,
    ServiceTitanCustomer,
    ServiceTitanJob,
    ServiceTitanJobType,
    ServiceTitanTechnician,
    ServiceTitanCapacity,
    ServiceTitanSyncLog
)


class ServiceTitanService:
    """Service class for interacting with ServiceTitan API"""

    # ServiceTitan API endpoints
    BASE_URL = "https://api.servicetitan.io"
    AUTH_URL = "https://auth.servicetitan.io/connect/token"

    def __init__(self, account_id: int):
        """
        Initialize ServiceTitan service for a specific account.

        Args:
            account_id: The account ID to sync data for
        """
        self.account_id = account_id
        self.connection = self._get_connection()

    def _get_connection(self) -> Optional[ServiceTitanConnection]:
        """Get the ServiceTitan connection for this account"""
        return ServiceTitanConnection.query.filter_by(account_id=self.account_id).first()

    def _ensure_valid_token(self) -> bool:
        """
        Ensure we have a valid access token, refreshing if necessary.

        Returns:
            True if token is valid, False otherwise
        """
        if not self.connection:
            return False

        # Check if token is expired or about to expire
        if not self.connection.access_token or not self.connection.token_expires_at:
            return self._get_access_token()

        # Refresh token if it expires in less than 5 minutes
        if self.connection.token_expires_at < datetime.utcnow() + timedelta(minutes=5):
            return self._refresh_access_token()

        return True

    def _get_access_token(self) -> bool:
        """
        Get a new access token using client credentials.

        Returns:
            True if successful, False otherwise
        """
        if not self.connection:
            return False

        try:
            try:
                from app.services.crypto import decrypt
                _secret = decrypt(self.connection.client_secret)
            except Exception:
                _secret = self.connection.client_secret
            response = requests.post(
                self.AUTH_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.connection.client_id,
                    "client_secret": _secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=30
            )
            response.raise_for_status()

            token_data = response.json()
            self.connection.access_token = token_data.get("access_token")
            self.connection.token_expires_at = datetime.utcnow() + timedelta(
                seconds=token_data.get("expires_in", 3600)
            )

            db.session.commit()
            return True

        except RequestException as e:
            print(f"Error getting access token: {e}")
            return False

    def _refresh_access_token(self) -> bool:
        """
        Refresh the access token using refresh token.

        Returns:
            True if successful, False if needs to get new token
        """
        if not self.connection or not self.connection.refresh_token:
            return self._get_access_token()

        try:
            try:
                from app.services.crypto import decrypt
                _secret = decrypt(self.connection.client_secret)
            except Exception:
                _secret = self.connection.client_secret
            response = requests.post(
                self.AUTH_URL,
                data={
                    "grant_type": "refresh_token",
                    "client_id": self.connection.client_id,
                    "client_secret": _secret,
                    "refresh_token": self.connection.refresh_token,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=30
            )
            response.raise_for_status()

            token_data = response.json()
            self.connection.access_token = token_data.get("access_token")
            self.connection.refresh_token = token_data.get("refresh_token", self.connection.refresh_token)
            self.connection.token_expires_at = datetime.utcnow() + timedelta(
                seconds=token_data.get("expires_in", 3600)
            )

            db.session.commit()
            return True

        except RequestException:
            # If refresh fails, get new token
            return self._get_access_token()

    def _make_api_request(
        self,
        endpoint: str,
        method: str = "GET",
        params: Optional[Dict] = None,
        data: Optional[Dict] = None
    ) -> Optional[Dict]:
        """
        Make an authenticated request to the ServiceTitan API.

        Args:
            endpoint: API endpoint (e.g., "/jpm/v2/tenant/{tenant}/customers")
            method: HTTP method (GET, POST, etc.)
            params: Query parameters
            data: Request body data

        Returns:
            JSON response data or None if error
        """
        if not self._ensure_valid_token():
            return None

        # Replace {tenant} placeholder in endpoint
        endpoint = endpoint.replace("{tenant}", str(self.connection.tenant_id))
        url = f"{self.BASE_URL}{endpoint}"

        headers = {
            "Authorization": f"Bearer {self.connection.access_token}",
            "ST-App-Key": self.connection.app_key or "",
        }

        try:
            response = requests.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                json=data,
                timeout=60
            )
            response.raise_for_status()
            return response.json()

        except RequestException as e:
            print(f"API request error: {e}")
            return None

    def sync_customers(self, start_date: Optional[datetime] = None) -> Dict[str, int]:
        """
        Sync customer data from ServiceTitan.

        Args:
            start_date: Only sync customers modified after this date

        Returns:
            Dict with sync statistics
        """
        sync_log = ServiceTitanSyncLog(
            account_id=self.account_id,
            sync_type="customers",
            status="running"
        )
        db.session.add(sync_log)
        db.session.commit()

        try:
            stats = {"fetched": 0, "created": 0, "updated": 0, "failed": 0}

            # Build query parameters
            params = {
                "pageSize": 500,
                "page": 1
            }
            if start_date:
                params["modifiedOnOrAfter"] = start_date.isoformat()

            # Paginate through all customers
            while True:
                response = self._make_api_request(
                    "/crm/v2/tenant/{tenant}/customers",
                    params=params
                )

                if not response or "data" not in response:
                    break

                customers = response.get("data", [])
                if not customers:
                    break

                for customer_data in customers:
                    try:
                        self._upsert_customer(customer_data)
                        stats["fetched"] += 1
                    except Exception as e:
                        print(f"Error upserting customer: {e}")
                        stats["failed"] += 1

                # Check if there are more pages
                has_more = response.get("hasMore", False)
                if not has_more:
                    break

                params["page"] += 1

            # Update sync log
            sync_log.status = "success"
            sync_log.completed_at = datetime.utcnow()
            sync_log.duration_seconds = int((sync_log.completed_at - sync_log.started_at).total_seconds())
            sync_log.records_fetched = stats["fetched"]
            sync_log.records_failed = stats["failed"]

            db.session.commit()
            return stats

        except Exception as e:
            sync_log.status = "error"
            sync_log.error_message = str(e)
            sync_log.completed_at = datetime.utcnow()
            db.session.commit()
            raise

    def _upsert_customer(self, customer_data: Dict) -> ServiceTitanCustomer:
        """Create or update a customer record"""
        st_customer_id = customer_data.get("id")

        customer = ServiceTitanCustomer.query.filter_by(
            account_id=self.account_id,
            st_customer_id=st_customer_id
        ).first()

        if not customer:
            customer = ServiceTitanCustomer(
                account_id=self.account_id,
                st_customer_id=st_customer_id
            )
            db.session.add(customer)

        # Update fields
        customer.name = customer_data.get("name")
        customer.first_name = customer_data.get("firstName")
        customer.last_name = customer_data.get("lastName")
        customer.email = customer_data.get("email")
        customer.phone = customer_data.get("phoneNumber")
        customer.customer_type = customer_data.get("type")
        customer.st_data = customer_data
        customer.st_modified_at = datetime.fromisoformat(
            customer_data.get("modifiedOn", "").replace("Z", "+00:00")
        ) if customer_data.get("modifiedOn") else None

        db.session.commit()
        return customer

    def sync_jobs(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Dict[str, int]:
        """
        Sync job data from ServiceTitan.

        Args:
            start_date: Only sync jobs modified after this date
            end_date: Only sync jobs modified before this date

        Returns:
            Dict with sync statistics
        """
        sync_log = ServiceTitanSyncLog(
            account_id=self.account_id,
            sync_type="jobs",
            status="running"
        )
        db.session.add(sync_log)
        db.session.commit()

        try:
            stats = {"fetched": 0, "created": 0, "updated": 0, "failed": 0}

            params = {
                "pageSize": 500,
                "page": 1
            }
            if start_date:
                params["modifiedOnOrAfter"] = start_date.isoformat()
            if end_date:
                params["modifiedBefore"] = end_date.isoformat()

            while True:
                response = self._make_api_request(
                    "/jpm/v2/tenant/{tenant}/jobs",
                    params=params
                )

                if not response or "data" not in response:
                    break

                jobs = response.get("data", [])
                if not jobs:
                    break

                for job_data in jobs:
                    try:
                        self._upsert_job(job_data)
                        stats["fetched"] += 1
                    except Exception as e:
                        print(f"Error upserting job: {e}")
                        stats["failed"] += 1

                if not response.get("hasMore", False):
                    break

                params["page"] += 1

            sync_log.status = "success"
            sync_log.completed_at = datetime.utcnow()
            sync_log.duration_seconds = int((sync_log.completed_at - sync_log.started_at).total_seconds())
            sync_log.records_fetched = stats["fetched"]
            sync_log.records_failed = stats["failed"]

            db.session.commit()
            return stats

        except Exception as e:
            sync_log.status = "error"
            sync_log.error_message = str(e)
            sync_log.completed_at = datetime.utcnow()
            db.session.commit()
            raise

    def _upsert_job(self, job_data: Dict) -> ServiceTitanJob:
        """Create or update a job record"""
        st_job_id = job_data.get("id")

        job = ServiceTitanJob.query.filter_by(
            account_id=self.account_id,
            st_job_id=st_job_id
        ).first()

        if not job:
            job = ServiceTitanJob(
                account_id=self.account_id,
                st_job_id=st_job_id
            )
            db.session.add(job)

        # Update fields
        job.st_customer_id = job_data.get("customerId")
        job.st_job_type_id = job_data.get("jobTypeId")
        job.st_business_unit_id = job_data.get("businessUnitId")
        job.job_number = job_data.get("jobNumber")
        job.job_status = job_data.get("jobStatus")
        job.total_amount = job_data.get("total")
        job.invoice_amount = job_data.get("invoiceAmount")
        job.outstanding_balance = job_data.get("outstandingBalance")
        job.lead_source = job_data.get("leadSource")
        job.campaign_name = job_data.get("campaignName")
        job.st_data = job_data

        # Parse dates
        prev_status = job.job_status
        if job_data.get("scheduledOn"):
            job.scheduled_date = datetime.fromisoformat(job_data["scheduledOn"].replace("Z", "+00:00"))
        if job_data.get("completedOn"):
            job.completed_date = datetime.fromisoformat(job_data["completedOn"].replace("Z", "+00:00"))

        # Populate normalised CRMJob fields
        if job_data.get("scheduledOn") and hasattr(job, "appointment_at") and not job.appointment_at:
            try:
                from app.models_crm import CRMJob as _CRMJob  # noqa: F401 — ensure table exists
                job.appointment_at = datetime.fromisoformat(
                    job_data["scheduledOn"].replace("Z", "+00:00")
                )
            except Exception:
                pass

        db.session.commit()

        new_status = (job.job_status or "").lower()
        old_status = (prev_status or "").lower()

        # Fire review request on first completion
        if new_status == "completed" and old_status != "completed":
            try:
                from app.services.review_request_service import on_crm_job_completed
                on_crm_job_completed(self.account_id, job)
            except Exception:
                pass

        # Detect estimates in ServiceTitan job records
        try:
            from app.services.crm_normalizer import handle_servicetitan_job
            if self.connection:
                handle_servicetitan_job(self.account_id, self.connection.id, job_data)
        except Exception:
            pass

        # Fire appointment hook when appointment_at is newly set
        if job.appointment_at and not getattr(job, "_appt_notified", False):
            try:
                from app.services.crm_normalizer import on_appointment_booked
                on_appointment_booked(self.account_id, job)
            except Exception:
                pass

        return job

    def calculate_capacity_metrics(self, target_date: datetime) -> Optional[ServiceTitanCapacity]:
        """
        Calculate capacity metrics for a specific date.
        This analyzes scheduled jobs and technician availability.

        Args:
            target_date: The date to calculate capacity for

        Returns:
            ServiceTitanCapacity record or None
        """
        # Query jobs scheduled for this date
        jobs = ServiceTitanJob.query.filter(
            ServiceTitanJob.account_id == self.account_id,
            db.func.date(ServiceTitanJob.scheduled_date) == target_date.date()
        ).all()

        # Query active technicians
        technicians = ServiceTitanTechnician.query.filter_by(
            account_id=self.account_id,
            is_active=True
        ).count()

        # Calculate metrics
        booked_slots = len(jobs)
        # Assume 8 jobs per tech per day (configurable)
        total_slots = technicians * 8
        available_slots = max(0, total_slots - booked_slots)
        utilization = (booked_slots / total_slots * 100) if total_slots > 0 else 0

        # Calculate scheduled revenue
        scheduled_revenue = sum(float(job.total_amount or 0) for job in jobs)

        # Calculate capacity score (0-100, inversely proportional to utilization)
        # Lower utilization = higher score = more capacity for ads
        capacity_score = max(0, 100 - utilization)

        # Upsert capacity record
        capacity = ServiceTitanCapacity.query.filter_by(
            account_id=self.account_id,
            capacity_date=target_date.date()
        ).first()

        if not capacity:
            capacity = ServiceTitanCapacity(
                account_id=self.account_id,
                capacity_date=target_date.date()
            )
            db.session.add(capacity)

        capacity.total_slots = total_slots
        capacity.booked_slots = booked_slots
        capacity.available_slots = available_slots
        capacity.utilization_percent = utilization
        capacity.total_technicians = technicians
        capacity.scheduled_revenue = scheduled_revenue
        capacity.capacity_score = capacity_score

        db.session.commit()
        return capacity

    def get_capacity_based_budget_multiplier(self, days_ahead: int = 7) -> float:
        """
        Calculate a budget multiplier based on available capacity.

        Args:
            days_ahead: Number of days to look ahead for capacity

        Returns:
            Budget multiplier (0.5 to 1.5)
            - Low capacity (high utilization) = reduce budget (0.5-0.9)
            - High capacity (low utilization) = increase budget (1.0-1.5)
        """
        target_date = datetime.utcnow() + timedelta(days=days_ahead)

        capacity = ServiceTitanCapacity.query.filter(
            ServiceTitanCapacity.account_id == self.account_id,
            ServiceTitanCapacity.capacity_date >= datetime.utcnow().date(),
            ServiceTitanCapacity.capacity_date <= target_date.date()
        ).all()

        if not capacity:
            return 1.0  # No data, keep budget unchanged

        avg_utilization = sum(float(c.utilization_percent or 0) for c in capacity) / len(capacity)

        # Map utilization to budget multiplier
        # 0-40% utilization: increase budget (1.2-1.5x)
        # 40-70% utilization: normal budget (1.0-1.2x)
        # 70-100% utilization: reduce budget (0.5-1.0x)
        if avg_utilization < 40:
            return 1.5 - (avg_utilization / 40) * 0.3  # 1.5 to 1.2
        elif avg_utilization < 70:
            return 1.2 - ((avg_utilization - 40) / 30) * 0.2  # 1.2 to 1.0
        else:
            return 1.0 - ((avg_utilization - 70) / 30) * 0.5  # 1.0 to 0.5

    def test_connection(self) -> Dict[str, Any]:
        """
        Test the ServiceTitan API connection.

        Returns:
            Dict with test results
        """
        if not self.connection:
            return {"success": False, "error": "No connection configured"}

        if not self._ensure_valid_token():
            return {"success": False, "error": "Failed to obtain access token"}

        # Try to fetch a small amount of data
        response = self._make_api_request(
            "/crm/v2/tenant/{tenant}/customers",
            params={"pageSize": 1}
        )

        if response:
            return {"success": True, "message": "Connection successful"}
        else:
            return {"success": False, "error": "API request failed"}
