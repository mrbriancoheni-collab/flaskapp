# app/services/baseline_import.py
"""
Service for importing baseline (historical) performance data.
This allows capturing performance BEFORE using FieldSprout for YoY comparison.
"""

from __future__ import annotations
import datetime as dt
import json
from typing import Dict, List, Optional, Any
from dateutil.relativedelta import relativedelta

from app.services.metrics_service import save_metrics, save_metrics_batch


def import_baseline_from_csv(
    account_id: int,
    source_type: str,
    csv_file_path: str,
    source_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Import baseline metrics from CSV file.

    CSV format should have columns:
    date, impressions, clicks, spend, conversions, [other metrics...]

    Args:
        account_id: Account ID
        source_type: Source type identifier
        csv_file_path: Path to CSV file
        source_id: Optional source ID

    Returns:
        Dictionary with import stats
    """
    import csv

    imported = 0
    errors = []

    try:
        with open(csv_file_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)

            for row in reader:
                try:
                    # Parse date
                    date_str = row.get('date', '')
                    date = dt.datetime.strptime(date_str, '%Y-%m-%d').date()

                    # Build metrics dict from row
                    metrics = {}
                    for key, value in row.items():
                        if key == 'date':
                            continue
                        # Try to convert to number
                        try:
                            if '.' in value:
                                metrics[key] = float(value)
                            else:
                                metrics[key] = int(value)
                        except (ValueError, AttributeError):
                            metrics[key] = value

                    # Save to database
                    save_metrics(
                        account_id=account_id,
                        source_type=source_type,
                        date=date,
                        metrics=metrics,
                        source_id=source_id,
                        timeframe='daily'
                    )

                    imported += 1

                except Exception as e:
                    errors.append(f"Row {imported + len(errors) + 2}: {str(e)}")

    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'imported': 0
        }

    return {
        'success': True,
        'imported': imported,
        'errors': errors if errors else None
    }


def import_google_ads_historical(
    account_id: int,
    customer_id: str,
    start_date: dt.date,
    end_date: dt.date,
    google_ads_client
) -> Dict[str, Any]:
    """
    Import historical Google Ads data from Google Ads API.
    This fetches past data to establish a baseline.

    Args:
        account_id: Account ID
        customer_id: Google Ads customer ID
        start_date: Start date for import
        end_date: End date for import
        google_ads_client: Initialized Google Ads API client

    Returns:
        Dictionary with import stats
    """
    try:
        ga_service = google_ads_client.get_service("GoogleAdsService")

        # Query for campaign-level daily metrics
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
            ORDER BY segments.date
        """

        response = ga_service.search_stream(customer_id=customer_id, query=query)

        metrics_list = []
        for batch in response:
            for row in batch.results:
                date_str = row.segments.date
                date = dt.datetime.strptime(date_str, '%Y-%m-%d').date()

                metrics = {
                    'impressions': row.metrics.impressions,
                    'clicks': row.metrics.clicks,
                    'cost': row.metrics.cost_micros / 1_000_000,
                    'conversions': row.metrics.conversions,
                    'conversion_value': row.metrics.conversions_value
                }

                metrics_list.append({
                    'date': date,
                    'metrics': metrics,
                    'entity_type': 'campaign',
                    'entity_id': str(row.campaign.id),
                    'entity_name': row.campaign.name
                })

        # Batch save
        imported = save_metrics_batch(
            account_id=account_id,
            source_type='google_ads',
            metrics_list=metrics_list,
            source_id=customer_id
        )

        return {
            'success': True,
            'imported': imported,
            'source': 'google_ads',
            'period': f"{start_date} to {end_date}"
        }

    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'source': 'google_ads'
        }


