# app/ads_grader/__init__.py
"""
Google Ads Quality Checker / Grader Blueprint

Free tool for all users to analyze Google Ads account performance.
Provides comprehensive scoring across 10+ dimensions and generates
branded PDF reports.
"""
from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    jsonify,
    session,
    current_app,
    send_file,
)
from flask_login import current_user, login_required
from datetime import datetime, timedelta
import logging

from app import db
from app.models import Account, User
from app.models_ads_grader import GoogleAdsGraderReport
from app.ads_grader.oauth_helper import GoogleAdsOAuthHelper
from app.ads_grader.google_ads_client import GoogleAdsGraderClient
from app.ads_grader.analyzer import GoogleAdsAnalyzer
from app.ads_grader.pdf_generator import generate_report_pdf, generate_report_filename

logger = logging.getLogger(__name__)

ads_grader_bp = Blueprint(
    "ads_grader_bp",
    __name__,
    url_prefix="/ads-grader",
    template_folder="templates",
)


# ============================================================================
# Landing Page
# ============================================================================
@ads_grader_bp.route("/")
def index():
    """
    Landing page for Google Ads Quality Checker.
    Available to all users (logged in or not).
    """
    # If user is logged in, show their recent reports
    recent_reports = []
    if current_user.is_authenticated:
        recent_reports = GoogleAdsGraderReport.get_for_account(
            current_user.account_id, limit=3
        )

    return render_template(
        "ads_grader/index.html",
        recent_reports=recent_reports,
    )


# ============================================================================
# Google Ads Connection (OAuth Flow)
# ============================================================================
@ads_grader_bp.route("/connect")
def connect():
    """
    Initiate OAuth flow to connect Google Ads account.
    """
    try:
        import os
        # Check if OAuth credentials are configured (check env vars first, then config)
        client_id = os.getenv("GOOGLE_ADS_CLIENT_ID") or current_app.config.get("GOOGLE_ADS_CLIENT_ID")
        if not client_id:
            logger.warning("Google Ads OAuth not configured - using demo mode")
            flash("Google Ads connection not configured. Using demo mode.", "info")
            return redirect(url_for("ads_grader_bp.analyze"))

        # Generate authorization URL
        authorization_url = GoogleAdsOAuthHelper.get_authorization_url()

        # Redirect user to Google OAuth consent screen
        return redirect(authorization_url)

    except Exception as e:
        logger.exception(f"Error initiating OAuth flow: {e}")
        flash("Error connecting to Google Ads. Please try again or use demo mode.", "error")
        return redirect(url_for("ads_grader_bp.index"))


@ads_grader_bp.route("/connect/callback")
def connect_callback():
    """
    Handle OAuth callback from Google.
    """
    try:
        # Get authorization response (full URL)
        authorization_response = request.url
        state = request.args.get("state")

        # Exchange code for tokens
        tokens = GoogleAdsOAuthHelper.handle_callback(authorization_response, state)

        if not tokens:
            flash("Failed to authorize Google Ads access. Please try again.", "error")
            return redirect(url_for("ads_grader_bp.index"))

        # Store tokens in session (for single-use grading)
        # In production, you might want to store these in the database for recurring analysis
        session['google_ads_tokens'] = tokens

        # Get available customer IDs
        customer_ids = GoogleAdsOAuthHelper.get_customer_ids(tokens['refresh_token'])

        if not customer_ids:
            flash("No Google Ads accounts found. Please ensure you have access to at least one account.", "warning")
            return redirect(url_for("ads_grader_bp.index"))

        # Store customer IDs in session for selection
        session['google_ads_customers'] = customer_ids

        # If only one account, auto-select it and go to analysis
        if len(customer_ids) == 1:
            session['selected_customer_id'] = customer_ids[0]['customer_id']
            flash(f"Connected to Google Ads account: {customer_ids[0]['name']}", "success")
            return redirect(url_for("ads_grader_bp.analyze"))

        # Multiple accounts - show selection page
        flash(f"Connected successfully! Select which account to analyze.", "success")
        return redirect(url_for("ads_grader_bp.select_account"))

    except Exception as e:
        logger.exception(f"Error in OAuth callback: {e}")
        flash("Error connecting to Google Ads. Please try again.", "error")
        return redirect(url_for("ads_grader_bp.index"))


