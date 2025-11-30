# app/admin/lead_campaigns_routes.py
"""
Admin routes for Lead Generation Campaigns

Manage campaigns, view leads, send emails
"""
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from sqlalchemy import desc, func
import logging

from app.extensions import db
from app.auth.decorators import require_admin_cloaked as require_admin
from app.models_leads import LeadCampaign, Lead, EmailSequence, EmailSent, EmailUnsubscribe
from app.services.serpapi_scraper import SerpAPIScraperService
from app.services.lead_enrichment import LeadEnrichmentService
from app.services.mailgun_outreach import MailgunOutreachService

logger = logging.getLogger(__name__)

lead_campaigns_bp = Blueprint('lead_campaigns_bp', __name__, url_prefix='/admin/lead-campaigns')


# ==================== Campaign Management ====================

@lead_campaigns_bp.route('/')
@require_admin
def index():
    """List all lead campaigns"""
    campaigns = LeadCampaign.query.order_by(desc(LeadCampaign.created_at)).all()

    # Get stats for each campaign
    campaign_stats = []
    for campaign in campaigns:
        stats = {
            'campaign': campaign,
            'leads_total': Lead.query.filter_by(campaign_id=campaign.id).count(),
            'leads_enriched': Lead.query.filter_by(campaign_id=campaign.id, enrichment_status='completed').count(),
            'emails_sent': EmailSent.query.join(Lead).filter(Lead.campaign_id == campaign.id).count(),
            'emails_opened': EmailSent.query.join(Lead).filter(
                Lead.campaign_id == campaign.id,
                EmailSent.opened_at.isnot(None)
            ).count(),
        }
        campaign_stats.append(stats)

    return render_template('admin/lead_campaigns/index.html', campaign_stats=campaign_stats)


@lead_campaigns_bp.route('/new', methods=['GET', 'POST'])
@require_admin
def new_campaign():
    """Create new lead campaign"""
    if request.method == 'GET':
        return render_template('admin/lead_campaigns/new.html')

    # Create campaign
    campaign = LeadCampaign(
        name=request.form['name'],
        industry_service=request.form['industry_service'],
        location=request.form['location'],
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


@lead_campaigns_bp.route('/<int:campaign_id>/start-scraping', methods=['POST'])
@require_admin
def start_scraping(campaign_id: int):
    """Start scraping for a campaign"""
    campaign = LeadCampaign.query.get_or_404(campaign_id)

    if campaign.status not in ['draft', 'ready']:
        return jsonify({'success': False, 'error': 'Campaign is already running or completed'}), 400

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

        for source_type, items in results.items():
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
                    source_type=source_type,
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
        logger.error(f"Scraping error: {e}")
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
    sequence = EmailSequence(
        campaign_id=campaign_id,
        step_number=int(request.form['step_number']),
        name=request.form['name'],
        subject=request.form['subject'],
        body_html=request.form['body_html'],
        body_text=request.form.get('body_text'),
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
        mailgun = MailgunOutreachService()

        # Check daily limit
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        sent_today = EmailSent.query.join(Lead).filter(
            Lead.campaign_id == campaign_id,
            EmailSent.created_at >= today_start
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

            subject = mailgun.personalize_template(sequence.subject, variables)
            body_html = mailgun.personalize_template(sequence.body_html, variables)

            # Add unsubscribe link
            unsubscribe_url = mailgun.get_unsubscribe_url(lead.decision_maker_email, campaign_id)
            variables['unsubscribe_url'] = unsubscribe_url
            body_html = mailgun.add_unsubscribe_footer(body_html, unsubscribe_url)

            # Send email
            result = mailgun.send_email(
                to_email=lead.decision_maker_email,
                subject=subject,
                body_html=body_html,
                tags=[f'campaign-{campaign_id}', f'sequence-{sequence.id}'],
                custom_vars={'lead_id': lead.id, 'sequence_id': sequence.id}
            )

            if result['success']:
                # Record sent email
                email_sent = EmailSent(
                    lead_id=lead.id,
                    sequence_id=sequence.id,
                    to_email=lead.decision_maker_email,
                    subject=subject,
                    body_html=body_html,
                    mailgun_message_id=result.get('message_id'),
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
        campaign.emails_sent = EmailSent.query.join(Lead).filter(Lead.campaign_id == campaign_id).count()
        campaign.sending_started_at = campaign.sending_started_at or datetime.now()
        db.session.commit()

        flash(f'Sent {sent_count} emails!', 'success')
        return jsonify({'success': True, 'sent_count': sent_count})

    except Exception as e:
        logger.error(f"Email sending error: {e}")
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
