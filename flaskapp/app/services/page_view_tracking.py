# app/services/page_view_tracking.py
"""
Service for tracking user page views and analyzing user flow.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from flask import current_app
from sqlalchemy import func, desc, and_

from app import db
from app.models import PageView, User


def generate_session_id() -> str:
    """Generate a unique session ID for tracking."""
    return secrets.token_hex(32)


def parse_user_agent(user_agent: str) -> Tuple[str, str]:
    """
    Parse user agent string to extract device type and browser.

    Returns:
        Tuple of (device_type, browser)
        device_type: desktop, mobile, tablet
        browser: chrome, firefox, safari, edge, etc.
    """
    if not user_agent:
        return ("unknown", "unknown")

    ua_lower = user_agent.lower()

    # Detect device type
    if any(x in ua_lower for x in ["mobile", "android", "iphone"]):
        device_type = "mobile"
    elif "tablet" in ua_lower or "ipad" in ua_lower:
        device_type = "tablet"
    else:
        device_type = "desktop"

    # Detect browser
    if "edg/" in ua_lower or "edge/" in ua_lower:
        browser = "edge"
    elif "chrome" in ua_lower and "edg" not in ua_lower:
        browser = "chrome"
    elif "firefox" in ua_lower:
        browser = "firefox"
    elif "safari" in ua_lower and "chrome" not in ua_lower:
        browser = "safari"
    elif "opera" in ua_lower or "opr/" in ua_lower:
        browser = "opera"
    else:
        browser = "other"

    return (device_type, browser)


def extract_utm_params(query_string: str) -> Dict[str, Optional[str]]:
    """
    Extract UTM parameters from query string.

    Returns:
        Dict with utm_source, utm_medium, utm_campaign, utm_term, utm_content
    """
    if not query_string:
        return {
            "utm_source": None,
            "utm_medium": None,
            "utm_campaign": None,
            "utm_term": None,
            "utm_content": None,
        }

    # Remove leading '?' if present
    if query_string.startswith("?"):
        query_string = query_string[1:]

    params = parse_qs(query_string)

    return {
        "utm_source": params.get("utm_source", [None])[0],
        "utm_medium": params.get("utm_medium", [None])[0],
        "utm_campaign": params.get("utm_campaign", [None])[0],
        "utm_term": params.get("utm_term", [None])[0],
        "utm_content": params.get("utm_content", [None])[0],
    }


def log_page_view(
    session_id: str,
    path: str,
    page_title: Optional[str] = None,
    referrer: Optional[str] = None,
    query_string: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    user_id: Optional[int] = None,
) -> PageView:
    """
    Log a page view to the database.

    Args:
        session_id: Browser session ID
        path: URL path (e.g., "/", "/pricing")
        page_title: Page title from document.title
        referrer: Referring URL
        query_string: URL query parameters
        ip_address: Client IP address
        user_agent: User agent string
        user_id: User ID if logged in

    Returns:
        Created PageView instance
    """
    # Parse user agent
    device_type, browser = parse_user_agent(user_agent or "")

    # Extract UTM parameters
    utm_params = extract_utm_params(query_string or "")

    # Create page view record
    page_view = PageView(
        session_id=session_id,
        user_id=user_id,
        path=path,
        page_title=page_title,
        referrer=referrer,
        query_string=query_string,
        viewed_at=datetime.utcnow(),
        ip_address=ip_address,
        user_agent=user_agent,
        device_type=device_type,
        browser=browser,
        **utm_params,
    )

    db.session.add(page_view)
    db.session.commit()

    current_app.logger.info(
        f"Page view logged: session={session_id[:8]}... path={path} device={device_type} browser={browser}"
    )

    return page_view


def update_time_on_page(page_view_id: int, time_on_page: int) -> bool:
    """
    Update the time spent on a page.

    Args:
        page_view_id: ID of the PageView record
        time_on_page: Time spent in seconds

    Returns:
        True if updated successfully
    """
    try:
        page_view = PageView.query.get(page_view_id)
        if page_view:
            page_view.time_on_page = time_on_page
            db.session.commit()
            return True
        return False
    except Exception as e:
        current_app.logger.error(f"Error updating time on page: {e}")
        db.session.rollback()
        return False


def get_user_journey(session_id: str) -> List[PageView]:
    """
    Get all page views for a session in chronological order.

    Args:
        session_id: Browser session ID

    Returns:
        List of PageView records ordered by viewed_at
    """
    return PageView.query.filter_by(session_id=session_id).order_by(PageView.viewed_at.asc()).all()


def get_popular_paths(days: int = 7, limit: int = 10) -> List[Tuple[str, int]]:
    """
    Get the most popular pages by view count.

    Args:
        days: Number of days to look back
        limit: Maximum number of results

    Returns:
        List of (path, view_count) tuples
    """
    since = datetime.utcnow() - timedelta(days=days)

    results = (
        db.session.query(PageView.path, func.count(PageView.id).label("count"))
        .filter(PageView.viewed_at >= since)
        .group_by(PageView.path)
        .order_by(desc("count"))
        .limit(limit)
        .all()
    )

    return [(r.path, r.count) for r in results]


def get_common_user_flows(days: int = 7, limit: int = 10) -> List[Tuple[str, str, int]]:
    """
    Get the most common page-to-page transitions.

    Args:
        days: Number of days to look back
        limit: Maximum number of results

    Returns:
        List of (from_path, to_path, count) tuples
    """
    since = datetime.utcnow() - timedelta(days=days)

    # Get sequential page views within sessions
    subquery = (
        db.session.query(
            PageView.session_id,
            PageView.path,
            PageView.viewed_at,
            func.lag(PageView.path).over(
                partition_by=PageView.session_id,
                order_by=PageView.viewed_at
            ).label("prev_path")
        )
        .filter(PageView.viewed_at >= since)
        .subquery()
    )

    results = (
        db.session.query(
            subquery.c.prev_path,
            subquery.c.path,
            func.count().label("count")
        )
        .filter(subquery.c.prev_path.isnot(None))
        .group_by(subquery.c.prev_path, subquery.c.path)
        .order_by(desc("count"))
        .limit(limit)
        .all()
    )

    return [(r.prev_path, r.path, r.count) for r in results]


def get_exit_pages(days: int = 7, limit: int = 10) -> List[Tuple[str, int]]:
    """
    Get pages where users most commonly leave the site.

    Args:
        days: Number of days to look back
        limit: Maximum number of results

    Returns:
        List of (path, exit_count) tuples
    """
    since = datetime.utcnow() - timedelta(days=days)

    # Find the last page view in each session
    subquery = (
        db.session.query(
            PageView.session_id,
            func.max(PageView.viewed_at).label("last_viewed")
        )
        .filter(PageView.viewed_at >= since)
        .group_by(PageView.session_id)
        .subquery()
    )

    results = (
        db.session.query(PageView.path, func.count(PageView.id).label("count"))
        .join(
            subquery,
            and_(
                PageView.session_id == subquery.c.session_id,
                PageView.viewed_at == subquery.c.last_viewed
            )
        )
        .group_by(PageView.path)
        .order_by(desc("count"))
        .limit(limit)
        .all()
    )

    return [(r.path, r.count) for r in results]


def get_conversion_funnel_stats(funnel_paths: List[str], days: int = 7) -> Dict[str, any]:
    """
    Analyze conversion rates through a defined funnel.

    Args:
        funnel_paths: List of paths in order (e.g., ["/", "/pricing", "/signup", "/dashboard"])
        days: Number of days to look back

    Returns:
        Dict with funnel statistics
    """
    since = datetime.utcnow() - timedelta(days=days)

    stats = {
        "funnel": funnel_paths,
        "steps": [],
        "total_sessions": 0,
    }

    # Get all sessions that started at the first step
    sessions_at_step_0 = set(
        pv.session_id for pv in
        PageView.query.filter(
            PageView.path == funnel_paths[0],
            PageView.viewed_at >= since
        ).all()
    )

    stats["total_sessions"] = len(sessions_at_step_0)
    current_sessions = sessions_at_step_0

    for i, path in enumerate(funnel_paths):
        # Count sessions that reached this step
        sessions_at_step = set(
            pv.session_id for pv in
            PageView.query.filter(
                PageView.path == path,
                PageView.viewed_at >= since,
                PageView.session_id.in_(current_sessions)
            ).all()
        )

        count = len(sessions_at_step)
        conversion_rate = (count / stats["total_sessions"] * 100) if stats["total_sessions"] > 0 else 0
        drop_off = len(current_sessions) - count if i > 0 else 0

        stats["steps"].append({
            "step": i + 1,
            "path": path,
            "sessions": count,
            "conversion_rate": round(conversion_rate, 2),
            "drop_off": drop_off,
        })

        # Only sessions that made it to this step can proceed to next
        current_sessions = sessions_at_step

    return stats


def get_device_breakdown(days: int = 7) -> Dict[str, int]:
    """
    Get breakdown of page views by device type.

    Args:
        days: Number of days to look back

    Returns:
        Dict mapping device_type to view count
    """
    since = datetime.utcnow() - timedelta(days=days)

    results = (
        db.session.query(PageView.device_type, func.count(PageView.id).label("count"))
        .filter(PageView.viewed_at >= since)
        .group_by(PageView.device_type)
        .all()
    )

    return {r.device_type or "unknown": r.count for r in results}


def get_traffic_sources(days: int = 7) -> Dict[str, int]:
    """
    Get breakdown of traffic by UTM source.

    Args:
        days: Number of days to look back

    Returns:
        Dict mapping utm_source to session count
    """
    since = datetime.utcnow() - timedelta(days=days)

    # Count unique sessions per UTM source
    results = (
        db.session.query(PageView.utm_source, func.count(func.distinct(PageView.session_id)).label("count"))
        .filter(PageView.viewed_at >= since)
        .group_by(PageView.utm_source)
        .all()
    )

    return {(r.utm_source or "direct"): r.count for r in results}