# ============================================================================
# Analysis Execution
# ============================================================================
@ads_grader_bp.route("/analyze", methods=["GET", "POST"])
def analyze():
    """
    Run Google Ads analysis and generate report.
    """
    if request.method == "GET":
        # Check if we have customer selection
        customers = session.get('google_ads_customers', [])
        selected_customer = session.get('selected_customer_id')

        return render_template(
            "ads_grader/analyze.html",
            customers=customers,
            selected_customer=selected_customer
        )

    # POST: Run analysis
    try:
        # Get customer ID from form or session
        customer_id = request.form.get("customer_id") or session.get('selected_customer_id')

        if not customer_id:
            flash("Please connect a Google Ads account first.", "error")
            return redirect(url_for("ads_grader_bp.connect"))

        # Get tokens from session
        tokens = session.get('google_ads_tokens')

        # If no tokens, check if demo mode is requested
        use_demo = request.form.get("use_demo", "false") == "true"

        if not tokens and not use_demo:
            flash("Session expired. Please reconnect your Google Ads account.", "warning")
            return redirect(url_for("ads_grader_bp.connect"))

        # Create report
        if use_demo or not tokens:
            # Demo mode - use mock data
            report = _create_demo_report(customer_id)
        else:
            # Real mode - fetch data from Google Ads API
            report = _create_real_report(customer_id, tokens['refresh_token'])

        flash(f"Analysis complete! Your Google Ads Performance Score: {report.overall_score:.0f}/100", "success")
        return redirect(url_for("ads_grader_bp.report", report_id=report.id))

    except Exception as e:
        logger.exception(f"Error running analysis: {e}")
        flash(f"Error analyzing account: {str(e)}", "error")
        return redirect(url_for("ads_grader_bp.index"))


# ============================================================================
# Report Viewing
# ============================================================================
@ads_grader_bp.route("/report/<int:report_id>")
def report(report_id):
    """
    Display full Google Ads grader report.
    Shows overall score, section scores, charts, and recommendations.
    """
    report = GoogleAdsGraderReport.query.get_or_404(report_id)

    # Check access: report owner or admin only
    if current_user.is_authenticated:
        if report.account_id and report.account_id != current_user.account_id:
            if not current_user.is_admin:
                flash("You don't have permission to view this report.", "error")
                return redirect(url_for("ads_grader_bp.index"))
    else:
        # Allow anonymous access if session matches
        session_report_id = session.get("last_grader_report_id")
        if session_report_id != report_id:
            flash("Report not found or access denied.", "error")
            return redirect(url_for("ads_grader_bp.index"))

    return render_template(
        "ads_grader/report.html",
        report=report,
    )


# ============================================================================
# PDF Export
# ============================================================================
@ads_grader_bp.route("/report/<int:report_id>/pdf")
def report_pdf(report_id):
    """
    Generate and download PDF version of report.
    """
    report = GoogleAdsGraderReport.query.get_or_404(report_id)

    # Check access (same logic as report view)
    if current_user.is_authenticated:
        if report.account_id and report.account_id != current_user.account_id:
            if not current_user.is_admin:
                flash("You don't have permission to download this report.", "error")
                return redirect(url_for("ads_grader_bp.index"))
    else:
        session_report_id = session.get("last_grader_report_id")
        if session_report_id != report_id:
            flash("Report not found or access denied.", "error")
            return redirect(url_for("ads_grader_bp.index"))

    try:
        # Generate PDF
        pdf_file = generate_report_pdf(report)

        # Track download
        report.pdf_download_count += 1
        db.session.commit()

        # Generate filename
        filename = generate_report_filename(report)

        # Return PDF file
        return send_file(
            pdf_file,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=filename
        )

    except Exception as e:
        logger.exception(f"Error generating PDF for report {report_id}: {e}")
        flash(f"Error generating PDF: {str(e)}", "error")
        return redirect(url_for("ads_grader_bp.report", report_id=report_id))


# ============================================================================
# Report History
# ============================================================================
@ads_grader_bp.route("/history")
@login_required
def history():
    """
    View all past reports for the current user's account.
    Shows performance trends over time.
    """
    reports = GoogleAdsGraderReport.get_for_account(
        current_user.account_id, limit=50
    )

    return render_template(
        "ads_grader/history.html",
        reports=reports,
    )


