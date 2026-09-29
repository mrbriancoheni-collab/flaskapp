# app/services/skimmer_client.py
"""
Skimmer API client.
Base URL: https://api.getskimmer.com/v1
Auth: skimmer-api-key header
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.getskimmer.com/v1"
_TIMEOUT = 15  # seconds


class SkimmerClient:
    """Thin wrapper around the Skimmer REST API."""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.base_url = _BASE_URL
        self.session = requests.Session()
        # Try both header names for compatibility
        self.session.headers.update(
            {
                "skimmer-api-key": api_key,
                "X-Skimmer-API-Key": api_key,
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )

    # ── Low-level helpers ────────────────────────────────────────────────────

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """
        Perform a GET request and return the parsed JSON body.
        Raises requests.HTTPError on 4xx/5xx responses.
        """
        url = f"{self.base_url}{path}"
        try:
            resp = self.session.get(url, params=params, timeout=_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except requests.HTTPError as exc:
            logger.warning(
                "Skimmer GET %s returned %s: %s",
                path,
                exc.response.status_code if exc.response is not None else "?",
                exc,
            )
            raise
        except Exception as exc:
            logger.warning("Skimmer GET %s failed: %s", path, exc)
            raise

    def _post(self, path: str, body: Dict[str, Any]) -> Any:
        """
        Perform a POST request and return the parsed JSON body.
        Raises requests.HTTPError on 4xx/5xx responses.
        """
        url = f"{self.base_url}{path}"
        try:
            resp = self.session.post(url, json=body, timeout=_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except requests.HTTPError as exc:
            logger.warning(
                "Skimmer POST %s returned %s: %s",
                path,
                exc.response.status_code if exc.response is not None else "?",
                exc,
            )
            raise
        except Exception as exc:
            logger.warning("Skimmer POST %s failed: %s", path, exc)
            raise

    # ── Public API methods ───────────────────────────────────────────────────

    def get_service_locations(self, page: int = 1, per_page: int = 50) -> List[Dict]:
        """GET /service-locations — returns list of service location objects."""
        try:
            data = self._get("/service-locations", params={"page": page, "per_page": per_page})
            if isinstance(data, list):
                return data
            # Some APIs wrap results in a key
            if isinstance(data, dict):
                for key in ("data", "results", "items", "service_locations"):
                    if key in data and isinstance(data[key], list):
                        return data[key]
            return []
        except Exception:
            return []

    def get_work_orders(
        self,
        status: Optional[str] = None,
        completed_after: Optional[str] = None,
        page: int = 1,
        per_page: int = 100,
    ) -> List[Dict]:
        """
        GET /work-orders with optional filters.

        :param status: e.g. "completed"
        :param completed_after: ISO8601 date string, e.g. "2024-01-15T00:00:00"
        :param page: 1-based page number
        :param per_page: results per page
        """
        params: Dict[str, Any] = {"page": page, "per_page": per_page}
        if status:
            params["status"] = status
        if completed_after:
            params["completed_after"] = completed_after

        try:
            data = self._get("/work-orders", params=params)
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                for key in ("data", "results", "items", "work_orders"):
                    if key in data and isinstance(data[key], list):
                        return data[key]
            return []
        except Exception:
            return []

    def get_customers(self, page: int = 1, per_page: int = 100) -> List[Dict]:
        """GET /customers — returns list of customer objects."""
        params: Dict[str, Any] = {"page": page, "per_page": per_page}
        try:
            data = self._get("/customers", params=params)
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                for key in ("data", "results", "items", "customers"):
                    if key in data and isinstance(data[key], list):
                        return data[key]
            return []
        except Exception:
            return []

    def get_work_order(self, work_order_id: str) -> Dict:
        """GET /work-orders/{id} — returns a single work order dict."""
        try:
            data = self._get(f"/work-orders/{work_order_id}")
            if isinstance(data, dict):
                return data
            return {}
        except Exception:
            return {}


# ---------------------------------------------------------------------------
# Module-level factory
# ---------------------------------------------------------------------------

def client_from_account(account_id: int) -> Optional[SkimmerClient]:
    """
    Load SkimmerAuth for the given account, decrypt the API key, and return
    a configured SkimmerClient. Returns None if no auth record exists or the
    key cannot be decrypted.
    """
    try:
        from app.models_skimmer import SkimmerAuth
        from app.services.crypto import decrypt

        auth = SkimmerAuth.query.filter_by(account_id=account_id).first()
        if not auth or not auth.api_key_encrypted:
            logger.debug("No Skimmer auth found for account %s", account_id)
            return None

        api_key = decrypt(auth.api_key_encrypted)
        return SkimmerClient(api_key)
    except Exception as exc:
        logger.warning("client_from_account(%s) failed: %s", account_id, exc)
        return None
