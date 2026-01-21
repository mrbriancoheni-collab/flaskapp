# app/admin/lead_campaigns_routes.py
"""
Admin routes for Lead Generation Campaigns

Manage campaigns, view leads, send emails
"""
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from sqlalchemy import desc, func
import logging
import html
import uuid
from threading import Thread

from app.extensions import db
from app.auth.decorators import require_admin_cloaked as require_admin
from app.models_leads import LeadCampaign, Lead, EmailSequence, LeadEmail, LeadContactEmail, EmailUnsubscribe
from app.services.serpapi_scraper import SerpAPIScraperService
from app.services.lead_enrichment import LeadEnrichmentService
from app.services.brevo_outreach import BrevoOutreachService
from app.configs.lead_automation_config import HOME_SERVICE_CATEGORIES

logger = logging.getLogger(__name__)


def text_to_html(text):
    """
    Convert plain text to HTML, preserving line breaks and paragraphs.
    Escapes HTML for security while preserving template variables like {{company_name}}.
    """
    if not text:
        return ''

    # Split into paragraphs (double line breaks)
    paragraphs = text.split('\n\n')

    html_parts = []
    for para in paragraphs:
        if para.strip():
            # Escape HTML but preserve template variables
            # First, temporarily replace template variables
            import re
            placeholders = {}
            counter = 0

            def replace_var(match):
                nonlocal counter
                placeholder = f"__PLACEHOLDER_{counter}__"
                placeholders[placeholder] = match.group(0)
                counter += 1
                return placeholder

            # Find and replace {{variable}} patterns
            para_with_placeholders = re.sub(r'\{\{[^}]+\}\}', replace_var, para)

            # Escape HTML
            escaped = html.escape(para_with_placeholders)

            # Restore template variables
            for placeholder, original in placeholders.items():
                escaped = escaped.replace(placeholder, original)

            # Convert single line breaks to <br>
            escaped = escaped.replace('\n', '<br>\n')

            # Wrap in paragraph
            html_parts.append(f'<p>{escaped}</p>')

    return '\n'.join(html_parts)

lead_campaigns_bp = Blueprint('lead_campaigns_bp', __name__, url_prefix='/admin/lead-campaigns')


# ==================== Monitoring & Analytics ====================

@lead_campaigns_bp.route('/debug-stats')
@require_admin
def debug_stats():
    """Debug endpoint to show raw database statistics"""
    campaigns = LeadCampaign.query.order_by(desc(LeadCampaign.created_at)).all()

    debug_data = []
    for campaign in campaigns:
        # Get all counts
        leads_total = Lead.query.filter_by(campaign_id=campaign.id).count()
        leads_enriched = Lead.query.filter_by(campaign_id=campaign.id, enrichment_status='completed').count()
        leads_pending_enrichment = Lead.query.filter_by(campaign_id=campaign.id, enrichment_status='pending').count()

        legacy_emails = LeadEmail.query.join(Lead).filter(Lead.campaign_id == campaign.id).count()
        contact_emails = LeadContactEmail.query.filter_by(campaign_id=campaign.id).count()

        sequences = EmailSequence.query.filter_by(campaign_id=campaign.id).count()

        debug_data.append({
            'id': campaign.id,
            'name': campaign.name,
            'status': campaign.status,
            'industry_service': campaign.industry_service,
            'location': campaign.location,
            'created_at': str(campaign.created_at),
            'stats': {
                'leads_total': leads_total,
                'leads_enriched': leads_enriched,
                'leads_pending_enrichment': leads_pending_enrichment,
                'legacy_emails': legacy_emails,
                'contact_emails': contact_emails,
                'total_emails': legacy_emails + contact_emails,
                'sequences': sequences
            },
            'campaign_table_values': {
                'leads_scraped': campaign.leads_scraped,
                'leads_enriched': campaign.leads_enriched,
                'emails_sent': campaign.emails_sent
            }
        })

    return jsonify({
        'total_campaigns': len(campaigns),
        'campaigns': debug_data
    })

@lead_campaigns_bp.route('/automation-status')
@require_admin
def automation_status():
    """Show automation system status and progress"""
    from app.services.lead_automation_service import LeadAutomationService
    import os
    import json

    service = LeadAutomationService()
    progress = service.get_progress_report()

    # Get today's stats
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_scraped = Lead.query.filter(Lead.created_at >= today_start).count()
    today_enriched = Lead.query.filter(Lead.enriched_at >= today_start).count()

    # Count emails from both tables
    today_legacy_emails = db.session.query(func.count(LeadEmail.id)).filter(
        LeadEmail.sent_at >= today_start
    ).scalar() or 0
    today_contact_emails = db.session.query(func.count(LeadContactEmail.id)).filter(
        LeadContactEmail.sent_at >= today_start
    ).scalar() or 0
    today_emails = today_legacy_emails + today_contact_emails

    # Check if automation is enabled
    state_file = os.getenv('AUTOMATION_STATE_FILE', 'automation_state.json')
    automation_enabled = os.path.exists(state_file)
    last_run = None

    if automation_enabled and os.path.exists(state_file):
        with open(state_file, 'r') as f:
            state = json.load(f)
            last_run = state.get('last_run_date')

    return render_template('admin/lead_campaigns/automation_status.html',
                         progress=progress,
                         today_scraped=today_scraped,
                         today_enriched=today_enriched,
                         today_emails=today_emails,
                         automation_enabled=automation_enabled,
                         last_run=last_run)


@lead_campaigns_bp.route('/activity')
@require_admin
def activity():
    """Show recent activity feed"""
    # Recent leads scraped (last 24 hours)
    yesterday = datetime.now() - timedelta(hours=24)
    recent_leads = Lead.query.filter(
        Lead.created_at >= yesterday
    ).order_by(desc(Lead.created_at)).limit(50).all()

    # Recent enrichments (last 24 hours)
    recent_enrichments = Lead.query.filter(
        Lead.enriched_at >= yesterday,
        Lead.enrichment_status == 'completed'
    ).order_by(desc(Lead.enriched_at)).limit(50).all()

    # Recent emails sent (last 24 hours)
    recent_emails = LeadEmail.query.filter(
        LeadEmail.sent_at >= yesterday
    ).order_by(desc(LeadEmail.sent_at)).limit(50).all()

    return render_template('admin/lead_campaigns/activity.html',
                         recent_leads=recent_leads,
                         recent_enrichments=recent_enrichments,
                         recent_emails=recent_emails)


@lead_campaigns_bp.route('/email-activity')
@require_admin
def email_activity():
    """Show email activity log with filters"""
    page = request.args.get('page', 1, type=int)
    status_filter = request.args.get('status', 'all')
    campaign_filter = request.args.get('campaign', 'all', type=str)

    # Base query
    query = LeadEmail.query.join(Lead)

    # Apply filters
    if status_filter != 'all':
        if status_filter == 'opened':
            query = query.filter(LeadEmail.opened_at.isnot(None))
        elif status_filter == 'bounced':
            query = query.filter(LeadEmail.status == 'bounced')
        elif status_filter == 'sent':
            query = query.filter(LeadEmail.status == 'sent')

    if campaign_filter != 'all':
        query = query.filter(Lead.campaign_id == int(campaign_filter))

    # Paginate
    per_page = 50
    emails = query.order_by(desc(LeadEmail.created_at)).paginate(
        page=page, per_page=per_page, error_out=False
    )

    # Get campaigns for filter dropdown
    campaigns = LeadCampaign.query.order_by(LeadCampaign.name).all()

    return render_template('admin/lead_campaigns/email_activity.html',
                         emails=emails,
                         campaigns=campaigns,
                         status_filter=status_filter,
                         campaign_filter=campaign_filter)


# ==================== Campaign Management ====================

@lead_campaigns_bp.route('/debug/campaign-patterns')
@require_admin
def debug_campaign_patterns():
    """Debug endpoint to see what campaign naming patterns exist"""
    # Get sample of all campaigns with different prefixes
    all_campaigns = LeadCampaign.query.order_by(LeadCampaign.created_at.desc()).limit(50).all()

    patterns = {}
    for campaign in all_campaigns:
        # Extract pattern (first 50 chars of name)
        pattern = campaign.name[:50] if len(campaign.name) > 50 else campaign.name
        if pattern not in patterns:
            patterns[pattern] = {
                'count': 0,
                'example_id': campaign.id,
                'created_at': campaign.created_at.isoformat() if campaign.created_at else None
            }
        patterns[pattern]['count'] += 1

    # Get counts by prefix
    total_campaigns = LeadCampaign.query.count()
    auto_colon = LeadCampaign.query.filter(LeadCampaign.name.like('Auto:%')).count()
    auto_home_services = LeadCampaign.query.filter(LeadCampaign.name.like('Auto: Home Services -%')).count()

    return jsonify({
        'total_campaigns': total_campaigns,
        'campaigns_with_auto_prefix': auto_colon,
        'campaigns_with_consolidated_pattern': auto_home_services,
        'sample_patterns': patterns,
        'recent_50_campaigns': [
            {
                'id': c.id,
                'name': c.name,
                'created_at': c.created_at.isoformat() if c.created_at else None
            }
            for c in all_campaigns
        ]
    })