# ============================================================================
# Account Selection
# ============================================================================
@ads_grader_bp.route("/select-account", methods=["GET", "POST"])
def select_account():
    """
    Select which Google Ads account to analyze (for users with multiple accounts).
    """
    customers = session.get('google_ads_customers', [])

    if not customers:
        flash("No Google Ads accounts found. Please connect your account.", "error")
        return redirect(url_for("ads_grader_bp.connect"))

    if request.method == "POST":
        selected_id = request.form.get("customer_id")
        if selected_id:
            session['selected_customer_id'] = selected_id
            flash("Account selected. Ready to analyze!", "success")
            return redirect(url_for("ads_grader_bp.analyze"))

    return render_template(
        "ads_grader/select_account.html",
        customers=customers
    )


# ============================================================================
# Helper Functions
# ============================================================================
def _create_real_report(customer_id: str, refresh_token: str) -> GoogleAdsGraderReport:
    """
    Create a report using real Google Ads API data.
    """
    try:
        # Initialize API client
        logger.info(f"Fetching Google Ads data for customer {customer_id}")
        api_client = GoogleAdsGraderClient(refresh_token, customer_id)

        # Fetch account metrics (365 days - full year of historical data)
        metrics = api_client.get_account_metrics(days=365)

        # Run analysis
        logger.info("Running analysis on fetched data")
        analyzer = GoogleAdsAnalyzer(metrics)
        analysis_results = analyzer.analyze()

        # Get account info
        account_info = metrics.get("account_info", {})
        account_name = account_info.get("account_name", f"Account {customer_id}")

        # Create report from analysis results
        report = GoogleAdsGraderReport(
            account_id=current_user.account_id if current_user.is_authenticated else None,
            user_id=current_user.id if current_user.is_authenticated else None,
            google_ads_customer_id=customer_id,
            google_ads_account_name=account_name,

            # Overall score
            overall_score=analysis_results["overall_score"],
            overall_grade=analysis_results["overall_grade"],

            # Key metrics
            quality_score_avg=analysis_results["key_metrics"]["quality_score_avg"],
            ctr_avg=analysis_results["key_metrics"]["ctr_avg"],
            wasted_spend_90d=analysis_results["key_metrics"]["wasted_spend_90d"],
            projected_waste_12m=analysis_results["key_metrics"]["projected_waste_12m"],

            # Account diagnostics
            active_campaigns=analysis_results["account_diagnostics"]["active_campaigns"],
            active_ad_groups=analysis_results["account_diagnostics"]["active_ad_groups"],
            active_text_ads=analysis_results["account_diagnostics"]["active_text_ads"],
            active_keywords=analysis_results["account_diagnostics"]["active_keywords"],
            clicks_90d=analysis_results["account_diagnostics"]["clicks_90d"],
            conversions_90d=analysis_results["account_diagnostics"]["conversions_90d"],
            avg_cpa_90d=analysis_results["account_diagnostics"]["avg_cpa_90d"],
            avg_monthly_spend=analysis_results["account_diagnostics"]["avg_monthly_spend"],

            # Section scores
            wasted_spend_score=analysis_results["section_scores"]["wasted_spend"],
            expanded_text_ads_score=analysis_results["section_scores"]["expanded_text_ads"],
            text_ad_optimization_score=analysis_results["section_scores"]["text_ad_optimization"],
            quality_score_optimization_score=analysis_results["section_scores"]["quality_score"],
            ctr_optimization_score=analysis_results["section_scores"]["ctr_optimization"],
            account_activity_score=analysis_results["section_scores"]["account_activity"],
            long_tail_keywords_score=analysis_results["section_scores"]["long_tail_keywords"],
            impression_share_score=analysis_results["section_scores"]["impression_share"],
            landing_page_score=analysis_results["section_scores"]["landing_pages"],
            mobile_advertising_score=analysis_results["section_scores"]["mobile_advertising"],

            # Detailed data
            detailed_metrics=metrics,

            # Best practices
            best_practices=analysis_results["best_practices"],

            # Recommendations
            recommendations=analysis_results["recommendations"],

            # Metadata
            report_date=datetime.utcnow(),
            date_range_start=datetime.utcnow() - timedelta(days=365),
            date_range_end=datetime.utcnow(),
        )

        db.session.add(report)
        db.session.commit()

        logger.info(f"Report created successfully: ID {report.id}, Score {report.overall_score}")

        # Store in session for anonymous users
        if not current_user.is_authenticated:
            session["last_grader_report_id"] = report.id

        return report

    except Exception as e:
        logger.exception(f"Error creating real report: {e}")
        # Fallback to demo report if API fails
        flash("Unable to fetch live data. Showing demo report instead.", "warning")
        return _create_demo_report(customer_id)



