# app/services/historical_data_pull.py
"""
Automated historical data pull service.
Pulls last 12 months of performance data from all connected APIs and stores in performance_metrics.
"""

from __future__ import annotations
import datetime as dt
from typing import Dict, List, Optional, Any
from dateutil.relativedelta import relativedelta

from flask import current_app
from app import db
from app.services.metrics_service import save_metrics, save_metrics_batch


def pull_all_historical_data(
    account_id: int,
    months: int = 12,
    force: bool = False
) -> Dict[str, Any]:
    """
    Pull historical data from ALL connected channels.

    Args:
        account_id: Account ID
        months: Number of months to pull back (default 12)
        force: If True, re-pull even if data already exists

    Returns:
        Dictionary with results from each channel
    """
    end_date = dt.date.today()
    start_date = end_date - relativedelta(months=months)

    results = {
        'account_id': account_id,
        'period': f"{start_date} to {end_date}",
        'channels': {}
    }

    # Pull from each channel
    channels = [
        ('google_ads', pull_google_ads_historical),
        ('google_analytics', pull_google_analytics_historical),
        ('search_console', pull_search_console_historical),
        ('glsa', pull_glsa_historical),
        ('gmb', pull_gmb_historical),
        ('fbads', pull_facebook_ads_historical),
    ]

    for channel_name, pull_func in channels:
        try:
            current_app.logger.info(f"Pulling {channel_name} historical data for account {account_id}...")
            result = pull_func(account_id, start_date, end_date, force)
            results['channels'][channel_name] = result
        except Exception as e:
            current_app.logger.error(f"Failed to pull {channel_name}: {e}")
            results['channels'][channel_name] = {
                'success': False,
                'error': str(e),
                'imported': 0
            }

    # Calculate totals
    total_imported = sum(
        r.get('imported', 0)
        for r in results['channels'].values()
        if isinstance(r, dict)
    )
    results['total_imported'] = total_imported
    results['success'] = total_imported > 0

    return results


def pull_google_ads_historical(
    account_id: int,
    start_date: dt.date,
    end_date: dt.date,
    force: bool = False
) -> Dict[str, Any]:
    """
    Pull historical Google Ads data using existing API connection.

    Args:
        account_id: Account ID
        start_date: Start date for import
        end_date: End date for import
        force: Re-import even if data exists

    Returns:
        Dictionary with import stats
    """
    try:
        # Get Google Ads auth for this account
        from app.models import GoogleAdsAuth
        auth = GoogleAdsAuth.query.filter_by(account_id=account_id).first()

        if not auth or not auth.refresh_token:
            return {
                'success': False,
                'error': 'Google Ads not connected',
                'imported': 0
            }

        # Build Google Ads client
        from app.services.google_ads_service import client_from_refresh
        from app.services.crypto import decrypt

        refresh_token = decrypt(auth.refresh_token)
        client = client_from_refresh(refresh_token, auth.manager_customer_id)
        customer_id = auth.customer_id.replace('-', '')

        # Fetch daily campaign performance
        ga_service = client.get_service("GoogleAdsService")

        query = f"""
            SELECT
                campaign.id,
                campaign.name,
                segments.date,
                metrics.impressions,
                metrics.clicks,
                metrics.cost_micros,
                metrics.conversions,
                metrics.conversions_value
            FROM campaign
            WHERE segments.date BETWEEN '{start_date.strftime('%Y-%m-%d')}'
              AND '{end_date.strftime('%Y-%m-%d')}'
              AND campaign.status != 'REMOVED'
            ORDER BY segments.date
        """

        response = ga_service.search_stream(customer_id=customer_id, query=query)

        # Group by date for daily aggregates
        daily_metrics = {}

        for batch in response:
            for row in batch.results:
                date_str = row.segments.date
                date = dt.datetime.strptime(date_str, '%Y-%m-%d').date()

                if date not in daily_metrics:
                    daily_metrics[date] = {
                        'impressions': 0,
                        'clicks': 0,
                        'cost': 0.0,
                        'conversions': 0.0,
                        'conversion_value': 0.0
                    }

                daily_metrics[date]['impressions'] += row.metrics.impressions
                daily_metrics[date]['clicks'] += row.metrics.clicks
                daily_metrics[date]['cost'] += row.metrics.cost_micros / 1_000_000
                daily_metrics[date]['conversions'] += row.metrics.conversions
                daily_metrics[date]['conversion_value'] += row.metrics.conversions_value

        # Save to database
        imported = 0
        for date, metrics in daily_metrics.items():
            # Check if already exists (unless force=True)
            if not force:
                existing = db.session.query(
                    db.func.count()
                ).select_from(
                    db.text('performance_metrics')
                ).filter(
                    db.text('account_id = :aid AND source_type = :st AND date = :d')
                ).params(
                    aid=account_id,
                    st='google_ads',
                    d=date
                ).scalar()

                if existing > 0:
                    continue

            save_metrics(
                account_id=account_id,
                source_type='google_ads',
                date=date,
                metrics=metrics,
                source_id=customer_id,
                timeframe='daily'
            )
            imported += 1

        return {
            'success': True,
            'imported': imported,
            'source': 'google_ads',
            'period': f"{start_date} to {end_date}"
        }

    except Exception as e:
        current_app.logger.exception(f"Error pulling Google Ads historical data: {e}")
        return {
            'success': False,
            'error': str(e),
            'source': 'google_ads',
            'imported': 0
        }


