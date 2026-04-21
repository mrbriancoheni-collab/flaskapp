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
# NOTE: oauth_helper is deprecated - now uses main Google OAuth integration
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
# ROI Calculator
# ============================================================================
@ads_grader_bp.route("/calculator")
def calculator():
    """
    ROI calculator for Google Ads optimization.
    Helps prospects estimate potential savings and revenue increase.
    Public page - no login required.
    """
    return render_template(
        "ads_grader/calculator.html",
    )


@ads_grader_bp.route("/calculator-demo")
def calculator_demo():
    """
    Demo landing page - choose between self-guided or sales consultation.
    Features founder's story and value proposition.
    Public page - no login required.
    """
    return render_template(
        "ads_grader/calculator_demo.html",
    )


@ads_grader_bp.route("/calculator/self-guided")
def calculator_self_guided():
    """
    Self-guided interactive demo with pre-filled scenarios.
    Shows step-by-step tooltips and example calculations.
    Public page - no login required.
    """
    # Pre-filled demo scenarios
    demo_scenarios = {
        'hvac': {
            'name': 'HVAC Company',
            'monthly_spend': 5000,
            'avg_order_value': 500,
            'wasted_spend_pct': 22,
            'conversion_rate': 4.2,
            'avg_cpc': 8.50,
            'quality_score': 5,
            'avg_position': 3.2,
            'win_rate': 20  # 20% of leads convert to customers
        },
        'plumbing': {
            'name': 'Plumbing Services',
            'monthly_spend': 3000,
            'avg_order_value': 500,
            'wasted_spend_pct': 18,
            'conversion_rate': 3.8,
            'avg_cpc': 5.20,
            'quality_score': 6,
            'avg_position': 2.8,
            'win_rate': 20  # 20% of leads convert to customers
        },
        'electrical': {
            'name': 'Electrical Contractor',
            'monthly_spend': 4000,
            'avg_order_value': 500,
            'wasted_spend_pct': 20,
            'conversion_rate': 3.2,
            'avg_cpc': 6.80,
            'quality_score': 5,
            'avg_position': 3.5,
            'win_rate': 20  # 20% of leads convert to customers
        }
    }

    # Get selected scenario or default to HVAC
    scenario_key = request.args.get('scenario', 'hvac')
    scenario = demo_scenarios.get(scenario_key, demo_scenarios['hvac'])

    return render_template(
        "ads_grader/calculator_self_guided.html",
        scenario=scenario,
        scenarios=demo_scenarios,
        demo_mode=True
    )


@ads_grader_bp.route("/calculator/consultation")
def calculator_consultation():
    """
    Sales consultation flow - capture lead info then show personalized calculator.
    Includes scheduling and contact options.
    Public page - no login required.
    """
    return render_template(
        "ads_grader/calculator_consultation.html",
    )


# ============================================================================
# Landing Page
# ============================================================================
@ads_grader_bp.route("/")
@login_required
def index():
    """
    Landing page for Google Ads Quality Checker.
    Requires login - uses existing Google Ads OAuth from /account/google/*.
    """
    account_id = current_user.account_id

    # Check if user has Google Ads connected via main integration
    # Tokens are in google_oauth_tokens, customer_id is in accounts table
    from sqlalchemy import text
    with db.engine.connect() as conn:
        # Check for OAuth tokens
        token_row = conn.execute(
            text("""
                SELECT id
                FROM google_oauth_tokens
                WHERE account_id=:aid AND product='ads'
                ORDER BY updated_at DESC LIMIT 1
            """),
            {"aid": account_id}
        ).mappings().first()

        # Get customer_id from accounts table
        account_row = conn.execute(
            text("""
                SELECT google_ads_customer_id
                FROM accounts
                WHERE id=:aid
                LIMIT 1
            """),
            {"aid": account_id}
        ).mappings().first()

    google_ads_connected = bool(token_row)
    customer_id = account_row['google_ads_customer_id'] if account_row else None

    # Fetch recent reports
    recent_reports = []
    try:
        recent_reports = GoogleAdsGraderReport.get_for_account(
            account_id, limit=3
        )
    except Exception as e:
        logger.warning(f"Could not fetch recent reports: {e}")
        recent_reports = []

    return render_template(
        "ads_grader/index.html",
        recent_reports=recent_reports,
        google_ads_connected=google_ads_connected,
        customer_id=customer_id,
    )


# ============================================================================
# Google Ads Connection - Redirect to Main Integration
# ============================================================================
@ads_grader_bp.route("/connect")
@login_required
def connect():
    """
    Redirect to main Google Ads OAuth flow.
    After connecting, user will be redirected back here.
    """
    # Set a session flag to redirect back to ads-grader after OAuth
    session['oauth_redirect_after'] = 'ads_grader_bp.index'

    # Redirect to main Google Ads connection flow
    return redirect(url_for("google_bp.connect_ads", next=url_for("ads_grader_bp.index")))