def _create_demo_report(customer_id: str) -> GoogleAdsGraderReport:
    """
    Create a demo report with mock data for testing.
    TODO: Remove this once real Google Ads API integration is complete.
    """
    import random

    # Generate realistic mock scores
    overall_score = random.uniform(40, 85)

    report = GoogleAdsGraderReport(
        account_id=current_user.account_id if current_user.is_authenticated else None,
        user_id=current_user.id if current_user.is_authenticated else None,
        google_ads_customer_id=customer_id,
        google_ads_account_name="Demo Account",

        # Overall score
        overall_score=overall_score,
        overall_grade=_calculate_grade(overall_score),

        # Key metrics
        quality_score_avg=random.uniform(4.5, 8.5),
        ctr_avg=random.uniform(1.2, 5.8),
        wasted_spend_90d=random.uniform(200, 2500),
        projected_waste_12m=random.uniform(800, 10000),

        # Account diagnostics
        active_campaigns=random.randint(3, 15),
        active_ad_groups=random.randint(10, 50),
        active_text_ads=random.randint(20, 150),
        active_keywords=random.randint(100, 1000),
        clicks_90d=random.randint(500, 5000),
        conversions_90d=random.randint(20, 200),
        avg_cpa_90d=random.uniform(15, 150),
        avg_monthly_spend=random.uniform(1000, 15000),

        # Section scores
        wasted_spend_score=random.uniform(10, 90),
        expanded_text_ads_score=random.uniform(50, 100),
        text_ad_optimization_score=random.uniform(30, 90),
        quality_score_optimization_score=random.uniform(10, 80),
        ctr_optimization_score=random.uniform(20, 85),
        account_activity_score=random.uniform(40, 95),
        long_tail_keywords_score=random.uniform(25, 75),
        impression_share_score=random.uniform(15, 70),
        landing_page_score=random.uniform(50, 100),
        mobile_advertising_score=random.uniform(30, 90),

        # Detailed data (simplified for demo)
        detailed_metrics={
            "quality_score_distribution": {
                "1-3": 15,
                "4-6": 35,
                "7-8": 30,
                "9-10": 20,
            },
            "ctr_by_device": {
                "mobile": 2.8,
                "desktop": 3.2,
                "tablet": 2.1,
            },
        },

        best_practices={
            "mobile_bid_adjustments": random.choice([True, False]),
            "multiple_ads_per_group": random.choice([True, False]),
            "modified_broad_match": random.choice([True, False]),
            "ad_extensions": random.choice([True, False]),
            "conversion_tracking": random.choice([True, False]),
            "negative_keywords": random.choice([True, False]),
        },

        recommendations=[
            "Add 128 negative keywords to reduce wasted spend by $739/month",
            "Improve Quality Score from 5.2 to 7.0+ to reduce CPC by 30%",
            "Test 3 new ad variations in your top-performing ad groups",
            "Increase mobile bids by 15% based on strong mobile performance",
            "Add sitelink and callout extensions to improve CTR",
        ],

        # Metadata
        report_date=datetime.utcnow(),
        date_range_start=datetime.utcnow() - timedelta(days=90),
        date_range_end=datetime.utcnow(),
    )

    db.session.add(report)
    db.session.commit()

    # Store in session for anonymous users
    if not current_user.is_authenticated:
        session["last_grader_report_id"] = report.id

    return report


def _calculate_grade(score: float) -> str:
    """Convert numerical score to letter grade."""
    if score >= 90: return "A+"
    elif score >= 85: return "A"
    elif score >= 80: return "A-"
    elif score >= 75: return "B+"
    elif score >= 70: return "B"
    elif score >= 65: return "B-"
    elif score >= 60: return "C+"
    elif score >= 55: return "C"
    elif score >= 50: return "C-"
    elif score >= 45: return "D+"
    elif score >= 40: return "D"
    else: return "F"