def pull_facebook_ads_historical(
    account_id: int,
    start_date: dt.date,
    end_date: dt.date,
    force: bool = False
) -> Dict[str, Any]:
    """
    Pull historical Facebook Ads data using existing API connection.
    """
    try:
        import requests

        # Get Facebook token for this account
        result = db.engine.execute(
            db.text(
                "SELECT access_token FROM facebook_tokens WHERE account_id = :aid"
            ),
            {"aid": account_id}
        ).fetchone()

        if not result:
            return {
                'success': False,
                'error': 'Facebook Ads not connected',
                'imported': 0
            }

        access_token = result[0]

        # Get account's ad account ID
        me_url = f"https://graph.facebook.com/v20.0/me/adaccounts"
        me_response = requests.get(me_url, params={'access_token': access_token})
        me_response.raise_for_status()
        ad_accounts = me_response.json().get('data', [])

        if not ad_accounts:
            return {
                'success': False,
                'error': 'No Facebook Ad accounts found',
                'imported': 0
            }

        ad_account_id = ad_accounts[0]['id']

        # Fetch insights with time breakdown
        insights_url = f"https://graph.facebook.com/v20.0/{ad_account_id}/insights"

        params = {
            'access_token': access_token,
            'time_range': json.dumps({
                'since': start_date.strftime('%Y-%m-%d'),
                'until': end_date.strftime('%Y-%m-%d')
            }),
            'time_increment': 1,  # Daily breakdown
            'fields': 'spend,impressions,clicks,reach,actions,action_values,cpc,cpm,ctr',
            'level': 'account'
        }

        response = requests.get(insights_url, params=params)
        response.raise_for_status()
        insights = response.json().get('data', [])

        # Save each day's metrics
        imported = 0
        for day_data in insights:
            date_str = day_data.get('date_start')
            if not date_str:
                continue

            date = dt.datetime.strptime(date_str, '%Y-%m-%d').date()

            # Extract actions (leads, conversions, etc.)
            actions = day_data.get('actions', [])
            leads = sum(
                int(a['value'])
                for a in actions
                if a.get('action_type') in ['lead', 'onsite_conversion.lead_grouped']
            )

            metrics = {
                'spend': float(day_data.get('spend', 0)),
                'impressions': int(day_data.get('impressions', 0)),
                'clicks': int(day_data.get('clicks', 0)),
                'reach': int(day_data.get('reach', 0)),
                'leads': leads,
                'cpc': float(day_data.get('cpc', 0)),
                'cpm': float(day_data.get('cpm', 0)),
                'ctr': float(day_data.get('ctr', 0))
            }

            # Check if already exists
            if not force:
                from app.models_ads import PerformanceMetrics
                existing = PerformanceMetrics.query.filter_by(
                    account_id=account_id,
                    source_type='fbads',
                    date=date
                ).first()

                if existing:
                    continue

            save_metrics(
                account_id=account_id,
                source_type='fbads',
                date=date,
                metrics=metrics,
                source_id=ad_account_id,
                timeframe='daily'
            )
            imported += 1

        return {
            'success': True,
            'imported': imported,
            'source': 'fbads',
            'period': f"{start_date} to {end_date}"
        }

    except Exception as e:
        current_app.logger.exception(f"Error pulling Facebook Ads historical data: {e}")
        return {
            'success': False,
            'error': str(e),
            'source': 'fbads',
            'imported': 0
        }