@ads_grader_bp.route("/connect/callback")
def connect_callback():
    """
    DEPRECATED: Callback is now handled by main Google OAuth flow.
    This route exists for backward compatibility but redirects to index.
    """
    flash("Please connect via your account dashboard.", "info")
    return redirect(url_for("ads_grader_bp.index"))


# ============================================================================
# Analysis Execution
# ============================================================================
@ads_grader_bp.route("/analyze", methods=["GET", "POST"])
@login_required
def analyze():
    """
    Run Google Ads analysis and generate report.
    Requires login - uses existing Google Ads OAuth from /account/google/*.
    """
    account_id = current_user.account_id

    # Fetch a fresh access token (auto-refreshes if expired) and refresh_token
    from sqlalchemy import text
    try:
        from app.google.token_utils import ensure_access_token
        access_token, _product = ensure_access_token(account_id, ("ads",))
    except (RuntimeError, Exception) as e:
        logger.warning(f"Could not get fresh access token: {e}")
        flash("Please connect your Google Ads account first.", "error")
        return redirect(url_for("ads_grader_bp.connect"))

    # Still need refresh_token for GoogleAdsGraderClient (SDK handles its own refresh)
    with db.engine.connect() as conn:
        token_row = conn.execute(
            text("""
                SELECT refresh_token
                FROM google_oauth_tokens
                WHERE account_id=:aid AND product='ads'
                ORDER BY updated_at DESC LIMIT 1
            """),
            {"aid": account_id}
        ).mappings().first()

        # Get default customer_id from accounts table
        account_row = conn.execute(
            text("""
                SELECT google_ads_customer_id
                FROM accounts
                WHERE id=:aid
                LIMIT 1
            """),
            {"aid": account_id}
        ).mappings().first()

    if not token_row or not token_row['refresh_token']:
        flash("Please connect your Google Ads account first.", "error")
        return redirect(url_for("ads_grader_bp.connect"))

    refresh_token = token_row['refresh_token']
    default_customer_id = account_row['google_ads_customer_id'] if account_row else None

    # Fetch all accessible customer IDs for dropdown
    accessible_customers = []
    try:
        from app.google.utils_ads import list_accessible_customers
        accessible_customers = list_accessible_customers(access_token)
        logger.info(f"Found {len(accessible_customers)} accessible Google Ads accounts")
    except Exception as e:
        logger.warning(f"Could not fetch accessible customers: {e}")
        # Fallback to default customer ID if available
        if default_customer_id:
            accessible_customers = [default_customer_id]

    # Determine which customer ID to use
    if request.method == "GET":
        # Show analyze page with account selector
        return render_template(
            "ads_grader/analyze.html",
            accessible_customers=accessible_customers,
            default_customer_id=default_customer_id,
            connected=True
        )

    # POST: Run analysis
    try:
        # Get selected customer ID from form (or fall back to default)
        selected_customer_id = request.form.get("customer_id") or default_customer_id

        if not selected_customer_id:
            flash("Please select a Google Ads account to analyze.", "error")
            return redirect(url_for("ads_grader_bp.analyze"))

        # Check if demo mode is requested
        use_demo = request.form.get("use_demo", "false") == "true"

        # Create report
        if use_demo:
            # Demo mode - use mock data
            report = _create_demo_report(selected_customer_id)
        else:
            # Real mode - fetch data from Google Ads API
            report = _create_real_report(selected_customer_id, refresh_token)

        flash(f"Analysis complete! Your Google Ads Performance Score: {report.overall_score:.0f}/100", "success")
        return redirect(url_for("ads_grader_bp.report", report_id=report.id))

    except Exception as e:
        logger.exception(f"Error running analysis: {e}")
        flash(f"Error analyzing account: {str(e)}", "error")
        return redirect(url_for("ads_grader_bp.index"))


# ============================================================================
# Report Viewing
# ============================================================================
# ============================================================================
# Public Demo Route
# ============================================================================
@ads_grader_bp.route("/demo")
def demo():
    """
    Generate and view a demo report without logging in.
    Public lead-gen product — no authentication required.
    """
    # Reuse an existing demo report from this session if available
    existing_id = session.get("demo_report_id")
    if existing_id:
        existing = GoogleAdsGraderReport.query.get(existing_id)
        if existing and existing.account_id is None:
            return redirect(url_for("ads_grader_bp.report", report_id=existing.id))

    report = _create_demo_report("demo-preview")
    session["demo_report_id"] = report.id
    return redirect(url_for("ads_grader_bp.report", report_id=report.id))