@lead_campaigns_bp.route('/debug/scheduler-status')
@require_admin
def scheduler_status():
    """Check APScheduler job status"""
    try:
        from flask import current_app
        scheduler = getattr(current_app, 'scheduler', None)

        if not scheduler:
            return jsonify({
                'scheduler_active': False,
                'error': 'Scheduler not initialized. App may need restart.'
            })

        # Get lead automation job
        job = scheduler.get_job('run_lead_automation_daily')

        if not job:
            return jsonify({
                'scheduler_active': True,
                'job_found': False,
                'error': 'Lead automation job not registered. Check background_jobs.py'
            })

        return jsonify({
            'scheduler_active': True,
            'job_found': True,
            'job_id': job.id,
            'next_run_time': job.next_run_time.isoformat() if job.next_run_time else None,
            'trigger': str(job.trigger),
            'current_time_utc': datetime.utcnow().isoformat()
        })

    except Exception as e:
        return jsonify({
            'error': str(e),
            'scheduler_active': False
        }), 500

@lead_campaigns_bp.route('/cleanup/delete-old-campaigns', methods=['POST'])
@require_admin
def delete_old_campaigns():
    """Delete old individual campaigns - keep only the core 20 campaigns"""
    logger.info("=" * 80)
    logger.info("DELETE OLD CAMPAIGNS - Starting deletion process")
    logger.info("=" * 80)

    try:
        # Get the core 20 campaign names (e.g., "Auto: Plumbing", "Auto: HVAC", etc.)
        core_campaign_names = [f"Auto: {business_type}" for business_type in HOME_SERVICE_CATEGORIES.keys()]

        logger.info(f"Core campaigns to keep ({len(core_campaign_names)}):")
        for i, name in enumerate(core_campaign_names, 1):
            logger.info(f"  {i:2d}. {name}")

        # Get all campaigns
        all_campaigns = LeadCampaign.query.all()

        logger.info(f"\nFound {len(all_campaigns)} total campaigns in database:")
        for i, campaign in enumerate(all_campaigns[:10], 1):  # Show first 10
            logger.info(f"  {i:2d}. ID={campaign.id}, Name='{campaign.name}'")
        if len(all_campaigns) > 10:
            logger.info(f"  ... and {len(all_campaigns) - 10} more campaigns")

        # Filter out the core campaigns - delete everything else
        old_campaigns = [c for c in all_campaigns if c.name not in core_campaign_names]

        logger.info(f"\nIdentified {len(old_campaigns)} old campaigns to DELETE:")
        for i, campaign in enumerate(old_campaigns[:20], 1):  # Show first 20
            logger.info(f"  {i:2d}. ID={campaign.id}, Name='{campaign.name}'")
        if len(old_campaigns) > 20:
            logger.info(f"  ... and {len(old_campaigns) - 20} more campaigns to delete")

        # Check which core campaigns exist
        existing_core = [c for c in all_campaigns if c.name in core_campaign_names]
        logger.info(f"\nExisting CORE campaigns to KEEP ({len(existing_core)}):")
        for i, campaign in enumerate(existing_core, 1):
            logger.info(f"  {i:2d}. ID={campaign.id}, Name='{campaign.name}'")

        if len(old_campaigns) == 0:
            logger.info("\n✓ No old campaigns to delete - database is clean!")
            return jsonify({
                'success': True,
                'deleted_count': 0,
                'message': 'No old campaigns to delete. Database is clean!'
            })

        logger.info(f"\nStarting deletion of {len(old_campaigns)} campaigns...")

        deleted_count = 0

        # Delete associated data first (due to foreign key constraints)
        for idx, campaign in enumerate(old_campaigns):
            try:
                campaign_id = campaign.id
                campaign_name = campaign.name

                # Delete associated leads and their emails
                leads = Lead.query.filter_by(campaign_id=campaign_id).all()
                lead_count = len(leads)

                for lead in leads:
                    LeadEmail.query.filter_by(lead_id=lead.id).delete()
                Lead.query.filter_by(campaign_id=campaign_id).delete()

                # Delete associated contact emails
                contact_emails_count = LeadContactEmail.query.filter_by(campaign_id=campaign_id).delete()

                # Delete email sequences
                sequences_count = EmailSequence.query.filter_by(campaign_id=campaign_id).delete()

                # Delete campaign
                db.session.delete(campaign)
                deleted_count += 1

                logger.info(f"  [{idx+1}/{len(old_campaigns)}] Deleted: ID={campaign_id}, Name='{campaign_name}' "
                          f"({lead_count} leads, {contact_emails_count} contact emails, {sequences_count} sequences)")

                # Commit every 100 campaigns to avoid long transactions
                if (idx + 1) % 100 == 0:
                    db.session.commit()
                    logger.info(f"  ✓ COMMITTED: {idx + 1}/{len(old_campaigns)} campaigns deleted so far")

            except Exception as e:
                logger.error(f"  ✗ ERROR deleting campaign ID={campaign.id} Name='{campaign.name}': {str(e)}")
                db.session.rollback()
                continue

        # Final commit
        db.session.commit()

        logger.info("=" * 80)
        logger.info(f"✓ SUCCESS: Deleted {deleted_count} old campaigns and associated data")
        logger.info("=" * 80)

        return jsonify({
            'success': True,
            'deleted_count': deleted_count,
            'message': f'Successfully deleted {deleted_count} old campaigns. Keeping {len(existing_core)} core campaigns.'
        })

    except Exception as e:
        db.session.rollback()
        logger.exception("✗ CRITICAL ERROR during campaign deletion:")
        logger.error("=" * 80)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@lead_campaigns_bp.route('/cleanup/test-button', methods=['POST'])
@require_admin
def test_button():
    """Test endpoint to verify button works"""
    logger.info("Test button endpoint called!")
    return jsonify({
        'success': True,
        'message': 'Button works! Endpoint was called successfully.'
    })

