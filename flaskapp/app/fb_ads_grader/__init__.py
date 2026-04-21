# app/fb_ads_grader/__init__.py
"""
Facebook Ads Performance Grader Blueprint

Free tool for all users to analyze Facebook Ads account performance.
Provides comprehensive scoring across 12+ dimensions and generates
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
from app.models_fb_ads_grader import FacebookAdsGraderReport
from app.fb_ads_grader.oauth_helper import FacebookAdsOAuthHelper
from app.fb_ads_grader.facebook_ads_client import FacebookAdsGraderClient
from app.fb_ads_grader.analyzer import FacebookAdsAnalyzer
from app.fb_ads_grader.pdf_generator import generate_report_pdf, generate_report_filename

logger = logging.getLogger(__name__)

fb_ads_grader_bp = Blueprint(
    "fb_ads_grader_bp",
    __name__,
    url_prefix="/ads-grader/facebook",
    template_folder="templates",
)


# ============================================================================
# Landing Page
# ============================================================================
@fb_ads_grader_bp.route("/")
def index():
    """
    Landing page for Facebook Ads Performance Grader.
    Available to all users (logged in or not).
    """
    # If user is logged in, show their recent reports
    recent_reports = []
    if current_user.is_authenticated:
        recent_reports = FacebookAdsGraderReport.get_for_account(
            current_user.account_id, limit=3
        )

    return render_template(
        "fb_ads_grader/index.html",
        recent_reports=recent_reports,
    )


# ============================================================================
# Facebook Connection (OAuth Flow)
# ============================================================================
@fb_ads_grader_bp.route("/connect")
def connect():
    """
    Initiate OAuth flow to connect Facebook Ads account.
    """
    try:
        # Check if OAuth credentials are configured
        if not current_app.config.get("FB_APP_ID"):
            logger.warning("Facebook Ads OAuth not configured - using demo mode")
            flash("Facebook Ads connection not configured. Using demo mode.", "info")
            return redirect(url_for("fb_ads_grader_bp.analyze"))

        # Generate authorization URL
        authorization_url = FacebookAdsOAuthHelper.get_authorization_url()

        # Redirect user to Facebook OAuth consent screen
        return redirect(authorization_url)

    except Exception as e:
        logger.exception(f"Error initiating OAuth flow: {e}")
        flash("Error connecting to Facebook Ads. Please try again or use demo mode.", "error")
        return redirect(url_for("fb_ads_grader_bp.index"))


@fb_ads_grader_bp.route("/connect/callback")
def connect_callback():
    """
    Handle OAuth callback from Facebook.
    """
    try:
        # Get authorization code and state
        code = request.args.get("code")
        state = request.args.get("state")

        if not code:
            error = request.args.get("error")
            error_description = request.args.get("error_description", "Unknown error")
            logger.error(f"OAuth error: {error} - {error_description}")
            flash(f"Failed to authorize Facebook Ads access: {error_description}", "error")
            return redirect(url_for("fb_ads_grader_bp.index"))

        # Exchange code for tokens
        tokens = FacebookAdsOAuthHelper.handle_callback(code, state)

        if not tokens:
            flash("Failed to authorize Facebook Ads access. Please try again.", "error")
            return redirect(url_for("fb_ads_grader_bp.index"))

        # Get access token
        access_token = tokens['access_token']

        # Exchange for long-lived token
        long_lived_token = FacebookAdsOAuthHelper.exchange_for_long_lived_token(access_token)
        if long_lived_token:
            access_token = long_lived_token

        # Store token in session
        session['fb_ads_access_token'] = access_token

        # Get available ad accounts
        ad_accounts = FacebookAdsOAuthHelper.get_ad_accounts(access_token)

        if not ad_accounts:
            flash("No Facebook Ads accounts found. Please ensure you have access to at least one active ad account.", "warning")
            return redirect(url_for("fb_ads_grader_bp.index"))

        # Store ad accounts in session for selection
        session['fb_ads_accounts'] = ad_accounts

        # If only one account, auto-select it and go to analysis
        if len(ad_accounts) == 1:
            session['selected_fb_ad_account_id'] = ad_accounts[0]['id']
            flash(f"Connected to Facebook Ads account: {ad_accounts[0]['name']}", "success")
            return redirect(url_for("fb_ads_grader_bp.analyze"))

        # Multiple accounts - show selection page
        flash(f"Connected successfully! Select which ad account to analyze.", "success")
        return redirect(url_for("fb_ads_grader_bp.select_account"))

    except Exception as e:
        logger.exception(f"Error in OAuth callback: {e}")
        flash("Error connecting to Facebook Ads. Please try again.", "error")
        return redirect(url_for("fb_ads_grader_bp.index"))


# ============================================================================
# Analysis Execution
# ============================================================================
@fb_ads_grader_bp.route("/analyze", methods=["GET", "POST"])
def analyze():
    """
    Run Facebook Ads analysis and generate report.
    """
    if request.method == "GET":
        # Check if we have ad account selection
        ad_accounts = session.get('fb_ads_accounts', [])
        selected_account = session.get('selected_fb_ad_account_id')

        return render_template(
            "fb_ads_grader/analyze.html",
            ad_accounts=ad_accounts,
            selected_account=selected_account
        )

    # POST: Run analysis
    try:
        # Get ad account ID from form or session
        ad_account_id = request.form.get("ad_account_id") or session.get('selected_fb_ad_account_id')

        if not ad_account_id:
            flash("Please connect a Facebook Ads account first.", "error")
            return redirect(url_for("fb_ads_grader_bp.connect"))

        # Get access token from session
        access_token = session.get('fb_ads_access_token')

        # If no token, check if demo mode is requested
        use_demo = request.form.get("use_demo", "false") == "true"

        if not access_token and not use_demo:
            flash("Session expired. Please reconnect your Facebook Ads account.", "warning")
            return redirect(url_for("fb_ads_grader_bp.connect"))

        # Create report
        if use_demo or not access_token:
            # Demo mode - use mock data
            report = _create_demo_report(ad_account_id)
        else:
            # Real mode - fetch data from Facebook Ads API
            report = _create_real_report(ad_account_id, access_token)

        flash(f"Analysis complete! Your Facebook Ads Performance Score: {report.overall_score:.0f}/100", "success")
        return redirect(url_for("fb_ads_grader_bp.report", report_id=report.id))

    except Exception as e:
        logger.exception(f"Error running analysis: {e}")
        flash(f"Error analyzing account: {str(e)}", "error")
        return redirect(url_for("fb_ads_grader_bp.index"))


# ============================================================================
# Report Viewing
# ============================================================================
@fb_ads_grader_bp.route("/report/<int:report_id>")
def report(report_id):
    """
    Display full Facebook Ads grader report.
    Shows overall score, section scores, charts, and recommendations.
    """
    report = FacebookAdsGraderReport.query.get_or_404(report_id)

    # Check access: report owner or admin only
    if current_user.is_authenticated:
        if report.account_id and report.account_id != current_user.account_id:
            if not current_user.is_admin:
                flash("You don't have permission to view this report.", "error")
                return redirect(url_for("fb_ads_grader_bp.index"))
    else:
        # Allow anonymous access if session matches
        session_report_id = session.get("last_fb_grader_report_id")
        if session_report_id != report_id:
            flash("Report not found or access denied.", "error")
            return redirect(url_for("fb_ads_grader_bp.index"))

    return render_template(
        "fb_ads_grader/report.html",
        report=report,
    )


# ============================================================================
# PDF Export
# ============================================================================
@fb_ads_grader_bp.route("/report/<int:report_id>/pdf")
def report_pdf(report_id):
    """
    Generate and download PDF version of report.
    """
    report = FacebookAdsGraderReport.query.get_or_404(report_id)

    # Check access (same logic as report view)
    if current_user.is_authenticated:
        if report.account_id and report.account_id != current_user.account_id:
            if not current_user.is_admin:
                flash("You don't have permission to download this report.", "error")
                return redirect(url_for("fb_ads_grader_bp.index"))
    else:
        session_report_id = session.get("last_fb_grader_report_id")
        if session_report_id != report_id:
            flash("Report not found or access denied.", "error")
            return redirect(url_for("fb_ads_grader_bp.index"))

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
        return redirect(url_for("fb_ads_grader_bp.report", report_id=report_id))


# ============================================================================
# Report History
# ============================================================================
@fb_ads_grader_bp.route("/history")
@login_required
def history():
    """
    View all past reports for the current user's account.
    Shows performance trends over time.
    """
    reports = FacebookAdsGraderReport.get_for_account(
        current_user.account_id, limit=50
    )

    return render_template(
        "fb_ads_grader/history.html",
        reports=reports,
    )


# ============================================================================
# Account Selection
# ============================================================================
@fb_ads_grader_bp.route("/select-account", methods=["GET", "POST"])
def select_account():
    """
    Select which Facebook Ad account to analyze (for users with multiple accounts).
    """
    ad_accounts = session.get('fb_ads_accounts', [])

    if not ad_accounts:
        flash("No Facebook Ads accounts found. Please connect your account.", "error")
        return redirect(url_for("fb_ads_grader_bp.connect"))

    if request.method == "POST":
        selected_id = request.form.get("ad_account_id")
        if selected_id:
            session['selected_fb_ad_account_id'] = selected_id
            flash("Account selected. Ready to analyze!", "success")
            return redirect(url_for("fb_ads_grader_bp.analyze"))

    return render_template(
        "fb_ads_grader/select_account.html",
        ad_accounts=ad_accounts
    )


# ============================================================================
# Helper Functions
# ============================================================================
def _create_real_report(ad_account_id: str, access_token: str) -> FacebookAdsGraderReport:
    """
    Create a report using real Facebook Ads API data.
    """
    try:
        # Initialize API client
        logger.info(f"Fetching Facebook Ads data for account {ad_account_id}")
        api_client = FacebookAdsGraderClient(access_token, ad_account_id)

        # Fetch account metrics (365 days - full year of historical data)
        metrics = api_client.get_account_metrics(days=365)

        # Run analysis
        logger.info("Running analysis on fetched data")
        analyzer = FacebookAdsAnalyzer(metrics)
        analysis_results = analyzer.analyze()

        # Get account info
        account_info = metrics.get("account_info", {})
        account_name = account_info.get("name", f"Account {ad_account_id}")

        # Create report from analysis results
        report = FacebookAdsGraderReport(
            account_id=current_user.account_id if current_user.is_authenticated else None,
            user_id=current_user.id if current_user.is_authenticated else None,
            fb_ad_account_id=ad_account_id,
            fb_ad_account_name=account_name,
            fb_business_id=account_info.get("business_id"),
            fb_business_name=account_info.get("business_name"),
            currency=account_info.get("currency", "USD"),

            # Overall score
            overall_score=analysis_results["overall_score"],
            overall_grade=analysis_results["overall_grade"],

            # Key metrics
            ctr_avg=analysis_results["key_metrics"]["ctr_avg"],
            cpc_avg=analysis_results["key_metrics"]["cpc_avg"],
            cpm_avg=analysis_results["key_metrics"]["cpm_avg"],
            roas_avg=analysis_results["key_metrics"]["roas_avg"],
            conversion_rate_avg=analysis_results["key_metrics"]["conversion_rate_avg"],
            wasted_spend_365d=analysis_results["key_metrics"]["wasted_spend_365d"],
            projected_waste_12m=analysis_results["key_metrics"]["projected_waste_12m"],

            # Account diagnostics
            active_campaigns=analysis_results["account_diagnostics"]["active_campaigns"],
            active_ad_sets=analysis_results["account_diagnostics"]["active_ad_sets"],
            active_ads=analysis_results["account_diagnostics"]["active_ads"],
            total_audiences=analysis_results["account_diagnostics"]["total_audiences"],
            clicks_365d=analysis_results["account_diagnostics"]["clicks_365d"],
            impressions_365d=analysis_results["account_diagnostics"]["impressions_365d"],
            conversions_365d=analysis_results["account_diagnostics"]["conversions_365d"],
            spend_365d=analysis_results["account_diagnostics"]["spend_365d"],
            revenue_365d=analysis_results["account_diagnostics"]["revenue_365d"],
            avg_monthly_spend=analysis_results["account_diagnostics"]["avg_monthly_spend"],

            # Section scores
            wasted_spend_score=analysis_results["section_scores"]["wasted_spend"],
            creative_optimization_score=analysis_results["section_scores"]["creative_optimization"],
            audience_targeting_score=analysis_results["section_scores"]["audience_targeting"],
            relevance_score_optimization_score=analysis_results["section_scores"]["relevance_score"],
            ctr_optimization_score=analysis_results["section_scores"]["ctr_optimization"],
            account_activity_score=analysis_results["section_scores"]["account_activity"],
            ad_format_diversity_score=analysis_results["section_scores"]["ad_format_diversity"],
            campaign_structure_score=analysis_results["section_scores"]["campaign_structure"],
            landing_page_score=analysis_results["section_scores"]["landing_page"],
            mobile_optimization_score=analysis_results["section_scores"]["mobile_optimization"],
            conversion_tracking_score=analysis_results["section_scores"]["conversion_tracking"],
            roas_score=analysis_results["section_scores"]["roas"],

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
            session["last_fb_grader_report_id"] = report.id

        return report

    except Exception as e:
        logger.exception(f"Error creating real report: {e}")
        # Fallback to demo report if API fails
        flash("Unable to fetch live data. Showing demo report instead.", "warning")
        return _create_demo_report(ad_account_id)



def _create_demo_report(ad_account_id: str) -> FacebookAdsGraderReport:
    """
    Create a demo report with mock data for testing.
    """
    import random

    # Generate realistic mock scores
    overall_score = random.uniform(45, 88)

    report = FacebookAdsGraderReport(
        account_id=current_user.account_id if current_user.is_authenticated else None,
        user_id=current_user.id if current_user.is_authenticated else None,
        fb_ad_account_id=ad_account_id,
        fb_ad_account_name="Demo Ad Account",
        currency="USD",

        # Overall score
        overall_score=overall_score,
        overall_grade=_calculate_grade(overall_score),

        # Key metrics
        ctr_avg=random.uniform(0.8, 2.5),
        cpc_avg=random.uniform(0.35, 2.50),
        cpm_avg=random.uniform(5, 25),
        roas_avg=random.uniform(1.5, 4.5),
        conversion_rate_avg=random.uniform(2, 12),
        wasted_spend_365d=random.uniform(500, 5000),
        projected_waste_12m=random.uniform(600, 6000),

        # Account diagnostics
        active_campaigns=random.randint(3, 12),
        active_ad_sets=random.randint(10, 40),
        active_ads=random.randint(25, 100),
        total_audiences=random.randint(5, 25),
        clicks_365d=random.randint(1000, 10000),
        impressions_365d=random.randint(100000, 1000000),
        conversions_365d=random.randint(50, 500),
        spend_365d=random.uniform(5000, 50000),
        revenue_365d=random.uniform(10000, 150000),
        avg_monthly_spend=random.uniform(500, 5000),

        # Section scores
        wasted_spend_score=random.uniform(20, 85),
        creative_optimization_score=random.uniform(40, 90),
        audience_targeting_score=random.uniform(30, 85),
        relevance_score_optimization_score=random.uniform(35, 90),
        ctr_optimization_score=random.uniform(25, 85),
        account_activity_score=random.uniform(45, 95),
        ad_format_diversity_score=random.uniform(30, 80),
        campaign_structure_score=random.uniform(40, 90),
        landing_page_score=random.uniform(35, 85),
        mobile_optimization_score=random.uniform(50, 95),
        conversion_tracking_score=random.uniform(40, 95),
        roas_score=random.uniform(35, 90),

        # Detailed data (simplified for demo)
        detailed_metrics={
            "demo": True,
            "note": "This is demo data for testing purposes"
        },

        best_practices={
            "conversion_tracking": random.choice([True, False]),
            "pixel_installed": random.choice([True, False]),
            "multiple_ad_creatives": random.choice([True, False]),
            "audience_testing": random.choice([True, False]),
            "placement_optimization": random.choice([True, False]),
            "mobile_optimized": random.choice([True, False]),
            "ad_rotation": random.choice([True, False]),
            "retargeting_campaigns": random.choice([True, False]),
            "lookalike_audiences": random.choice([True, False]),
            "dynamic_ads": random.choice([True, False]),
        },

        recommendations=[
            "Install Facebook Pixel to track 50% more conversions",
            "Test 3-5 new ad creatives with video content to improve CTR",
            "Create lookalike audiences to reduce CPA by 25-30%",
            "Optimize landing pages for mobile to improve conversion rate",
            "Test carousel ads and collection ads for better engagement",
        ],

        # Metadata
        report_date=datetime.utcnow(),
        date_range_start=datetime.utcnow() - timedelta(days=365),
        date_range_end=datetime.utcnow(),
    )

    db.session.add(report)
    db.session.commit()

    # Store in session for anonymous users
    if not current_user.is_authenticated:
        session["last_fb_grader_report_id"] = report.id

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