def import_facebook_ads_historical(
    account_id: int,
    page_id: str,
    start_date: dt.date,
    end_date: dt.date,
    access_token: str
) -> Dict[str, Any]:
    """
    Import historical Facebook Ads data from Facebook Graph API.

    Args:
        account_id: Account ID
        page_id: Facebook page/ad account ID
        start_date: Start date for import
        end_date: End date for import
        access_token: Facebook access token

    Returns:
        Dictionary with import stats
    """
    try:
        import requests

        # Facebook Graph API endpoint for insights
        url = f"https://graph.facebook.com/v18.0/{page_id}/insights"

        params = {
            'access_token': access_token,
            'metric': 'page_impressions,page_engaged_users,page_views_total',
            'period': 'day',
            'since': start_date.strftime('%Y-%m-%d'),
            'until': end_date.strftime('%Y-%m-%d')
        }

        response = requests.get(url, params=params)
        response.raise_for_status()

        data = response.json()

        metrics_list = []
        # Process response and convert to metrics format
        # (This is a simplified example - actual implementation depends on API response format)

        for item in data.get('data', []):
            # Parse Facebook's response format
            date_str = item.get('end_time', '').split('T')[0]
            if not date_str:
                continue

            date = dt.datetime.strptime(date_str, '%Y-%m-%d').date()

            metrics = {
                'impressions': item.get('value', 0),
                # Add other metrics based on API response
            }

            metrics_list.append({
                'date': date,
                'metrics': metrics
            })

        imported = save_metrics_batch(
            account_id=account_id,
            source_type='fbads',
            metrics_list=metrics_list,
            source_id=page_id
        )

        return {
            'success': True,
            'imported': imported,
            'source': 'fbads',
            'period': f"{start_date} to {end_date}"
        }

    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'source': 'fbads'
        }


def import_manual_baseline(
    account_id: int,
    source_type: str,
    monthly_data: List[Dict[str, Any]],
    source_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Import baseline data from manual entry (e.g., from spreadsheet).
    Useful when you have monthly aggregates but not daily data.

    Args:
        account_id: Account ID
        source_type: Source type identifier
        monthly_data: List of monthly metric dictionaries:
            [
                {
                    'year': 2024,
                    'month': 1,
                    'impressions': 50000,
                    'clicks': 2500,
                    'spend': 1250.00,
                    'conversions': 125
                },
                ...
            ]
        source_id: Optional source ID

    Returns:
        Dictionary with import stats
    """
    imported = 0
    errors = []

    for monthly in monthly_data:
        try:
            year = monthly['year']
            month = monthly['month']

            # Create a date for the first day of the month
            date = dt.date(year, month, 1)

            # Extract metrics (exclude year/month keys)
            metrics = {k: v for k, v in monthly.items() if k not in ['year', 'month']}

            # Save as monthly aggregate
            save_metrics(
                account_id=account_id,
                source_type=source_type,
                date=date,
                metrics=metrics,
                source_id=source_id,
                timeframe='monthly'
            )

            imported += 1

        except Exception as e:
            errors.append(f"Year {year} Month {month}: {str(e)}")

    return {
        'success': len(errors) == 0,
        'imported': imported,
        'errors': errors if errors else None
    }


def generate_baseline_template() -> str:
    """
    Generate a CSV template for baseline data import.

    Returns:
        CSV string with header row and example data
    """
    template = """date,impressions,clicks,spend,conversions
2024-01-01,10000,500,250.50,25
2024-01-02,12000,600,300.00,30
2024-01-03,11000,550,275.25,28
# Add your historical data below
# Date format: YYYY-MM-DD
# Spend in dollars (not cents or micros)
# Add any additional metric columns as needed
"""
    return template


def get_baseline_import_instructions() -> Dict[str, Any]:
    """
    Get instructions for importing baseline data.

    Returns:
        Dictionary with step-by-step instructions
    """
    return {
        'overview': 'Import historical performance data from before using FieldSprout to enable YoY comparison',
        'methods': [
            {
                'name': 'CSV Import',
                'description': 'Import from exported CSV files',
                'steps': [
                    '1. Export historical data from Google Ads, Facebook Ads, etc.',
                    '2. Format as CSV with columns: date, impressions, clicks, spend, conversions',
                    '3. Use import_baseline_from_csv() function',
                    '4. Verify import with SQL query'
                ]
            },
            {
                'name': 'API Import',
                'description': 'Fetch historical data directly from APIs',
                'steps': [
                    '1. Use import_google_ads_historical() for Google Ads',
                    '2. Use import_facebook_ads_historical() for Facebook Ads',
                    '3. Specify date range (e.g., last 12 months)',
                    '4. Data is automatically saved to performance_metrics table'
                ]
            },
            {
                'name': 'Manual Import',
                'description': 'Enter monthly aggregates from spreadsheets',
                'steps': [
                    '1. Prepare monthly data as list of dictionaries',
                    '2. Use import_manual_baseline() function',
                    '3. Data is stored as monthly aggregates',
                    '4. Suitable when daily data is not available'
                ]
            }
        ],
        'example_csv_format': generate_baseline_template(),
        'recommended_period': '12 months of historical data for meaningful YoY comparison'
    }
