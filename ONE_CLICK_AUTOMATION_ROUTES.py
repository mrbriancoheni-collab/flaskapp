# Add these routes to the END of /flaskapp/app/admin/lead_campaigns_routes.py

# ==================== ONE-CLICK CAMPAIGN AUTOMATION ====================

import uuid
from threading import Thread

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

            # Initialize services
            from app.services.serpapi_scraper import SerpAPIScraperService
            from app.services.lead_enrichment import LeadEnrichmentService
            from app.services.brevo_outreach import BrevoOutreachService

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

                        results = scraper.scrape_campaign(campaign.id)
                        if results.get('success'):
                            scraped_count = results.get('total_leads_created', 0)
                            job['leads_scraped'] += scraped_count
                            job['recent_logs'].append(f"  ✓ Scraped {scraped_count} leads")

                            campaign.status = 'ready'
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


# ==================== MODELS NEEDED ====================
# Add these to app/models_leads.py:

"""
class CampaignAutomationConfig(db.Model):
    '''Configuration for automated campaign execution'''
    __tablename__ = "campaign_automation_config"

    id = db.Column(Integer, primary_key=True)
    enabled = db.Column(Boolean, default=False)
    run_time = db.Column(String(5), default='09:00')  # HH:MM format
    run_days = db.Column(JSONType, nullable=True)  # [0,1,2,3,4] for Mon-Fri
    daily_email_limit = db.Column(Integer, default=250)
    skip_weekends = db.Column(Boolean, default=True)
    next_run_at = db.Column(DateTime, nullable=True)
    last_run_at = db.Column(DateTime, nullable=True)
    created_at = db.Column(DateTime, server_default=func.now())
    updated_at = db.Column(DateTime, server_default=func.now(), onupdate=func.now())


class AutomationRun(db.Model):
    '''Track automation execution history'''
    __tablename__ = "automation_runs"

    id = db.Column(Integer, primary_key=True)
    job_id = db.Column(String(36), unique=True, index=True)
    trigger_type = db.Column(String(20))  # 'manual' or 'scheduled'
    status = db.Column(String(20))  # 'running', 'completed', 'failed'
    started_at = db.Column(DateTime, nullable=False)
    completed_at = db.Column(DateTime, nullable=True)
    duration_minutes = db.Column(Integer, nullable=True)
    campaigns_processed = db.Column(Integer, default=0)
    leads_scraped = db.Column(Integer, default=0)
    leads_enriched = db.Column(Integer, default=0)
    emails_sent = db.Column(Integer, default=0)
    error_count = db.Column(Integer, default=0)
    error_message = db.Column(Text, nullable=True)


# Also add this column to LeadCampaign model:
# is_core = db.Column(Boolean, default=False)  # Flag for core 20 campaigns
# last_automation_run = db.Column(DateTime, nullable=True)  # Last automation run time
"""
