# app/services/auto_historical_pull.py
"""
Automatic historical data pull trigger.
Runs after OAuth connections are activated.
"""

from __future__ import annotations
import datetime as dt
from typing import Optional
from flask import current_app


def trigger_historical_pull_after_connection(
    account_id: int,
    source_type: str,
    months: int = 12,
    run_async: bool = True
) -> None:
    """
    Trigger historical data pull after API connection is activated.

    This is called automatically after:
    - Google Ads OAuth success
    - Facebook Ads OAuth success
    - Google Analytics OAuth success
    - Google Search Console OAuth success
    - GLSA setup
    - GMB OAuth success

    Args:
        account_id: Account ID
        source_type: 'google_ads', 'fbads', 'google_analytics', 'search_console', 'glsa', 'gmb'
        months: Number of months to pull (default 12)
        run_async: Run in background (default True)
    """
    current_app.logger.info(
        f"🔄 Auto-triggering historical data pull for account {account_id}, "
        f"source: {source_type}, months: {months}"
    )

    if run_async:
        # Run in background thread
        _run_pull_in_background(account_id, source_type, months)
    else:
        # Run synchronously (blocks until complete)
        _run_pull_sync(account_id, source_type, months)


def _run_pull_in_background(account_id: int, source_type: str, months: int) -> None:
    """Run historical pull in background thread."""
    import threading

    def background_task():
        try:
            from app import create_app
            app = create_app()

            with app.app_context():
                _run_pull_sync(account_id, source_type, months)

        except Exception as e:
            # Log error but don't crash
            if current_app:
                current_app.logger.exception(
                    f"Background historical pull failed for account {account_id}, "
                    f"source {source_type}: {e}"
                )

    thread = threading.Thread(target=background_task, daemon=True)
    thread.start()

    current_app.logger.info(
        f"✓ Background historical pull started for account {account_id}, source {source_type}"
    )


def _run_pull_sync(account_id: int, source_type: str, months: int) -> None:
    """Run historical pull synchronously."""
    from app.services.historical_data_pull import (
        pull_google_ads_historical,
        pull_facebook_ads_historical,
        pull_google_analytics_historical,
        pull_search_console_historical,
        pull_glsa_historical,
        pull_gmb_historical
    )

    end_date = dt.date.today()
    start_date = end_date - dt.timedelta(days=months * 30)  # Approximate

    try:
        # Map source type to pull function
        pull_functions = {
            'google_ads': pull_google_ads_historical,
            'fbads': pull_facebook_ads_historical,
            'google_analytics': pull_google_analytics_historical,
            'search_console': pull_search_console_historical,
            'glsa': pull_glsa_historical,
            'gmb': pull_gmb_historical,
        }

        pull_func = pull_functions.get(source_type)
        if not pull_func:
            current_app.logger.warning(f"Unknown source type: {source_type}")
            return

        # Run the pull
        result = pull_func(
            account_id=account_id,
            start_date=start_date,
            end_date=end_date,
            force=False  # Don't overwrite existing data
        )

        if result.get('success'):
            imported = result.get('imported', 0)
            current_app.logger.info(
                f"✓ Auto-pull completed for account {account_id}, "
                f"source {source_type}: {imported} records imported"
            )
        else:
            error = result.get('error', 'Unknown error')
            current_app.logger.warning(
                f"Auto-pull failed for account {account_id}, "
                f"source {source_type}: {error}"
            )

    except Exception as e:
        current_app.logger.exception(
            f"Error in auto-pull for account {account_id}, source {source_type}: {e}"
        )


def schedule_delayed_pull(
    account_id: int,
    source_type: str,
    delay_seconds: int = 60,
    months: int = 12
) -> None:
    """
    Schedule a historical pull to run after a delay.
    Useful for giving OAuth tokens time to propagate.

    Args:
        account_id: Account ID
        source_type: Source type
        delay_seconds: Delay before starting pull (default 60 seconds)
        months: Number of months to pull
    """
    import threading
    import time

    def delayed_task():
        try:
            time.sleep(delay_seconds)

            from app import create_app
            app = create_app()

            with app.app_context():
                _run_pull_sync(account_id, source_type, months)

        except Exception as e:
            if current_app:
                current_app.logger.exception(
                    f"Delayed historical pull failed for account {account_id}, "
                    f"source {source_type}: {e}"
                )

    thread = threading.Thread(target=delayed_task, daemon=True)
    thread.start()

    current_app.logger.info(
        f"✓ Scheduled delayed historical pull for account {account_id}, "
        f"source {source_type} in {delay_seconds} seconds"
    )


def should_auto_pull(account_id: int, source_type: str) -> bool:
    """
    Check if we should auto-pull for this account/source.
    Returns False if data already exists or if disabled in settings.

    Args:
        account_id: Account ID
        source_type: Source type

    Returns:
        True if should pull, False otherwise
    """
    # Check if auto-pull is disabled globally
    auto_pull_enabled = current_app.config.get('AUTO_HISTORICAL_PULL_ENABLED', True)
    if not auto_pull_enabled:
        return False

    # Check if data already exists
    try:
        from app.services.historical_data_pull import check_existing_data
        data = check_existing_data(account_id, source_type)

        # If we have recent data (within last 7 days), skip
        if data.get('has_data') and data.get('latest_date'):
            latest_date_str = data['latest_date']
            latest_date = dt.datetime.strptime(latest_date_str, '%Y-%m-%d').date()
            days_old = (dt.date.today() - latest_date).days

            if days_old < 7:
                current_app.logger.info(
                    f"Skipping auto-pull for account {account_id}, source {source_type}: "
                    f"Recent data exists (latest: {latest_date_str})"
                )
                return False

    except Exception as e:
        current_app.logger.warning(f"Error checking existing data: {e}")
        # If check fails, proceed with pull anyway

    return True


def trigger_pull_for_newly_connected_channel(
    account_id: int,
    source_type: str,
    months: int = 12
) -> dict:
    """
    Main entry point for triggering historical pull after channel connection.

    This function:
    1. Checks if auto-pull should run
    2. Triggers background pull if appropriate
    3. Returns status message

    Args:
        account_id: Account ID
        source_type: Source type
        months: Number of months to pull

    Returns:
        Dictionary with status
    """
    if not should_auto_pull(account_id, source_type):
        return {
            'triggered': False,
            'reason': 'Already has recent data or auto-pull disabled'
        }

    trigger_historical_pull_after_connection(
        account_id=account_id,
        source_type=source_type,
        months=months,
        run_async=True
    )

    return {
        'triggered': True,
        'message': f'Historical data pull started in background for {source_type}',
        'months': months
    }