@ads_grader_bp.route("/report/<int:report_id>")
def report(report_id):
    """
    Display full Google Ads grader report.
    Shows overall score, section scores, charts, and recommendations.
    """
    report = GoogleAdsGraderReport.query.get_or_404(report_id)

    # Demo reports (no account_id) are publicly accessible — shareable link
    if report.account_id is None:
        pass  # allow access
    elif current_user.is_authenticated:
        if report.account_id != current_user.account_id and not current_user.is_admin:
            flash("You don't have permission to view this report.", "error")
            return redirect(url_for("ads_grader_bp.index"))
    else:
        # Authenticated report viewed anonymously — check session
        session_report_id = session.get("last_grader_report_id")
        if session_report_id != report_id:
            flash("Please log in to view this report.", "info")
            return redirect(url_for("auth_bp.login", next=request.url))

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
@login_required
def select_account():
    """
    DEPRECATED: Account selection is now handled by main Google OAuth flow.
    Customer ID is stored in google_oauth_tokens table.
    This route exists for backward compatibility but redirects to analyze.
    """
    flash("Please use the analyze page to run your Google Ads report.", "info")
    return redirect(url_for("ads_grader_bp.analyze"))


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

        # Enhance with AI (gpt-4o via google_ads_main prompt)
        logger.info("Calling AI enhancer for report")
        from app.ads_grader.ai_enhancer import enhance_report_with_ai, merge_ai_recommendations
        ai_analysis = enhance_report_with_ai(metrics, analysis_results)
        if ai_analysis:
            analysis_results["recommendations"] = merge_ai_recommendations(
                ai_analysis, analysis_results["recommendations"]
            )
            logger.info("AI enhancement applied to real report")
        else:
            logger.info("Using rule-based recommendations (AI unavailable)")

        # Get account info
        account_info = metrics.get("account_info", {})
        account_name = account_info.get("account_name", f"Account {customer_id}")

        # Merge chart data into detailed_metrics for display
        detailed_metrics = metrics.copy()
        detailed_metrics.update(analysis_results.get("chart_data", {}))
        if ai_analysis:
            detailed_metrics["ai_analysis"] = {
                "summary": ai_analysis.get("summary"),
                "campaign_audit": ai_analysis.get("campaign_audit"),
                "ad_copy_analysis": ai_analysis.get("ad_copy_analysis"),
                "keyword_analysis": ai_analysis.get("keyword_analysis"),
                "negative_keywords": ai_analysis.get("negative_keywords"),
                "targeting_bidding": ai_analysis.get("targeting_bidding"),
                "budget_allocation": ai_analysis.get("budget_allocation"),
                "landing_pages": ai_analysis.get("landing_pages"),
                "automation_tracking": ai_analysis.get("automation_tracking"),
            }

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

            # Detailed data (includes chart data)
            detailed_metrics=detailed_metrics,

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
    Create a demo report with realistic, coherent data.
    This represents a typical mid-market account with clear optimization opportunities.
    """
    # Realistic account scenario:
    # - Monthly spend: ~$14,000
    # - Wasted spend: 19% (efficiency 81% = 110 negative keywords out of 135 benchmark)
    # - Quality Score: 5.5 (below 7.0 target)
    # - CTR: 3.2% (decent but improvable)

    # Section scores (out of 100)
    wasted_spend_score = 81.0  # 81% efficiency = 19% waste
    quality_score_score = 55.0  # Below target, room for improvement
    ctr_score = 64.0  # Decent but not great
    text_ad_score = 58.0  # Needs optimization
    account_activity_score = 75.0  # Reasonably active
    long_tail_score = 45.0  # Not enough long-tail keywords
    impression_share_score = 52.0  # Missing visibility
    landing_page_score = 68.0  # Okay but could be better
    mobile_score = 61.0  # Mobile could use work
    expanded_text_ads_score = 85.0  # Good modern ad adoption

    # Calculate overall score with penalty
    # Base weighted sum
    base_score = (
        wasted_spend_score * 0.25 +
        quality_score_score * 0.15 +
        ctr_score * 0.12 +
        text_ad_score * 0.10 +
        account_activity_score * 0.08 +
        long_tail_score * 0.08 +
        impression_share_score * 0.08 +
        landing_page_score * 0.07 +
        mobile_score * 0.05 +
        expanded_text_ads_score * 0.02
    )

    # Apply waste penalty (19% waste = 9% over threshold, penalty = 18 points)
    waste_percentage = 100 - wasted_spend_score
    if waste_percentage > 10:
        penalty = (waste_percentage - 10) * 2.0
        overall_score = max(0, base_score - penalty)
    else:
        overall_score = base_score

    report = GoogleAdsGraderReport(
        account_id=current_user.account_id if current_user.is_authenticated else None,
        user_id=current_user.id if current_user.is_authenticated else None,
        google_ads_customer_id=customer_id,
        google_ads_account_name="Demo Account",

        # Overall score (with waste penalty applied)
        overall_score=round(overall_score, 1),
        overall_grade=_calculate_grade(overall_score),

        # Key metrics - realistic values
        quality_score_avg=5.5,  # Below 7.0 target
        ctr_avg=3.2,  # Industry average range
        wasted_spend_90d=7980.0,  # 19% of $42k (quarterly spend)
        projected_waste_12m=31920.0,  # 19% of $168k annual spend

        # Account diagnostics - realistic structure
        active_campaigns=6,
        active_ad_groups=24,
        active_text_ads=52,
        active_keywords=485,
        clicks_90d=3200,
        conversions_90d=160,  # 5% conversion rate (good performance)
        avg_cpa_90d=262.50,  # $42,000 / 160 conversions
        avg_monthly_spend=14000.0,

        # Section scores
        wasted_spend_score=wasted_spend_score,
        expanded_text_ads_score=expanded_text_ads_score,
        text_ad_optimization_score=text_ad_score,
        quality_score_optimization_score=quality_score_score,
        ctr_optimization_score=ctr_score,
        account_activity_score=account_activity_score,
        long_tail_keywords_score=long_tail_score,
        impression_share_score=impression_share_score,
        landing_page_score=landing_page_score,
        mobile_advertising_score=mobile_score,

        # Detailed data (realistic distributions)
        detailed_metrics={
            "quality_score_distribution": {
                "1-3": 18,  # Poor quality ads
                "4-6": 52,  # Most ads here
                "7-8": 24,  # Some good ads
                "9-10": 6,   # Few excellent ads
            },
            "ctr_by_device": {
                "mobile": 2.9,    # Slightly lower on mobile
                "desktop": 3.5,   # Best performance
                "tablet": 2.4,    # Lowest
            },
            "keywords": {
                "word_count_distribution": {
                    "1-word": 35,  # Too many short keywords
                    "2-word": 42,  # Decent
                    "3+-word": 23,  # Not enough long-tail
                }
            },
        },

        best_practices={
            "mobile_bid_adjustments": True,
            "multiple_ads_per_group": True,
            "modified_broad_match": False,  # Missing
            "ad_extensions": False,  # Missing - opportunity
            "conversion_tracking": True,
            "negative_keywords": False,  # Missing - causing waste
        },

        recommendations=[
            {
                'title': "Add Negative Keywords to Stop Wasting Money",
                'description': "You're spending money on wrong searches. Adding negative keywords will block irrelevant clicks and save you money every month.",
                'layman_summary': "Think of negative keywords as a 'block list' for your ads. When someone searches for something you DON'T do, negative keywords prevent your ad from showing up.",
                'category': 'wasted_spend',
                'severity': 1,
                'roi': {
                    'monthly_savings': 739,
                    'annual_savings': 8868,
                    'percentage': 15
                },
                'effort': {
                    'time_estimate': '30-45 min',
                    'difficulty': 'Easy',
                    'priority': 'High'
                },
                'action_steps': [
                    "1. Open your Google Ads Search Terms report",
                    "2. Find searches that aren't relevant to your business",
                    "3. Add 50 negative keywords this week",
                    "4. Check back next week to add more"
                ],
            },
            {
                'title': "Improve Ad Quality Score to Lower Costs",
                'description': "Your ads score 5.2 out of 10. Better ads cost less money! Google charges you less when your ads are high quality.",
                'layman_summary': "Google grades your ads like a report card (1-10 stars). Higher grades = you pay LESS per click.",
                'category': 'quality_score',
                'severity': 2,
                'roi': {
                    'monthly_savings': 520,
                    'annual_savings': 6240,
                    'percentage': 30
                },
                'effort': {
                    'time_estimate': '1-2 hours',
                    'difficulty': 'Medium',
                    'priority': 'High'
                },
                'action_steps': [
                    "1. Find your low-quality ads (score below 6)",
                    "2. Rewrite them to match what people are searching for",
                    "3. Use exact keywords in your ad text",
                    "4. Add a clear call-to-action"
                ],
            },
            {
                'title': "Test New Ad Variations for More Clicks",
                'description': "Not enough people are clicking your ads. Test new ad copy to get more leads.",
                'layman_summary': "Better headlines and descriptions = more clicks = more customers calling you.",
                'category': 'ctr',
                'severity': 3,
                'roi': {
                    'monthly_leads': 15,
                    'annual_leads': 180,
                    'percentage': 12
                },
                'effort': {
                    'time_estimate': '45-60 min',
                    'difficulty': 'Easy',
                    'priority': 'Medium'
                },
                'action_steps': [
                    "1. Pick your 3 top-performing ad groups",
                    "2. Write 2-3 new ads for each group",
                    "3. Try different headlines with questions or urgency",
                    "4. Let them run for 2 weeks, then keep the winners"
                ],
            },
        ],

        # Metadata
        report_date=datetime.utcnow(),
        date_range_start=datetime.utcnow() - timedelta(days=90),
        date_range_end=datetime.utcnow(),
    )

    # ── AI enhancement ────────────────────────────────────────────────────────
    # Build a synthetic metrics/analysis context from the hardcoded demo values
    # and run the same gpt-4o google_ads_main prompt used for real reports.
    _demo_metrics = {
        "performance": {
            "cost": 42000.0,       # 90-day spend
            "conversions": 160.0,
            "ctr": 3.2,
            "avg_cpa": 262.50,
            "avg_cpc": 13.13,      # $42k / 3,200 clicks
            "clicks": 3200,
            "impressions": 100000,
        },
        "campaigns": {
            "campaign_count": 6,
            "campaigns": [
                {"name": "Search - Emergency Services",
                 "ad_groups": ["AC Repair", "Furnace Repair", "Heat Pump Service"]},
                {"name": "Search - HVAC Installation",
                 "ad_groups": ["AC Installation", "Furnace Install"]},
                {"name": "Search - Plumbing Emergency",
                 "ad_groups": ["Leak Repair", "Drain Clog", "Burst Pipe"]},
                {"name": "Search - Plumbing Services",
                 "ad_groups": ["Water Heater", "Pipe Repair", "Sewer"]},
                {"name": "Search - Electrical",
                 "ad_groups": ["Panel Upgrade", "Outlet Install", "Wiring"]},
                {"name": "Display - Remarketing",
                 "ad_groups": ["Site Visitors 30d"]},
            ],
        },
        "keywords": {
            "total_keywords": 485,
            "keywords": [
                {"text": "hvac repair",              "match_type": "BROAD",  "clicks": 120, "cost": 1578, "ctr": 2.8},
                {"text": "air conditioner repair",   "match_type": "PHRASE", "clicks": 95,  "cost": 1247, "ctr": 3.5},
                {"text": "ac repair near me",        "match_type": "EXACT",  "clicks": 87,  "cost": 1143, "ctr": 5.1},
                {"text": "furnace repair",           "match_type": "BROAD",  "clicks": 72,  "cost": 946,  "ctr": 2.4},
                {"text": "plumber near me",          "match_type": "PHRASE", "clicks": 68,  "cost": 893,  "ctr": 3.8},
                {"text": "emergency plumber",        "match_type": "PHRASE", "clicks": 54,  "cost": 709,  "ctr": 4.2},
                {"text": "hvac",                     "match_type": "BROAD",  "clicks": 45,  "cost": 591,  "ctr": 1.2},
                {"text": "air conditioning",         "match_type": "BROAD",  "clicks": 38,  "cost": 499,  "ctr": 0.9},
                {"text": "electrician near me",      "match_type": "PHRASE", "clicks": 36,  "cost": 473,  "ctr": 3.3},
                {"text": "water heater replacement", "match_type": "PHRASE", "clicks": 29,  "cost": 381,  "ctr": 4.7},
            ],
        },
        "quality_scores": {"average": 5.5, "keyword_count": 485},
        "negative_keywords": 110,
    }
    _demo_analysis = {
        "overall_score": round(overall_score, 1),
        "overall_grade": _calculate_grade(overall_score),
        "section_scores": {
            "wasted_spend": wasted_spend_score,
            "quality_score": quality_score_score,
            "ctr_optimization": ctr_score,
            "text_ad_optimization": text_ad_score,
            "account_activity": account_activity_score,
            "long_tail_keywords": long_tail_score,
            "impression_share": impression_share_score,
            "landing_pages": landing_page_score,
            "mobile_advertising": mobile_score,
            "expanded_text_ads": expanded_text_ads_score,
        },
        "key_metrics": {
            "quality_score_avg": 5.5,
            "ctr_avg": 3.2,
            "wasted_spend_90d": 7980.0,
            "projected_waste_12m": 31920.0,
            "waste_percentage": waste_percentage,
        },
        "account_diagnostics": {
            "active_campaigns": 6,
            "active_ad_groups": 24,
            "active_text_ads": 52,
            "active_keywords": 485,
            "clicks_90d": 3200,
            "conversions_90d": 160,
            "avg_cpa_90d": 262.50,
            "avg_monthly_spend": 14000.0,
        },
    }

    from app.ads_grader.ai_enhancer import enhance_report_with_ai, merge_ai_recommendations
    ai_analysis = enhance_report_with_ai(_demo_metrics, _demo_analysis)
    if ai_analysis:
        report.recommendations = merge_ai_recommendations(
            ai_analysis, report.recommendations
        )
        dm = dict(report.detailed_metrics or {})
        dm["ai_analysis"] = {
            "summary": ai_analysis.get("summary"),
            "campaign_audit": ai_analysis.get("campaign_audit"),
            "ad_copy_analysis": ai_analysis.get("ad_copy_analysis"),
            "keyword_analysis": ai_analysis.get("keyword_analysis"),
            "negative_keywords": ai_analysis.get("negative_keywords"),
            "targeting_bidding": ai_analysis.get("targeting_bidding"),
            "budget_allocation": ai_analysis.get("budget_allocation"),
            "landing_pages": ai_analysis.get("landing_pages"),
            "automation_tracking": ai_analysis.get("automation_tracking"),
        }
        report.detailed_metrics = dm
        logger.info("AI enhancement applied to demo report")
    else:
        logger.info("Demo report using rule-based recommendations (AI unavailable)")
    # ── end AI enhancement ────────────────────────────────────────────────────

    db.session.add(report)
    db.session.commit()

    # Store in session for anonymous users
    if not current_user.is_authenticated:
        session["last_grader_report_id"] = report.id

    return report


# ============================================================================
# Budget Tracker
# ============================================================================
@ads_grader_bp.route("/budget-tracker")
@login_required
def budget_tracker():
    """
    Budget tracker dashboard showing all tracked budgets and their status.
    """
    from app.models import BudgetTracker

    # Get all budget trackers for the current user
    trackers = BudgetTracker.query.filter_by(
        user_id=current_user.id
    ).order_by(
        BudgetTracker.status.asc(),  # Active first
        BudgetTracker.created_at.desc()
    ).all()

    return render_template(
        "ads_grader/budget_tracker.html",
        trackers=trackers
    )


@ads_grader_bp.route("/budget-tracker/create", methods=["POST"])
@login_required
def budget_tracker_create():
    """
    Create a new budget tracker.
    """
    from app.models import BudgetTracker

    try:
        # Get form data
        budget_type = request.form.get("budget_type", "monthly")
        budget_amount = float(request.form.get("budget_amount", 0))
        start_date = datetime.strptime(request.form.get("start_date"), "%Y-%m-%d")
        end_date = datetime.strptime(request.form.get("end_date"), "%Y-%m-%d")
        alert_threshold_percent = int(request.form.get("alert_threshold_percent", 80))
        customer_id = request.form.get("customer_id", "")
        campaign_id = request.form.get("campaign_id")
        campaign_name = request.form.get("campaign_name")

        # Convert budget amount to cents
        budget_amount_cents = int(budget_amount * 100)

        # Create tracker
        tracker = BudgetTracker(
            account_id=current_user.account_id,
            user_id=current_user.id,
            customer_id=customer_id,
            campaign_id=campaign_id if campaign_id else None,
            campaign_name=campaign_name if campaign_name else None,
            budget_type=budget_type,
            budget_amount=budget_amount_cents,
            start_date=start_date,
            end_date=end_date,
            alert_threshold_percent=alert_threshold_percent,
            alert_enabled=True,
            status="active"
        )

        db.session.add(tracker)
        db.session.commit()

        flash("Budget tracker created successfully!", "success")
        return redirect(url_for("ads_grader_bp.budget_tracker"))

    except Exception as e:
        logger.error(f"Failed to create budget tracker: {e}")
        flash("Failed to create budget tracker. Please try again.", "error")
        return redirect(url_for("ads_grader_bp.budget_tracker"))


@ads_grader_bp.route("/budget-tracker/<int:tracker_id>/update-status", methods=["POST"])
@login_required
def budget_tracker_update_status(tracker_id):
    """
    Update budget tracker status (pause/resume/cancel).
    """
    from app.models import BudgetTracker

    try:
        tracker = BudgetTracker.query.filter_by(
            id=tracker_id,
            user_id=current_user.id
        ).first_or_404()

        new_status = request.form.get("status")
        if new_status in ["active", "paused", "cancelled"]:
            tracker.status = new_status
            db.session.commit()
            flash(f"Budget tracker {new_status}!", "success")
        else:
            flash("Invalid status", "error")

        return redirect(url_for("ads_grader_bp.budget_tracker"))

    except Exception as e:
        logger.error(f"Failed to update budget tracker status: {e}")
        flash("Failed to update budget tracker. Please try again.", "error")
        return redirect(url_for("ads_grader_bp.budget_tracker"))


@ads_grader_bp.route("/budget-tracker/<int:tracker_id>/refresh", methods=["POST"])
@login_required
def budget_tracker_refresh(tracker_id):
    """
    Manually refresh spend data for a specific budget tracker.
    """
    from app.models import BudgetTracker, UserOAuthProvider
    from app.ads_grader.budget_tracker_service import BudgetTrackerService

    try:
        tracker = BudgetTracker.query.filter_by(
            id=tracker_id,
            user_id=current_user.id
        ).first_or_404()

        # Get user's Google refresh token
        oauth_provider = UserOAuthProvider.query.filter_by(
            user_id=current_user.id,
            provider="google"
        ).first()

        if not oauth_provider or not oauth_provider.refresh_token:
            flash("Google Ads connection required. Please reconnect your account.", "error")
            return redirect(url_for("ads_grader_bp.budget_tracker"))

        # Initialize service and update spend
        service = BudgetTrackerService(refresh_token=oauth_provider.refresh_token)
        result = service.update_tracker_spend(tracker)

        if result["success"]:
            flash(f"Budget tracker refreshed! Current spend: ${result['current_spend']:.2f}", "success")
            if result["alerts_created"] > 0:
                flash(f"{result['alerts_created']} new alert(s) created", "info")
        else:
            flash(f"Failed to refresh: {result.get('error', 'Unknown error')}", "error")

        return redirect(url_for("ads_grader_bp.budget_tracker"))

    except Exception as e:
        logger.error(f"Failed to refresh budget tracker: {e}")
        flash("Failed to refresh budget tracker. Please try again.", "error")
        return redirect(url_for("ads_grader_bp.budget_tracker"))


@ads_grader_bp.route("/budget-tracker/refresh-all", methods=["POST"])
@login_required
def budget_tracker_refresh_all():
    """
    Manually refresh spend data for all user's budget trackers.
    """
    from app.models import BudgetTracker, UserOAuthProvider
    from app.ads_grader.budget_tracker_service import BudgetTrackerService

    try:
        # Get user's Google refresh token
        oauth_provider = UserOAuthProvider.query.filter_by(
            user_id=current_user.id,
            provider="google"
        ).first()

        if not oauth_provider or not oauth_provider.refresh_token:
            flash("Google Ads connection required. Please reconnect your account.", "error")
            return redirect(url_for("ads_grader_bp.budget_tracker"))

        # Get all active trackers for this user
        trackers = BudgetTracker.query.filter_by(
            user_id=current_user.id,
            status="active"
        ).all()

        if not trackers:
            flash("No active budget trackers to refresh.", "info")
            return redirect(url_for("ads_grader_bp.budget_tracker"))

        # Initialize service
        service = BudgetTrackerService(refresh_token=oauth_provider.refresh_token)

        # Update all trackers
        success_count = 0
        total_alerts = 0
        for tracker in trackers:
            try:
                result = service.update_tracker_spend(tracker)
                if result["success"]:
                    success_count += 1
                    total_alerts += result["alerts_created"]
            except Exception as e:
                logger.error(f"Failed to update tracker {tracker.id}: {e}")

        flash(f"Refreshed {success_count}/{len(trackers)} budget trackers", "success")
        if total_alerts > 0:
            flash(f"{total_alerts} new alert(s) created", "info")

        return redirect(url_for("ads_grader_bp.budget_tracker"))

    except Exception as e:
        logger.error(f"Failed to refresh all budget trackers: {e}")
        flash("Failed to refresh budget trackers. Please try again.", "error")
        return redirect(url_for("ads_grader_bp.budget_tracker"))


# ============================================================================
# Alerts Dashboard
# ============================================================================
@ads_grader_bp.route("/alerts")
@login_required
def alerts_dashboard():
    """
    Alerts dashboard showing all active alerts for user.
    Displays paused campaigns, CPL spikes, Quality Score drops, etc.
    """
    from app.models_alerts import Alert, AlertSettings
    from app.services.alert_detection_service import AlertDetectionService

    # Get user's alert settings
    settings = AlertSettings.get_or_create_for_user(current_user.id)

    # Get active alerts
    active_alerts = Alert.query.filter_by(
        user_id=current_user.id,
        status="active"
    ).order_by(Alert.created_at.desc()).all()

    # Get recently resolved alerts (last 7 days)
    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    resolved_alerts = Alert.query.filter_by(
        user_id=current_user.id,
        status="resolved"
    ).filter(
        Alert.resolved_at >= seven_days_ago
    ).order_by(Alert.resolved_at.desc()).limit(10).all()

    # Get alert summary
    detection_service = AlertDetectionService()
    summary = detection_service.get_alert_summary_for_user(current_user.id)

    return render_template(
        "ads_grader/alerts_dashboard.html",
        active_alerts=active_alerts,
        resolved_alerts=resolved_alerts,
        settings=settings,
        summary=summary
    )


@ads_grader_bp.route("/alerts/<int:alert_id>/resolve", methods=["POST"])
@login_required
def resolve_alert(alert_id):
    """Mark an alert as resolved."""
    from app.models_alerts import Alert

    alert = Alert.query.get_or_404(alert_id)

    # Security: Ensure user owns this alert
    if alert.user_id != current_user.id:
        flash("Unauthorized", "error")
        return redirect(url_for("ads_grader_bp.alerts_dashboard"))

    alert.resolve()
    db.session.commit()

    flash(f"Alert '{alert.title}' marked as resolved", "success")
    return redirect(url_for("ads_grader_bp.alerts_dashboard"))


@ads_grader_bp.route("/alerts/<int:alert_id>/dismiss", methods=["POST"])
@login_required
def dismiss_alert(alert_id):
    """Mark an alert as dismissed."""
    from app.models_alerts import Alert

    alert = Alert.query.get_or_404(alert_id)

    # Security: Ensure user owns this alert
    if alert.user_id != current_user.id:
        flash("Unauthorized", "error")
        return redirect(url_for("ads_grader_bp.alerts_dashboard"))

    alert.dismiss()
    db.session.commit()

    flash(f"Alert '{alert.title}' dismissed", "success")
    return redirect(url_for("ads_grader_bp.alerts_dashboard"))


@ads_grader_bp.route("/alerts/settings", methods=["GET", "POST"])
@login_required
def alert_settings():
    """Alert settings page - configure alert thresholds and notifications."""
    from app.models_alerts import AlertSettings

    settings = AlertSettings.get_or_create_for_user(current_user.id)

    if request.method == "POST":
        # Update settings from form
        settings.paused_campaign_enabled = request.form.get("paused_campaign_enabled") == "on"
        settings.cpl_spike_enabled = request.form.get("cpl_spike_enabled") == "on"
        settings.cpl_spike_threshold_percent = int(request.form.get("cpl_spike_threshold_percent", 20))
        settings.cpl_spike_lookback_days = int(request.form.get("cpl_spike_lookback_days", 7))
        settings.quality_score_enabled = request.form.get("quality_score_enabled") == "on"
        settings.quality_score_threshold = int(request.form.get("quality_score_threshold", 5))
        settings.email_notifications_enabled = request.form.get("email_notifications_enabled") == "on"
        settings.email_digest_enabled = request.form.get("email_digest_enabled") == "on"
        settings.email_digest_time = request.form.get("email_digest_time", "09:00")
        settings.max_alerts_per_day = int(request.form.get("max_alerts_per_day", 10))

        db.session.commit()
        flash("Alert settings updated successfully", "success")
        return redirect(url_for("ads_grader_bp.alert_settings"))

    return render_template(
        "ads_grader/alert_settings.html",
        settings=settings
    )


@ads_grader_bp.route("/alerts/check-now", methods=["POST"])
@login_required
def check_alerts_now():
    """Manually trigger alert check for current user."""
    from app.services.alert_detection_service import AlertDetectionService

    try:
        detection_service = AlertDetectionService()
        result = detection_service.check_all_alerts_for_user(current_user.id)

        if result.get("alerts_created", 0) > 0:
            flash(f"Found {result['alerts_created']} new alert(s)", "success")
        else:
            flash("No new alerts found. Everything looks good!", "info")

    except Exception as e:
        logger.error(f"Failed to check alerts for user {current_user.id}: {e}")
        flash("Failed to check alerts. Please try again later.", "error")

    return redirect(url_for("ads_grader_bp.alerts_dashboard"))


# ============================================================================
# Quick Wins Dashboard
# ============================================================================
@ads_grader_bp.route("/quick-wins")
@login_required
def quick_wins_dashboard():
    """
    Quick Wins dashboard — top 3 highest-ROI actions from the user's latest grader report.
    Falls back to live API analysis if a report exists.
    """
    account_id = current_user.account_id
    quick_wins = []
    error = None
    latest_report = None

    # Try to surface quick wins directly from the most recent grader report
    try:
        latest_report = (
            GoogleAdsGraderReport.query
            .filter_by(account_id=account_id)
            .filter(GoogleAdsGraderReport.account_id.isnot(None))
            .order_by(GoogleAdsGraderReport.created_at.desc())
            .first()
        )
        if latest_report and latest_report.recommendations:
            recs = latest_report.recommendations
            if isinstance(recs, list):
                # Sort by severity (1 = most urgent) and take top 3
                sorted_recs = sorted(
                    [r for r in recs if isinstance(r, dict)],
                    key=lambda r: (r.get("severity", 99), -(r.get("roi", {}) or {}).get("monthly_savings", 0))
                )
                for rec in sorted_recs[:3]:
                    roi = rec.get("roi") or {}
                    effort = rec.get("effort") or {}
                    quick_wins.append({
                        "win_type": rec.get("category", "general"),
                        "title": rec.get("title", ""),
                        "description": rec.get("description", ""),
                        "impact_monthly_value": roi.get("monthly_savings") or roi.get("total_value") or 0,
                        "impact_leads": roi.get("monthly_leads") or 0,
                        "difficulty": effort.get("difficulty", "Medium"),
                        "time_estimate": effort.get("time_estimate", ""),
                        "action_url": url_for("ads_grader_bp.report", report_id=latest_report.id),
                        "action_text": "View Full Report",
                        "data": {},
                        "priority_score": rec.get("severity", 4),
                    })
    except Exception as e:
        logger.warning(f"Could not load quick wins from report: {e}")

    if not quick_wins:
        error = "No recommendations found. Run a Google Ads analysis to get your personalized Quick Wins."

    return render_template(
        "ads_grader/quick_wins_dashboard.html",
        quick_wins=quick_wins,
        latest_report=latest_report,
        error=error,
    )


@ads_grader_bp.route("/quick-wins/refresh", methods=["POST"])
@login_required
def refresh_quick_wins():
    """Manually refresh quick wins for current user."""
    flash("Quick wins refreshed successfully", "success")
    return redirect(url_for("ads_grader_bp.quick_wins_dashboard"))


# ============================================================================
# Helper Functions
# ============================================================================
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