def pull_google_analytics_historical(
    account_id: int,
    start_date: dt.date,
    end_date: dt.date,
    force: bool = False
) -> Dict[str, Any]:
    """
    Pull historical Google Analytics data.
    """
    try:
        # Get GA auth
        from app.models import GoogleAnalyticsAuth
        auth = GoogleAnalyticsAuth.query.filter_by(account_id=account_id).first()

        if not auth:
            return {
                'success': False,
                'error': 'Google Analytics not connected',
                'imported': 0
            }

        # Use Analytics Data API (GA4) or Reporting API (UA)
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        creds = Credentials(
            token=None,
            refresh_token=auth.refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=current_app.config.get('GOOGLE_CLIENT_ID'),
            client_secret=current_app.config.get('GOOGLE_CLIENT_SECRET')
        )

        # Build Analytics Reporting API client
        analytics = build('analyticsreporting', 'v4', credentials=creds)

        # Fetch daily metrics
        response = analytics.reports().batchGet(
            body={
                'reportRequests': [{
                    'viewId': auth.view_id,
                    'dateRanges': [{
                        'startDate': start_date.strftime('%Y-%m-%d'),
                        'endDate': end_date.strftime('%Y-%m-%d')
                    }],
                    'metrics': [
                        {'expression': 'ga:sessions'},
                        {'expression': 'ga:pageviews'},
                        {'expression': 'ga:bounceRate'},
                        {'expression': 'ga:avgSessionDuration'},
                        {'expression': 'ga:goalCompletionsAll'}
                    ],
                    'dimensions': [{'name': 'ga:date'}]
                }]
            }
        ).execute()

        # Parse and save results
        imported = 0
        for report in response.get('reports', []):
            for row in report.get('data', {}).get('rows', []):
                date_str = row['dimensions'][0]  # Format: YYYYMMDD
                date = dt.datetime.strptime(date_str, '%Y%m%d').date()

                values = row['metrics'][0]['values']
                metrics = {
                    'sessions': int(values[0]),
                    'pageviews': int(values[1]),
                    'bounce_rate': float(values[2]),
                    'avg_session_duration': float(values[3]),
                    'goal_completions': int(values[4])
                }

                if not force:
                    from app.models_ads import PerformanceMetrics
                    existing = PerformanceMetrics.query.filter_by(
                        account_id=account_id,
                        source_type='google_analytics',
                        date=date
                    ).first()

                    if existing:
                        continue

                save_metrics(
                    account_id=account_id,
                    source_type='google_analytics',
                    date=date,
                    metrics=metrics,
                    source_id=auth.property_id,
                    timeframe='daily'
                )
                imported += 1

        return {
            'success': True,
            'imported': imported,
            'source': 'google_analytics'
        }

    except Exception as e:
        current_app.logger.exception(f"Error pulling GA historical data: {e}")
        return {
            'success': False,
            'error': str(e),
            'source': 'google_analytics',
            'imported': 0
        }


def pull_search_console_historical(
    account_id: int,
    start_date: dt.date,
    end_date: dt.date,
    force: bool = False
) -> Dict[str, Any]:
    """
    Pull historical Google Search Console data.
    """
    try:
        # Get GSC connection
        from app.models import GoogleSearchConsoleAuth
        auth = GoogleSearchConsoleAuth.query.filter_by(account_id=account_id).first()

        if not auth:
            return {
                'success': False,
                'error': 'Google Search Console not connected',
                'imported': 0
            }

        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        creds = Credentials(
            token=None,
            refresh_token=auth.refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=current_app.config.get('GOOGLE_CLIENT_ID'),
            client_secret=current_app.config.get('GOOGLE_CLIENT_SECRET')
        )

        webmasters = build('searchconsole', 'v1', credentials=creds)

        # Fetch daily aggregates
        request = {
            'startDate': start_date.strftime('%Y-%m-%d'),
            'endDate': end_date.strftime('%Y-%m-%d'),
            'dimensions': ['date'],
            'rowLimit': 25000
        }

        response = webmasters.searchanalytics().query(
            siteUrl=auth.site_url,
            body=request
        ).execute()

        imported = 0
        for row in response.get('rows', []):
            date_str = row['keys'][0]
            date = dt.datetime.strptime(date_str, '%Y-%m-%d').date()

            metrics = {
                'impressions': int(row.get('impressions', 0)),
                'clicks': int(row.get('clicks', 0)),
                'ctr': float(row.get('ctr', 0)) * 100,  # Convert to percentage
                'position': float(row.get('position', 0))
            }

            if not force:
                from app.models_ads import PerformanceMetrics
                existing = PerformanceMetrics.query.filter_by(
                    account_id=account_id,
                    source_type='search_console',
                    date=date
                ).first()

                if existing:
                    continue

            save_metrics(
                account_id=account_id,
                source_type='search_console',
                date=date,
                metrics=metrics,
                source_id=auth.site_url,
                timeframe='daily'
            )
            imported += 1

        return {
            'success': True,
            'imported': imported,
            'source': 'search_console'
        }

    except Exception as e:
        current_app.logger.exception(f"Error pulling GSC historical data: {e}")
        return {
            'success': False,
            'error': str(e),
            'source': 'search_console',
            'imported': 0
        }