@lead_campaigns_bp.route('/')
@require_admin
def index():
    """List all lead campaigns"""
    try:
        # Show only the newest 20 campaigns (one per business type from our new structure)
        campaigns = LeadCampaign.query.order_by(desc(LeadCampaign.created_at)).limit(20).all()

        logger.info(f"Found {len(campaigns)} campaigns")

        # Get stats for each campaign
        campaign_stats = []
        for campaign in campaigns:
            # Count emails from both legacy (LeadEmail) and new (LeadContactEmail) tables
            legacy_emails_sent = LeadEmail.query.join(Lead).filter(Lead.campaign_id == campaign.id).count()
            contact_emails_sent = LeadContactEmail.query.filter_by(campaign_id=campaign.id).count()
            total_emails_sent = legacy_emails_sent + contact_emails_sent

            legacy_emails_opened = LeadEmail.query.join(Lead).filter(
                Lead.campaign_id == campaign.id,
                LeadEmail.opened_at.isnot(None)
            ).count()
            contact_emails_opened = LeadContactEmail.query.filter(
                LeadContactEmail.campaign_id == campaign.id,
                LeadContactEmail.opened_at.isnot(None)
            ).count()
            total_emails_opened = legacy_emails_opened + contact_emails_opened

            leads_total = Lead.query.filter_by(campaign_id=campaign.id).count()
            leads_enriched = Lead.query.filter_by(campaign_id=campaign.id, enrichment_status='completed').count()
            sequence_count = EmailSequence.query.filter_by(campaign_id=campaign.id).count()

            # Get last activity timestamps
            last_scrape = Lead.query.filter_by(campaign_id=campaign.id).order_by(Lead.created_at.desc()).first()
            last_enrichment = Lead.query.filter_by(
                campaign_id=campaign.id,
                enrichment_status='completed'
            ).order_by(Lead.enriched_at.desc()).first()

            # Get last email sent from both tables
            last_legacy_email = LeadEmail.query.join(Lead).filter(
                Lead.campaign_id == campaign.id
            ).order_by(LeadEmail.sent_at.desc()).first()

            last_contact_email = LeadContactEmail.query.filter_by(
                campaign_id=campaign.id
            ).order_by(LeadContactEmail.sent_at.desc()).first()

            # Determine most recent email
            last_email_sent = None
            if last_legacy_email and last_contact_email:
                last_email_sent = last_legacy_email if last_legacy_email.sent_at > last_contact_email.sent_at else last_contact_email
            elif last_legacy_email:
                last_email_sent = last_legacy_email
            elif last_contact_email:
                last_email_sent = last_contact_email

            logger.info(f"Campaign '{campaign.name}' (ID:{campaign.id}): "
                       f"leads={leads_total}, enriched={leads_enriched}, "
                       f"emails={total_emails_sent} (legacy={legacy_emails_sent}, contact={contact_emails_sent}), "
                       f"opened={total_emails_opened}, sequences={sequence_count}")

            stats = {
                'campaign': campaign,
                'leads_total': leads_total,
                'leads_enriched': leads_enriched,
                'emails_sent': total_emails_sent,
                'emails_opened': total_emails_opened,
                'sequence_count': sequence_count,
                'last_scrape_at': last_scrape.created_at if last_scrape else None,
                'last_enrichment_at': last_enrichment.enriched_at if last_enrichment else None,
                'last_email_sent_at': last_email_sent.sent_at if last_email_sent else None,
            }
            campaign_stats.append(stats)

        # Get automation progress
        try:
            from app.services.lead_automation_service import LeadAutomationService
            service = LeadAutomationService()
            automation_progress = service.get_progress_report()
        except ImportError as e:
            logger.error(f"Error importing LeadAutomationService (likely missing dependencies): {e}")
            automation_progress = {
                'campaigns_created': 0,
                'leads_enriched': 0,
                'emails_sent': 0,
                'progress_percent': 0,
                'current_index': 0,
                'daily_stats': {'scrapes': 0, 'enrichments': 0, 'emails': 0},
                'error': 'Import error - install dependencies'
            }
        except Exception as e:
            logger.error(f"Error getting automation progress: {e}")
            automation_progress = {
                'campaigns_created': 0,
                'leads_enriched': 0,
                'emails_sent': 0,
                'progress_percent': 0,
                'current_index': 0,
                'daily_stats': {'scrapes': 0, 'enrichments': 0, 'emails': 0},
                'error': str(e)
            }

        return render_template('admin/lead_campaigns/index.html',
                             campaign_stats=campaign_stats,
                             automation_progress=automation_progress)

    except Exception as e:
        logger.exception(f"Critical error in lead campaigns index page: {e}")
        # Return error page with details
        return render_template('admin/error.html',
                             error_title="Lead Campaigns Page Error",
                             error_message=str(e),
                             error_details=f"Error type: {type(e).__name__}"), 500


@lead_campaigns_bp.route('/new', methods=['GET', 'POST'])
@require_admin
def new_campaign():
    """Create new lead campaign"""
    if request.method == 'GET':
        return render_template('admin/lead_campaigns/new.html')

    # Validate inputs
    industry_service = request.form.get('industry_service', '').strip()
    location = request.form.get('location', '').strip()

    # Validation checks
    errors = []

    if not industry_service or len(industry_service) < 3:
        errors.append('Service/Industry must be at least 3 characters (e.g., "plumber", "hvac repair")')

    if industry_service.lower() in ['all', 'all us', 'us', 'usa', 'united states']:
        errors.append('Service/Industry cannot be "All" or "US" - must be a specific service (e.g., "plumber", "hvac")')

    if not location or len(location) < 3:
        errors.append('Location must be at least 3 characters (e.g., "New York, NY")')

    if location.lower() in ['us', 'usa', 'united states', 'all']:
        errors.append('Location must be a specific city and state, not just "US" (e.g., "Dallas, TX")')

    if ',' not in location:
        errors.append('Location should include city and state separated by comma (e.g., "Austin, TX")')

    if errors:
        for error in errors:
            flash(error, 'error')
        return render_template('admin/lead_campaigns/new.html')

    # Create campaign
    campaign = LeadCampaign(
        name=request.form['name'],
        industry_service=industry_service,
        location=location,
        scrape_ads=request.form.get('scrape_ads') == 'on',
        scrape_maps=request.form.get('scrape_maps') == 'on',
        scrape_lsa=request.form.get('scrape_lsa') == 'on',
        scrape_organic=request.form.get('scrape_organic') == 'on',
        max_organic_results=int(request.form.get('max_organic_results', 5)),
        daily_email_limit=int(request.form.get('daily_email_limit', 250)),
        sequence_delay_days=int(request.form.get('sequence_delay_days', 3)),
        status='draft'
    )

    db.session.add(campaign)
    db.session.commit()

    flash(f'Campaign "{campaign.name}" created!', 'success')
    return redirect(url_for('lead_campaigns_bp.view_campaign', campaign_id=campaign.id))


@lead_campaigns_bp.route('/<int:campaign_id>')
@require_admin
def view_campaign(campaign_id: int):
    """View campaign details and leads"""
    try:
        campaign = LeadCampaign.query.get_or_404(campaign_id)

        # Get leads with pagination
        page = request.args.get('page', 1, type=int)
        per_page = 50

        leads_query = Lead.query.filter_by(campaign_id=campaign_id).order_by(desc(Lead.created_at))
        leads_pagination = leads_query.paginate(page=page, per_page=per_page, error_out=False)

        # Get sequences
        sequences = EmailSequence.query.filter_by(campaign_id=campaign_id).order_by(EmailSequence.step_number).all()

        return render_template(
            'admin/lead_campaigns/view.html',
            campaign=campaign,
            leads=leads_pagination.items,
            pagination=leads_pagination,
            sequences=sequences
        )
    except Exception as e:
        logger.exception(f"Error loading campaign {campaign_id} view: {e}")
        return render_template('admin/error.html',
                             error_title="Campaign View Error",
                             error_message=str(e),
                             error_details=f"Campaign ID: {campaign_id}"), 500


@lead_campaigns_bp.route('/<int:campaign_id>/edit', methods=['GET', 'POST'])
@require_admin
def edit_campaign(campaign_id: int):
    """Edit an existing campaign"""
    campaign = LeadCampaign.query.get_or_404(campaign_id)

    if request.method == 'GET':
        return render_template('admin/lead_campaigns/edit.html', campaign=campaign)

    # Validate inputs
    industry_service = request.form.get('industry_service', '').strip()
    location = request.form.get('location', '').strip()

    # Validation checks
    errors = []

    if not industry_service or len(industry_service) < 3:
        errors.append('Service/Industry must be at least 3 characters (e.g., "plumber", "hvac repair")')

    if industry_service.lower() in ['all', 'all us', 'us', 'usa', 'united states']:
        errors.append('Service/Industry cannot be "All" or "US" - must be a specific service (e.g., "plumber", "hvac")')

    if not location or len(location) < 3:
        errors.append('Location must be at least 3 characters (e.g., "New York, NY")')

    if location.lower() in ['us', 'usa', 'united states', 'all']:
        errors.append('Location must be a specific city and state, not just "US" (e.g., "Dallas, TX")')

    if ',' not in location:
        errors.append('Location should include city and state separated by comma (e.g., "Austin, TX")')

    if errors:
        for error in errors:
            flash(error, 'error')
        return render_template('admin/lead_campaigns/edit.html', campaign=campaign)

    # Update campaign
    campaign.name = request.form['name']
    campaign.industry_service = industry_service
    campaign.location = location
    campaign.scrape_ads = request.form.get('scrape_ads') == 'on'
    campaign.scrape_maps = request.form.get('scrape_maps') == 'on'
    campaign.scrape_lsa = request.form.get('scrape_lsa') == 'on'
    campaign.scrape_organic = request.form.get('scrape_organic') == 'on'
    campaign.max_organic_results = int(request.form.get('max_organic_results', 5))
    campaign.daily_email_limit = int(request.form.get('daily_email_limit', 250))
    campaign.sequence_delay_days = int(request.form.get('sequence_delay_days', 3))

    db.session.commit()

    flash(f'Campaign "{campaign.name}" updated!', 'success')
    return redirect(url_for('lead_campaigns_bp.view_campaign', campaign_id=campaign.id))


@lead_campaigns_bp.route('/<int:campaign_id>/start-scraping', methods=['POST'])
@require_admin
def start_scraping(campaign_id: int):
    """Start scraping for a campaign"""
    campaign = LeadCampaign.query.get_or_404(campaign_id)

    # Reset campaigns stuck in 'scraping' status for more than 5 minutes
    if campaign.status == 'scraping' and campaign.scraping_started_at:
        time_stuck = datetime.now() - campaign.scraping_started_at
        if time_stuck.total_seconds() > 300:  # 5 minutes
            logger.warning(f"Campaign {campaign_id} stuck in scraping for {time_stuck.total_seconds()}s, resetting to draft")
            campaign.status = 'draft'
            db.session.commit()

    if campaign.status not in ['draft', 'ready']:
        return jsonify({'success': False, 'error': 'Campaign is already running or completed'}), 400

    # Check if SerpAPI key is configured
    import os
    if not os.getenv('SERPAPI_API_KEY'):
        return jsonify({
            'success': False,
            'error': 'SERPAPI_API_KEY environment variable not configured. Please add it to your .env file and restart the app.'
        }), 400

    try:
        # Update status
        campaign.status = 'scraping'
        campaign.scraping_started_at = datetime.now()
        db.session.commit()

        # Run scraping (synchronous for now - should be background job)
        scraper = SerpAPIScraperService()

        query = f"{campaign.industry_service} {campaign.location}"
        results = scraper.scrape_campaign(
            query=query,
            location=campaign.location,
            scrape_ads=campaign.scrape_ads,
            scrape_maps=campaign.scrape_maps,
            scrape_lsa=campaign.scrape_lsa,
            scrape_organic=campaign.scrape_organic,
            max_organic=campaign.max_organic_results
        )

        # Save leads
        leads_created = 0

        # Map scraper source types (plural) to database enum values (singular)
        source_type_mapping = {
            'ads': 'ad',
            'maps': 'map',
            'lsa': 'lsa',
            'organic': 'organic'
        }

        for source_type, items in results.items():
            # Convert plural to singular for database enum
            db_source_type = source_type_mapping.get(source_type, source_type)

            for item in items:
                # Check if lead already exists (by company name + campaign)
                existing = Lead.query.filter_by(
                    campaign_id=campaign_id,
                    company_name=item['company_name']
                ).first()

                if existing:
                    continue

                lead = Lead(
                    campaign_id=campaign_id,
                    company_name=item['company_name'],
                    website=item.get('website'),
                    phone=item.get('phone'),
                    address=item.get('address'),
                    source_type=db_source_type,
                    source_url=item.get('source_url'),
                    serp_position=item.get('position'),
                    enrichment_status='pending',
                    email_status='pending',
                    extra_data=item.get('extra_data', {})
                )

                db.session.add(lead)
                leads_created += 1

        # Update campaign
        campaign.status = 'ready'
        campaign.scraping_completed_at = datetime.now()
        campaign.leads_scraped = leads_created
        db.session.commit()

        flash(f'Scraped {leads_created} leads!', 'success')
        return jsonify({'success': True, 'leads_created': leads_created})

    except Exception as e:
        logger.exception(f"Scraping error for campaign {campaign_id}: {e}")
        campaign.status = 'draft'
        db.session.commit()
        return jsonify({'success': False, 'error': str(e)}), 500