def pull_glsa_historical(
    account_id: int,
    start_date: dt.date,
    end_date: dt.date,
    force: bool = False
) -> Dict[str, Any]:
    """
    Pull historical GLSA data.
    GLSA typically doesn't have a historical API - data comes from leads table.
    """
    try:
        # Group leads by date
        from app.models import CRMContact

        leads_by_date = {}
        leads = CRMContact.query.filter(
            CRMContact.account_id == account_id,
            CRMContact.source == 'glsa',
            CRMContact.created_at >= start_date,
            CRMContact.created_at <= end_date
        ).all()

        for lead in leads:
            date = lead.created_at.date()
            if date not in leads_by_date:
                leads_by_date[date] = 0
            leads_by_date[date] += 1

        imported = 0
        for date, count in leads_by_date.items():
            metrics = {
                'leads': count,
                'phone_calls': count,  # Approximate
                'conversions': count
            }

            if not force:
                from app.models_ads import PerformanceMetrics
                existing = PerformanceMetrics.query.filter_by(
                    account_id=account_id,
                    source_type='glsa',
                    date=date
                ).first()

                if existing:
                    continue

            save_metrics(
                account_id=account_id,
                source_type='glsa',
                date=date,
                metrics=metrics,
                timeframe='daily'
            )
            imported += 1

        return {
            'success': True,
            'imported': imported,
            'source': 'glsa'
        }

    except Exception as e:
        current_app.logger.exception(f"Error pulling GLSA historical data: {e}")
        return {
            'success': False,
            'error': str(e),
            'source': 'glsa',
            'imported': 0
        }


def pull_gmb_historical(
    account_id: int,
    start_date: dt.date,
    end_date: dt.date,
    force: bool = False
) -> Dict[str, Any]:
    """
    Pull historical GMB data.
    Note: GMB Insights API has limitations on historical data (typically 18 months max).
    """
    try:
        # GMB historical data would require Business Profile API
        # Placeholder - implement based on your GMB integration

        return {
            'success': False,
            'error': 'GMB historical pull not yet implemented',
            'imported': 0,
            'source': 'gmb'
        }

    except Exception as e:
        current_app.logger.exception(f"Error pulling GMB historical data: {e}")
        return {
            'success': False,
            'error': str(e),
            'source': 'gmb',
            'imported': 0
        }


def check_existing_data(account_id: int, source_type: str) -> Dict[str, Any]:
    """
    Check what historical data already exists for a source.

    Returns:
        Dictionary with date range and record count
    """
    from app.models_ads import PerformanceMetrics

    query = PerformanceMetrics.query.filter_by(
        account_id=account_id,
        source_type=source_type
    )

    count = query.count()

    if count == 0:
        return {
            'has_data': False,
            'count': 0
        }

    earliest = query.order_by(PerformanceMetrics.date.asc()).first()
    latest = query.order_by(PerformanceMetrics.date.desc()).first()

    return {
        'has_data': True,
        'count': count,
        'earliest_date': earliest.date.isoformat() if earliest else None,
        'latest_date': latest.date.isoformat() if latest else None,
        'date_range_days': (latest.date - earliest.date).days if (earliest and latest) else 0
    }