@lead_campaigns_bp.route('/<int:campaign_id>/enrich-leads', methods=['POST'])
@require_admin
def enrich_leads(campaign_id: int):
    """Enrich leads with contact information"""
    campaign = LeadCampaign.query.get_or_404(campaign_id)

    try:
        enrichment_service = LeadEnrichmentService()

        # Get pending leads
        leads = Lead.query.filter_by(
            campaign_id=campaign_id,
            enrichment_status='pending'
        ).limit(10).all()  # Limit to avoid timeout

        enriched_count = 0

        for lead in leads:
            lead.enrichment_status = 'in_progress'
            lead.enrichment_attempts += 1
            db.session.commit()

            try:
                result = enrichment_service.enrich_lead(lead.company_name, lead.website)

                lead.email_format = result['email_format']
                lead.decision_maker_name = result['decision_maker_name']
                lead.decision_maker_title = result['decision_maker_title']
                lead.decision_maker_email = result['decision_maker_email']
                lead.decision_maker_linkedin = result['decision_maker_linkedin']
                lead.enrichment_status = 'completed'
                lead.enriched_at = datetime.now()

                enriched_count += 1

            except Exception as e:
                logger.error(f"Error enriching lead {lead.id}: {e}")
                lead.enrichment_status = 'failed'

            db.session.commit()

        # Update campaign stats
        campaign.leads_enriched = Lead.query.filter_by(
            campaign_id=campaign_id,
            enrichment_status='completed'
        ).count()
        db.session.commit()

        flash(f'Enriched {enriched_count} leads!', 'success')
        return jsonify({'success': True, 'enriched_count': enriched_count})

    except Exception as e:
        logger.error(f"Enrichment error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ==================== Email Sequences ====================

@lead_campaigns_bp.route('/sequences', methods=['GET'])
@require_admin
def sequences_list():
    """List all email sequences across all campaigns"""
    # Get all sequences with campaign info
    sequences = EmailSequence.query.join(LeadCampaign).order_by(
        LeadCampaign.name, EmailSequence.step_number
    ).all()

    return render_template('admin/lead_campaigns/sequences_list.html', sequences=sequences)


@lead_campaigns_bp.route('/sequences/new', methods=['GET', 'POST'])
@require_admin
def sequences_new():
    """Create a new email sequence (select campaign first)"""
    if request.method == 'GET':
        # Get all campaigns
        campaigns = LeadCampaign.query.order_by(LeadCampaign.name).all()
        return render_template('admin/lead_campaigns/sequences_new.html', campaigns=campaigns)

    # Create sequence
    campaign_id = int(request.form['campaign_id'])
    campaign = LeadCampaign.query.get_or_404(campaign_id)

    # Get next step number for this campaign
    max_step = db.session.query(func.max(EmailSequence.step_number)).filter_by(campaign_id=campaign_id).scalar() or 0
    next_step = max_step + 1

    body_text = request.form.get('body_text', '')
    body_html = text_to_html(body_text)

    sequence = EmailSequence(
        campaign_id=campaign_id,
        step_number=next_step,
        name=request.form['name'],
        subject=request.form['subject'],
        body_html=body_html,
        body_text=body_text,
        delay_days=int(request.form.get('delay_days', 0)),
        is_active=request.form.get('is_active') == 'on'
    )

    db.session.add(sequence)
    db.session.commit()

    flash(f'Email sequence "{sequence.name}" created for campaign "{campaign.name}"!', 'success')
    return redirect(url_for('lead_campaigns_bp.sequences_list'))


@lead_campaigns_bp.route('/sequences/<int:sequence_id>/edit', methods=['GET', 'POST'])
@require_admin
def sequences_edit(sequence_id: int):
    """Edit an existing email sequence"""
    sequence = EmailSequence.query.get_or_404(sequence_id)

    if request.method == 'GET':
        campaigns = LeadCampaign.query.order_by(LeadCampaign.name).all()
        return render_template('admin/lead_campaigns/sequences_edit.html',
                             sequence=sequence, campaigns=campaigns)

    # Update sequence
    sequence.campaign_id = int(request.form['campaign_id'])
    sequence.name = request.form['name']
    sequence.subject = request.form['subject']
    sequence.step_number = int(request.form['step_number'])
    sequence.delay_days = int(request.form.get('delay_days', 0))
    sequence.is_active = request.form.get('is_active') == 'on'

    body_text = request.form.get('body_text', '')
    sequence.body_text = body_text
    sequence.body_html = text_to_html(body_text)

    db.session.commit()

    flash(f'Email sequence "{sequence.name}" updated!', 'success')
    return redirect(url_for('lead_campaigns_bp.sequences_list'))


@lead_campaigns_bp.route('/sequences/<int:sequence_id>/delete', methods=['POST'])
@require_admin
def sequences_delete(sequence_id: int):
    """Delete an email sequence"""
    sequence = EmailSequence.query.get_or_404(sequence_id)
    sequence_name = sequence.name

    db.session.delete(sequence)
    db.session.commit()

    flash(f'Email sequence "{sequence_name}" deleted!', 'success')
    return redirect(url_for('lead_campaigns_bp.sequences_list'))


@lead_campaigns_bp.route('/sequences/copy-campaign/<int:source_campaign_id>', methods=['GET', 'POST'])
@require_admin
def sequences_copy_campaign(source_campaign_id: int):
    """Copy all sequence steps from one campaign to another"""
    source_campaign = LeadCampaign.query.get_or_404(source_campaign_id)
    source_sequences = EmailSequence.query.filter_by(
        campaign_id=source_campaign_id
    ).order_by(EmailSequence.step_number).all()

    if not source_sequences:
        flash('This campaign has no email sequences to copy.', 'warning')
        return redirect(url_for('lead_campaigns_bp.sequences_list'))

    if request.method == 'GET':
        # Show form to select target campaign
        campaigns = LeadCampaign.query.filter(
            LeadCampaign.id != source_campaign_id
        ).order_by(LeadCampaign.name).all()
        return render_template('admin/lead_campaigns/sequences_copy.html',
                             source_campaign=source_campaign,
                             source_sequences=source_sequences,
                             campaigns=campaigns)

    # Copy all sequences to target campaign
    target_campaign_id = int(request.form['campaign_id'])
    target_campaign = LeadCampaign.query.get_or_404(target_campaign_id)

    # Get starting step number for target campaign
    max_step = db.session.query(func.max(EmailSequence.step_number)).filter_by(
        campaign_id=target_campaign_id
    ).scalar() or 0

    # Copy all sequences
    copied_count = 0
    for idx, source_seq in enumerate(source_sequences):
        new_sequence = EmailSequence(
            campaign_id=target_campaign_id,
            step_number=max_step + idx + 1,
            name=source_seq.name,
            subject=source_seq.subject,
            body_html=source_seq.body_html,
            body_text=source_seq.body_text,
            delay_days=source_seq.delay_days,
            is_active=source_seq.is_active
        )
        db.session.add(new_sequence)
        copied_count += 1

    db.session.commit()

    flash(f'Copied {copied_count} email steps from "{source_campaign.name}" to "{target_campaign.name}"!', 'success')
    return redirect(url_for('lead_campaigns_bp.sequences_list'))


@lead_campaigns_bp.route('/<int:campaign_id>/sequences/new', methods=['GET', 'POST'])
@require_admin
def new_sequence(campaign_id: int):
    """Create email sequence step"""
    campaign = LeadCampaign.query.get_or_404(campaign_id)

    if request.method == 'GET':
        # Get next step number
        max_step = db.session.query(func.max(EmailSequence.step_number)).filter_by(campaign_id=campaign_id).scalar() or 0
        next_step = max_step + 1

        return render_template('admin/lead_campaigns/new_sequence.html', campaign=campaign, next_step=next_step)

    # Create sequence
    body_text = request.form.get('body_text', '')
    body_html = text_to_html(body_text)  # Convert plain text to HTML

    sequence = EmailSequence(
        campaign_id=campaign_id,
        step_number=int(request.form['step_number']),
        name=request.form['name'],
        subject=request.form['subject'],
        body_html=body_html,
        body_text=body_text,
        delay_days=int(request.form.get('delay_days', 0)),
        is_active=True
    )

    db.session.add(sequence)
    db.session.commit()

    flash(f'Email sequence "{sequence.name}" created!', 'success')
    return redirect(url_for('lead_campaigns_bp.view_campaign', campaign_id=campaign_id))


@lead_campaigns_bp.route('/<int:campaign_id>/send-emails', methods=['POST'])
@require_admin
def send_emails(campaign_id: int):
    """Send emails to leads (respects daily limit)"""
    campaign = LeadCampaign.query.get_or_404(campaign_id)

    try:
        brevo = BrevoOutreachService()

        # Check daily limit
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        sent_today = LeadEmail.query.join(Lead).filter(
            Lead.campaign_id == campaign_id,
            LeadEmail.created_at >= today_start
        ).count()

        if sent_today >= campaign.daily_email_limit:
            return jsonify({
                'success': False,
                'error': f'Daily limit reached ({campaign.daily_email_limit})'
            }), 400

        remaining = campaign.daily_email_limit - sent_today

        # Get leads ready to send (enriched, have email, not sent yet)
        leads = Lead.query.filter_by(
            campaign_id=campaign_id,
            enrichment_status='completed',
            email_status='pending'
        ).filter(
            Lead.decision_maker_email.isnot(None)
        ).limit(min(remaining, 50)).all()  # Send max 50 at a time

        # Get first sequence step
        sequence = EmailSequence.query.filter_by(
            campaign_id=campaign_id,
            step_number=1,
            is_active=True
        ).first()

        if not sequence:
            return jsonify({'success': False, 'error': 'No email sequence configured'}), 400

        sent_count = 0

        for lead in leads:
            # Check unsubscribe list
            if EmailUnsubscribe.query.filter_by(email=lead.decision_maker_email).first():
                lead.email_status = 'unsubscribed'
                db.session.commit()
                continue

            # Personalize email
            variables = {
                'company_name': lead.company_name,
                'decision_maker_name': lead.decision_maker_name or 'there',
                'decision_maker_title': lead.decision_maker_title or '',
                'service_type': campaign.industry_service,
                'location': campaign.location,
            }

            subject = brevo.personalize_template(sequence.subject, variables)
            body_html = brevo.personalize_template(sequence.body_html, variables)

            # Send email
            result = brevo.send_email(
                to_email=lead.decision_maker_email,
                subject=subject,
                body_html=body_html,
                tags=[f'campaign-{campaign_id}', f'sequence-{sequence.id}'],
                custom_vars={'lead_id': lead.id, 'sequence_id': sequence.id}
            )

            if result.get('success'):
                # Record sent email
                email_sent = LeadEmail(
                    lead_id=lead.id,
                    sequence_id=sequence.id,
                    to_email=lead.decision_maker_email,
                    subject=subject,
                    body_html=body_html,
                    brevo_message_id=result.get('message_id'),
                    email_provider='brevo',
                    status='sent',
                    sent_at=datetime.now()
                )
                db.session.add(email_sent)

                # Update lead
                lead.email_status = 'sent'
                lead.current_sequence_step = 1
                lead.last_email_sent_at = datetime.now()

                # Set auto-delete for 30 days if no response
                lead.auto_delete_at = datetime.now() + timedelta(days=30)

                sent_count += 1
            else:
                logger.error(f"Failed to send to {lead.decision_maker_email}: {result.get('error')}")

            db.session.commit()

        # Update campaign stats
        campaign.emails_sent = LeadEmail.query.join(Lead).filter(Lead.campaign_id == campaign_id).count()
        campaign.sending_started_at = campaign.sending_started_at or datetime.now()
        db.session.commit()

        flash(f'Sent {sent_count} emails!', 'success')
        return jsonify({'success': True, 'sent_count': sent_count})

    except Exception as e:
        logger.error(f"Email sending error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ==================== Individual Operation Triggers ====================

@lead_campaigns_bp.route('/trigger-scraping', methods=['POST'])
@require_admin
def trigger_scraping():
    """
    Trigger scraping operation independently.
    Runs daily scraping up to configured limits.
    """
    try:
        from app.services.lead_automation_service import LeadAutomationService

        logger.info("Manual trigger: Starting scraping operation")
        service = LeadAutomationService()
        result = service.run_scraping()

        return jsonify({
            'success': True,
            'scraped': result['scraped'],
            'total_campaigns': result['total_campaigns'],
            'message': f"Scraped {result['scraped']} campaigns"
        })

    except Exception as e:
        logger.exception(f"Error triggering scraping: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@lead_campaigns_bp.route('/trigger-enrichment', methods=['POST'])
@require_admin
def trigger_enrichment():
    """
    Trigger enrichment operation independently.
    Enriches pending leads up to configured limits.
    """
    try:
        from app.services.lead_automation_service import LeadAutomationService

        logger.info("Manual trigger: Starting enrichment operation")
        service = LeadAutomationService()
        result = service.run_enrichment()

        return jsonify({
            'success': True,
            'enriched': result['enriched'],
            'total_enriched': result['total_enriched'],
            'message': f"Enriched {result['enriched']} leads"
        })

    except Exception as e:
        logger.exception(f"Error triggering enrichment: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@lead_campaigns_bp.route('/trigger-outreach', methods=['POST'])
@require_admin
def trigger_outreach():
    """
    Trigger email outreach operation independently.
    Sends emails to enriched leads up to configured limits.
    """
    try:
        from app.services.lead_automation_service import LeadAutomationService

        logger.info("Manual trigger: Starting email outreach operation")
        service = LeadAutomationService()
        result = service.run_email_outreach()

        return jsonify({
            'success': True,
            'sent': result['sent'],
            'total_emails': result['total_emails'],
            'message': f"Sent {result['sent']} emails"
        })

    except Exception as e:
        logger.exception(f"Error triggering outreach: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ==================== Bulk Actions ====================

def _save_bulk_stats(action_type: str, stats: dict):
    """Save bulk action statistics to file"""
    import os
    import json

    stats_file = os.getenv('BULK_STATS_FILE', 'bulk_action_stats.json')

    # Load existing stats
    if os.path.exists(stats_file):
        with open(stats_file, 'r') as f:
            all_stats = json.load(f)
    else:
        all_stats = {}

    # Add timestamp
    stats['completed_at'] = datetime.now().isoformat()

    # Save stats for this action type
    all_stats[action_type] = stats

    # Write back to file
    with open(stats_file, 'w') as f:
        json.dump(all_stats, f, indent=2)

    logger.info(f"Saved bulk stats for {action_type}")


def _get_bulk_stats():
    """Get bulk action statistics from file"""
    import os
    import json

    stats_file = os.getenv('BULK_STATS_FILE', 'bulk_action_stats.json')

    if not os.path.exists(stats_file):
        return {}

    with open(stats_file, 'r') as f:
        return json.load(f)


@lead_campaigns_bp.route('/bulk/stats', methods=['GET'])
@require_admin
def bulk_stats():
    """Get statistics for all bulk actions"""
    try:
        stats = _get_bulk_stats()

        # Add counts of pending work
        draft_campaigns = LeadCampaign.query.filter_by(status='draft').count()
        pending_enrichment = Lead.query.filter_by(enrichment_status='pending').count()
        ready_for_email = Lead.query.filter_by(
            enrichment_status='completed',
            email_status='pending'
        ).filter(Lead.decision_maker_email.isnot(None)).count()

        return jsonify({
            'success': True,
            'stats': stats,
            'pending': {
                'draft_campaigns': draft_campaigns,
                'pending_enrichment': pending_enrichment,
                'ready_for_email': ready_for_email
            }
        })

    except Exception as e:
        logger.exception(f"Error getting bulk stats: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@lead_campaigns_bp.route('/bulk/scrape-all', methods=['POST'])
@require_admin
def bulk_scrape_all():
    """Bulk scrape all campaigns that haven't been scraped yet (status='draft')"""
    try:
        import os

        # Check if SerpAPI key is configured
        if not os.getenv('SERPAPI_API_KEY'):
            return jsonify({
                'success': False,
                'error': 'SERPAPI_API_KEY not configured'
            }), 400

        # Get all draft campaigns (not yet scraped)
        draft_campaigns = LeadCampaign.query.filter_by(status='draft').limit(20).all()

        if not draft_campaigns:
            return jsonify({
                'success': True,
                'message': 'No draft campaigns to scrape',
                'scraped_count': 0
            })

        logger.info(f"Starting bulk scrape for {len(draft_campaigns)} draft campaigns")

        scraper = SerpAPIScraperService()
        total_leads_created = 0
        campaigns_scraped = 0

        for campaign in draft_campaigns:
            try:
                # Update status
                campaign.status = 'scraping'
                campaign.scraping_started_at = datetime.now()
                db.session.commit()

                # Scrape
                query = f"{campaign.industry_service} {campaign.location}"
                results = scraper.scrape_campaign(
                    query=query,
                    location=campaign.location,
                    scrape_ads=campaign.scrape_ads,
                    scrape_maps=campaign.scrape_maps,
                    scrape_lsa=campaign.scrape_lsa,
                    scrape_organic=campaign.scrape_organic,
                    max_organic=campaign.max_organic_results
                )

                # Save leads
                leads_created = 0
                source_type_mapping = {
                    'ads': 'ad',
                    'maps': 'map',
                    'lsa': 'lsa',
                    'organic': 'organic'
                }

                for source_type, items in results.items():
                    db_source_type = source_type_mapping.get(source_type, source_type)

                    for item in items:
                        # Check if lead already exists
                        existing = Lead.query.filter_by(
                            campaign_id=campaign.id,
                            company_name=item['company_name']
                        ).first()

                        if existing:
                            continue

                        lead = Lead(
                            campaign_id=campaign.id,
                            company_name=item['company_name'],
                            website=item.get('website'),
                            phone=item.get('phone'),
                            address=item.get('address'),
                            source_type=db_source_type,
                            source_url=item.get('source_url'),
                            serp_position=item.get('position'),
                            enrichment_status='pending',
                            email_status='pending',
                            extra_data=item.get('extra_data', {})
                        )

                        db.session.add(lead)
                        leads_created += 1

                # Update campaign
                campaign.status = 'ready'
                campaign.scraping_completed_at = datetime.now()
                campaign.leads_scraped = leads_created
                db.session.commit()

                total_leads_created += leads_created
                campaigns_scraped += 1

                logger.info(f"Scraped campaign {campaign.name}: {leads_created} leads")

            except Exception as e:
                logger.error(f"Error scraping campaign {campaign.id}: {e}")
                campaign.status = 'draft'
                db.session.commit()
                continue

        # Save stats
        _save_bulk_stats('scrape', {
            'campaigns_scraped': campaigns_scraped,
            'total_leads_created': total_leads_created,
            'success': True
        })

        return jsonify({
            'success': True,
            'campaigns_scraped': campaigns_scraped,
            'total_leads_created': total_leads_created,
            'message': f'Scraped {campaigns_scraped} campaigns, created {total_leads_created} leads',
            'completed_at': datetime.now().isoformat()
        })

    except Exception as e:
        logger.exception(f"Bulk scrape error: {e}")
        _save_bulk_stats('scrape', {
            'success': False,
            'error': str(e)
        })
        return jsonify({'success': False, 'error': str(e)}), 500


@lead_campaigns_bp.route('/bulk/enrich-all', methods=['POST'])
@require_admin
def bulk_enrich_all():
    """Bulk enrich all leads that are pending enrichment"""
    try:
        from app.services.lead_enrichment import LeadEnrichmentService

        # Get pending leads across all campaigns (limit to avoid timeout)
        pending_leads = Lead.query.filter_by(
            enrichment_status='pending'
        ).limit(100).all()

        if not pending_leads:
            return jsonify({
                'success': True,
                'message': 'No pending leads to enrich',
                'enriched_count': 0
            })

        logger.info(f"Starting bulk enrichment for {len(pending_leads)} pending leads")

        enrichment_service = LeadEnrichmentService()
        enriched_count = 0
        failed_count = 0

        for lead in pending_leads:
            try:
                lead.enrichment_status = 'in_progress'
                lead.enrichment_attempts += 1
                db.session.commit()

                result = enrichment_service.enrich_lead(lead.company_name, lead.website)

                lead.email_format = result.get('email_format')
                lead.decision_maker_name = result.get('decision_maker_name')
                lead.decision_maker_title = result.get('decision_maker_title')
                lead.decision_maker_email = result.get('decision_maker_email')
                lead.decision_maker_linkedin = result.get('decision_maker_linkedin')
                lead.enrichment_status = 'completed'
                lead.enriched_at = datetime.now()

                enriched_count += 1

            except Exception as e:
                logger.error(f"Error enriching lead {lead.id}: {e}")
                lead.enrichment_status = 'failed'
                failed_count += 1

            db.session.commit()

        # Update campaign stats
        for lead in pending_leads:
            if lead.campaign:
                lead.campaign.leads_enriched = Lead.query.filter_by(
                    campaign_id=lead.campaign_id,
                    enrichment_status='completed'
                ).count()
        db.session.commit()

        # Save stats
        _save_bulk_stats('enrich', {
            'enriched_count': enriched_count,
            'failed_count': failed_count,
            'success': True
        })

        return jsonify({
            'success': True,
            'enriched_count': enriched_count,
            'failed_count': failed_count,
            'message': f'Enriched {enriched_count} leads, {failed_count} failed',
            'completed_at': datetime.now().isoformat()
        })

    except Exception as e:
        logger.exception(f"Bulk enrichment error: {e}")
        _save_bulk_stats('enrich', {
            'success': False,
            'error': str(e)
        })
        return jsonify({'success': False, 'error': str(e)}), 500


@lead_campaigns_bp.route('/bulk/send-emails-all', methods=['POST'])
@require_admin
def bulk_send_emails_all():
    """Bulk send emails to all leads ready to be contacted"""
    try:
        # Initialize Brevo email service
        outreach_service = BrevoOutreachService()

        # Get leads ready to send (enriched, have email, not sent yet)
        # Limit to 100 to avoid timeout
        ready_leads = Lead.query.filter_by(
            enrichment_status='completed',
            email_status='pending'
        ).filter(
            Lead.decision_maker_email.isnot(None)
        ).limit(100).all()

        if not ready_leads:
            return jsonify({
                'success': True,
                'message': 'No leads ready to email',
                'sent_count': 0
            })

        logger.info(f"Starting bulk email send for {len(ready_leads)} ready leads")

        sent_count = 0
        failed_count = 0

        for lead in ready_leads:
            try:
                campaign = lead.campaign
                if not campaign:
                    continue

                # Check unsubscribe list
                if EmailUnsubscribe.query.filter_by(email=lead.decision_maker_email).first():
                    lead.email_status = 'unsubscribed'
                    db.session.commit()
                    continue

                # Get first sequence step for this campaign
                sequence = EmailSequence.query.filter_by(
                    campaign_id=campaign.id,
                    step_number=1,
                    is_active=True
                ).first()

                if not sequence:
                    logger.warning(f"No active sequence for campaign {campaign.id}")
                    continue

                # Personalize email
                variables = {
                    'company_name': lead.company_name,
                    'decision_maker_name': lead.decision_maker_name or 'there',
                    'decision_maker_title': lead.decision_maker_title or '',
                    'service_type': campaign.industry_service,
                    'location': campaign.location,
                }

                subject = outreach_service.personalize_template(sequence.subject, variables)
                body_html = outreach_service.personalize_template(sequence.body_html, variables)

                # Send email
                result = outreach_service.send_email(
                    to_email=lead.decision_maker_email,
                    subject=subject,
                    body_html=body_html,
                    tags=[f'campaign-{campaign.id}', f'sequence-{sequence.id}', 'bulk-send'],
                    custom_vars={'lead_id': lead.id, 'sequence_id': sequence.id}
                )

                if result.get('success'):
                    # Record sent email
                    email_sent = LeadEmail(
                        lead_id=lead.id,
                        sequence_id=sequence.id,
                        to_email=lead.decision_maker_email,
                        subject=subject,
                        body_html=body_html,
                        brevo_message_id=result.get('message_id'),
                        status='sent',
                        sent_at=datetime.now(),
                        email_provider='brevo'
                    )

                    db.session.add(email_sent)

                    # Update lead
                    lead.email_status = 'sent'
                    lead.current_sequence_step = 1
                    lead.last_email_sent_at = datetime.now()
                    lead.auto_delete_at = datetime.now() + timedelta(days=30)

                    sent_count += 1
                else:
                    logger.error(f"Failed to send to {lead.decision_maker_email}: {result.get('error')}")
                    failed_count += 1

                db.session.commit()

            except Exception as e:
                logger.error(f"Error sending email to lead {lead.id}: {e}")
                failed_count += 1
                continue

        # Update campaign stats
        campaigns_updated = set()
        for lead in ready_leads:
            if lead.campaign_id and lead.campaign_id not in campaigns_updated:
                campaign = LeadCampaign.query.get(lead.campaign_id)
                if campaign:
                    campaign.emails_sent = LeadEmail.query.join(Lead).filter(
                        Lead.campaign_id == campaign.id
                    ).count()
                    campaign.sending_started_at = campaign.sending_started_at or datetime.now()
                    campaigns_updated.add(lead.campaign_id)

        db.session.commit()

        # Save stats
        _save_bulk_stats('send_emails', {
            'sent_count': sent_count,
            'failed_count': failed_count,
            'success': True
        })

        return jsonify({
            'success': True,
            'sent_count': sent_count,
            'failed_count': failed_count,
            'message': f'Sent {sent_count} emails, {failed_count} failed',
            'completed_at': datetime.now().isoformat()
        })

    except Exception as e:
        logger.exception(f"Bulk email send error: {e}")
        _save_bulk_stats('send_emails', {
            'success': False,
            'error': str(e)
        })
        return jsonify({'success': False, 'error': str(e)}), 500


# ==================== Unsubscribe ====================

@lead_campaigns_bp.route('/unsubscribe', methods=['GET', 'POST'])
def unsubscribe():
    """Handle unsubscribe requests (no auth required - CAN-SPAM)"""
    email = request.args.get('email') or request.form.get('email')
    campaign_id = request.args.get('campaign') or request.form.get('campaign')

    if request.method == 'GET':
        return render_template('admin/lead_campaigns/unsubscribe.html', email=email, campaign_id=campaign_id)

    if not email:
        flash('Email address required', 'error')
        return redirect(url_for('lead_campaigns_bp.unsubscribe'))

    # Add to unsubscribe list
    existing = EmailUnsubscribe.query.filter_by(email=email).first()
    if not existing:
        unsub = EmailUnsubscribe(
            email=email,
            unsubscribed_from_campaign_id=campaign_id,
            reason=request.form.get('reason')
        )
        db.session.add(unsub)

    # Update any leads with this email
    Lead.query.filter_by(decision_maker_email=email).update({
        'email_status': 'unsubscribed',
        'unsubscribed_at': datetime.now()
    })

    db.session.commit()

    return render_template('admin/lead_campaigns/unsubscribed.html', email=email)


# ==================== ONE-CLICK CAMPAIGN AUTOMATION ====================

# In-memory job tracking (for production, use Redis or database)
automation_jobs = {}

@lead_campaigns_bp.route('/automation-center')
@require_admin
def automation_center():
    """One-click automation dashboard"""
    # Get core 20 campaigns (or create default template)
    core_campaigns = LeadCampaign.query.filter_by(is_core=True).order_by(LeadCampaign.id).limit(20).all()

    # If no core campaigns, get top 20 by activity
    if not core_campaigns or len(core_campaigns) < 20:
        core_campaigns = LeadCampaign.query.order_by(
            desc(LeadCampaign.updated_at)
        ).limit(20).all()

    # Get automation config
    from app.models_leads import CampaignAutomationConfig
    automation_config = CampaignAutomationConfig.query.first()

    # Get recent automation runs
    from app.models_leads import AutomationRun
    recent_runs = AutomationRun.query.order_by(
        desc(AutomationRun.started_at)
    ).limit(10).all()

    return render_template(
        'admin/lead_campaigns/automation_one_click.html',
        core_campaigns=core_campaigns,
        automation_config=automation_config,
        recent_runs=recent_runs
    )


@lead_campaigns_bp.route('/run-all-campaigns', methods=['POST'])
@require_admin
def run_all_campaigns():
    """
    One-click execution: Run scrape → enrich → email for all core campaigns
    Returns job_id for progress tracking
    """
    try:
        # Create job ID
        job_id = str(uuid.uuid4())

        # Initialize job tracking
        automation_jobs[job_id] = {
            'status': 'running',
            'started_at': datetime.now(),
            'campaigns_processed': 0,
            'campaigns_total': 20,
            'leads_scraped': 0,
            'leads_enriched': 0,
            'emails_sent': 0,
            'error_count': 0,
            'current_operation': 'Initializing...',
            'recent_logs': [],
            'errors': []
        }

        # Create automation run record
        from app.models_leads import AutomationRun
        automation_run = AutomationRun(
            job_id=job_id,
            trigger_type='manual',
            started_at=datetime.now(),
            status='running'
        )
        db.session.add(automation_run)
        db.session.commit()

        # Start background thread
        thread = Thread(target=run_automation_job, args=(job_id, automation_run.id))
        thread.daemon = True
        thread.start()

        return jsonify({
            'success': True,
            'job_id': job_id,
            'message': 'Automation started'
        })

    except Exception as e:
        logger.error(f"Error starting automation: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


def run_automation_job(job_id, automation_run_id):
    """Background job to run all campaigns"""
    from app import create_app
    from app.models_leads import AutomationRun

    # Create new app context for thread
    app = create_app()

    with app.app_context():
        try:
            job = automation_jobs[job_id]
            automation_run = AutomationRun.query.get(automation_run_id)

            # Get core campaigns
            campaigns = LeadCampaign.query.filter_by(is_core=True).order_by(LeadCampaign.id).limit(20).all()
            if not campaigns or len(campaigns) < 20:
                campaigns = LeadCampaign.query.order_by(desc(LeadCampaign.updated_at)).limit(20).all()

            job['campaigns_total'] = len(campaigns)

            # Initialize services (already imported at top)
            scraper = SerpAPIScraperService()
            enricher = LeadEnrichmentService()
            outreach = BrevoOutreachService()

            # Process each campaign
            for idx, campaign in enumerate(campaigns, 1):
                try:
                    job['current_operation'] = f"Processing campaign {idx}/20: {campaign.name}"
                    job['recent_logs'].append(f"[{idx}/20] {campaign.name}")

                    # STEP 1: Scrape (if needed)
                    if campaign.status == 'draft':
                        job['current_operation'] = f"[{idx}/20] Scraping: {campaign.name}"
                        job['recent_logs'].append(f"  → Scraping leads...")

                        # Scrape campaign
                        query = f"{campaign.industry_service} {campaign.location}"
                        results = scraper.scrape_campaign(
                            query=query,
                            location=campaign.location,
                            scrape_ads=campaign.scrape_ads,
                            scrape_maps=campaign.scrape_maps,
                            scrape_lsa=campaign.scrape_lsa,
                            scrape_organic=campaign.scrape_organic,
                            max_organic=campaign.max_organic_results
                        )

                        # Save leads from scraping results
                        source_type_mapping = {
                            'ads': 'ad',
                            'maps': 'map',
                            'lsa': 'lsa',
                            'organic': 'organic'
                        }

                        leads_created = 0
                        for source_type, items in results.items():
                            db_source_type = source_type_mapping.get(source_type, source_type)

                            for item in items:
                                # Check if lead already exists
                                existing = Lead.query.filter_by(
                                    campaign_id=campaign.id,
                                    company_name=item['company_name']
                                ).first()

                                if existing:
                                    continue

                                lead = Lead(
                                    campaign_id=campaign.id,
                                    company_name=item['company_name'],
                                    website=item.get('website'),
                                    phone=item.get('phone'),
                                    address=item.get('address'),
                                    source_type=db_source_type,
                                    source_url=item.get('source_url'),
                                    serp_position=item.get('position'),
                                    enrichment_status='pending',
                                    email_status='pending'
                                )
                                db.session.add(lead)
                                leads_created += 1

                        db.session.commit()

                        job['leads_scraped'] += leads_created
                        job['recent_logs'].append(f"  ✓ Scraped {leads_created} leads")

                        campaign.status = 'ready'
                        campaign.scraping_completed_at = datetime.now()
                        campaign.leads_scraped = (campaign.leads_scraped or 0) + leads_created
                        db.session.commit()

                    # STEP 2: Enrich (if needed)
                    pending_leads = Lead.query.filter_by(
                        campaign_id=campaign.id,
                        enrichment_status='pending'
                    ).limit(50).all()  # Limit to avoid timeout

                    if pending_leads:
                        job['current_operation'] = f"[{idx}/20] Enriching: {campaign.name} ({len(pending_leads)} leads)"
                        job['recent_logs'].append(f"  → Enriching {len(pending_leads)} leads...")

                        for lead in pending_leads:
                            result = enricher.enrich_lead(lead.id)
                            if result.get('success'):
                                job['leads_enriched'] += 1

                        job['recent_logs'].append(f"  ✓ Enriched {len(pending_leads)} leads")

                    # STEP 3: Send Emails (if needed)
                    ready_leads = Lead.query.filter_by(
                        campaign_id=campaign.id,
                        enrichment_status='completed',
                        email_status='pending'
                    ).filter(
                        Lead.decision_maker_email.isnot(None)
                    ).limit(campaign.daily_email_limit or 50).all()

                    if ready_leads:
                        job['current_operation'] = f"[{idx}/20] Sending emails: {campaign.name} ({len(ready_leads)} leads)"
                        job['recent_logs'].append(f"  → Sending {len(ready_leads)} emails...")

                        for lead in ready_leads:
                            result = outreach.send_initial_email(lead.id, campaign.id)
                            if result.get('success'):
                                job['emails_sent'] += 1

                        job['recent_logs'].append(f"  ✓ Sent {len(ready_leads)} emails")

                    # Update campaign automation timestamp
                    campaign.last_automation_run = datetime.now()
                    db.session.commit()

                    job['campaigns_processed'] += 1

                except Exception as e:
                    logger.error(f"Error processing campaign {campaign.id}: {e}")
                    job['error_count'] += 1
                    job['errors'].append(f"Campaign {campaign.name}: {str(e)}")
                    job['recent_logs'].append(f"  ✗ Error: {str(e)}")

            # Mark job as completed
            job['status'] = 'completed'
            job['current_operation'] = 'Completed!'
            job['completed_at'] = datetime.now()

            # Update automation run
            automation_run.status = 'completed'
            automation_run.completed_at = datetime.now()
            automation_run.campaigns_processed = job['campaigns_processed']
            automation_run.leads_scraped = job['leads_scraped']
            automation_run.leads_enriched = job['leads_enriched']
            automation_run.emails_sent = job['emails_sent']
            automation_run.error_count = job['error_count']
            automation_run.duration_minutes = int((datetime.now() - automation_run.started_at).total_seconds() / 60)
            db.session.commit()

        except Exception as e:
            logger.error(f"Fatal error in automation job: {e}")
            job['status'] = 'failed'
            job['error_count'] += 1
            job['errors'].append(f"Fatal error: {str(e)}")

            if automation_run:
                automation_run.status = 'failed'
                automation_run.error_message = str(e)
                db.session.commit()


@lead_campaigns_bp.route('/automation-progress/<job_id>')
@require_admin
def automation_progress(job_id):
    """Get automation job progress"""
    job = automation_jobs.get(job_id)

    if not job:
        return jsonify({'success': False, 'error': 'Job not found'}), 404

    # Get recent logs (last 5 entries)
    recent_logs = job.get('recent_logs', [])[-5:]

    return jsonify({
        'success': True,
        'job_id': job_id,
        'status': job['status'],
        'campaigns_processed': job['campaigns_processed'],
        'campaigns_total': job['campaigns_total'],
        'leads_scraped': job['leads_scraped'],
        'leads_enriched': job['leads_enriched'],
        'emails_sent': job['emails_sent'],
        'error_count': job['error_count'],
        'current_operation': job['current_operation'],
        'recent_logs': recent_logs,
        'duration_minutes': int((datetime.now() - job['started_at']).total_seconds() / 60) if job.get('started_at') else 0
    })


@lead_campaigns_bp.route('/save-automation-schedule', methods=['POST'])
@require_admin
def save_automation_schedule():
    """Save scheduling configuration"""
    try:
        data = request.get_json()

        from app.models_leads import CampaignAutomationConfig
        config = CampaignAutomationConfig.query.first()

        if not config:
            config = CampaignAutomationConfig()
            db.session.add(config)

        config.enabled = data.get('enabled', False)
        config.run_time = data.get('run_time', '09:00')
        config.run_days = data.get('run_days', [0, 1, 2, 3, 4])  # Mon-Fri
        config.daily_email_limit = data.get('daily_email_limit', 250)
        config.skip_weekends = data.get('skip_weekends', True)
        config.updated_at = datetime.now()

        # Calculate next run time
        config.next_run_at = calculate_next_run_time(config)

        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Schedule saved',
            'next_run_at': config.next_run_at.isoformat() if config.next_run_at else None
        })

    except Exception as e:
        logger.error(f"Error saving schedule: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@lead_campaigns_bp.route('/test-schedule', methods=['POST'])
@require_admin
def test_schedule():
    """Test scheduling configuration"""
    try:
        from app.models_leads import CampaignAutomationConfig
        config = CampaignAutomationConfig.query.first()

        if not config or not config.enabled:
            return jsonify({
                'success': False,
                'error': 'Scheduling not enabled'
            })

        next_run = calculate_next_run_time(config)

        return jsonify({
            'success': True,
            'next_run_time': next_run.strftime('%Y-%m-%d %I:%M %p') if next_run else 'Not scheduled',
            'run_time': config.run_time,
            'run_days': config.run_days,
            'skip_weekends': config.skip_weekends
        })

    except Exception as e:
        logger.error(f"Error testing schedule: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


def calculate_next_run_time(config):
    """Calculate next scheduled run time based on config"""
    from datetime import time as dt_time

    if not config or not config.enabled:
        return None

    # Parse run time
    hour, minute = map(int, config.run_time.split(':'))
    run_time = dt_time(hour, minute)

    # Start from tomorrow
    next_run = datetime.combine(datetime.now().date() + timedelta(days=1), run_time)

    # Find next valid day
    max_attempts = 14  # Check up to 2 weeks ahead
    attempts = 0

    while attempts < max_attempts:
        # Check if day of week is enabled (0=Monday, 6=Sunday)
        day_of_week = next_run.weekday()

        # Check weekend skip
        is_weekend = day_of_week >= 5  # Saturday or Sunday
        if config.skip_weekends and is_weekend:
            next_run += timedelta(days=1)
            attempts += 1
            continue

        # Check if day is in enabled days
        if config.run_days and day_of_week in config.run_days:
            return next_run

        next_run += timedelta(days=1)
        attempts += 1

    return None  # No valid run time found
