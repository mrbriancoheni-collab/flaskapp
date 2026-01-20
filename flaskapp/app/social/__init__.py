# app/social/__init__.py
"""
Social Media Ad Composer Routes

AI-powered ad creative generation for social media platforms
"""
from flask import Blueprint, render_template, request, jsonify, session
from flask_login import login_required, current_user
import logging

from app.extensions import db
from app.models_social import AdCreative, AdTemplate, AdGenerationJob, AdAnalyticsEvent
from app.services.ad_generation_service import AdGenerationService
from app.services.social_export_service import SocialExportService

logger = logging.getLogger(__name__)

social_bp = Blueprint(
    "social_bp",
    __name__,
    url_prefix="/social",
    template_folder="../../templates"
)


@social_bp.route("/ad-composer", methods=["GET"])
@login_required
def ad_composer():
    """Main ad composer interface"""
    # Get user's recent creatives
    recent_creatives = AdCreative.query.filter_by(
        user_id=current_user.id
    ).order_by(AdCreative.created_at.desc()).limit(10).all()

    # Get available templates
    templates = AdTemplate.query.filter_by(is_active=True).limit(12).all()

    return render_template(
        "social/ad_composer.html",
        recent_creatives=recent_creatives,
        templates=templates
    )


@social_bp.route("/api/generate-from-website", methods=["POST"])
@login_required
def generate_from_website():
    """Generate ad creative from website URL"""
    data = request.get_json()

    website_url = data.get('website_url')
    platform = data.get('platform', 'facebook')
    objective = data.get('objective', 'leads')
    industry = data.get('industry')
    style = data.get('style', 'professional')
    image_variations = data.get('image_variations', 1)  # 1-3 variations
    image_size = data.get('image_size', 'square')  # square, story, banner

    if not website_url:
        return jsonify({'success': False, 'error': 'Website URL required'}), 400

    try:
        service = AdGenerationService()

        # Generate full creative
        result = service.generate_full_creative(
            website_url=website_url,
            platform=platform,
            objective=objective,
            industry=industry,
            style_preference=style,
            image_variations=image_variations,
            image_size=image_size
        )

        if not result.get('success'):
            return jsonify(result), 400

        # Save to database (primary variation)
        creative = AdCreative(
            user_id=current_user.id,
            account_id=current_user.account_id if hasattr(current_user, 'account_id') else None,
            name=f"Generated from {website_url}",
            platform=platform,
            image_url=result.get('image_url'),
            image_prompt=result.get('image_prompt'),
            headline=result.get('headline'),
            primary_text=result.get('primary_text'),
            description=result.get('description'),
            call_to_action=result.get('call_to_action'),
            generation_method='ai_website',
            source_url=website_url,
            image_model=result.get('image_model'),
            copy_model=result.get('copy_model'),
            industry=industry,
            ad_objective=objective,
            status='draft'
        )

        db.session.add(creative)
        db.session.commit()

        # Log analytics event
        try:
            analytics_event = AdAnalyticsEvent(
                user_id=current_user.id,
                account_id=current_user.account_id if hasattr(current_user, 'account_id') else None,
                creative_id=creative.id,
                event_type='ad_generated',
                platform=platform,
                industry=industry,
                generation_method='website',
                image_count=image_variations,
                ai_cost=round((image_variations * 0.08) + 0.01, 2),  # DALL-E 3 HD + Claude/GPT
                session_id=session.get('session_id')
            )
            db.session.add(analytics_event)
            db.session.commit()
        except Exception as e:
            logger.error(f"Error logging analytics event: {e}")
            # Don't fail the request if analytics logging fails
            db.session.rollback()

        # Generate performance prediction
        performance_prediction = service.predict_performance(
            creative={
                'headline': creative.headline,
                'primary_text': creative.primary_text,
                'description': creative.description,
                'call_to_action': creative.call_to_action
            },
            platform=platform,
            industry=industry
        )

        response_data = {
            'success': True,
            'creative_id': creative.id,
            'creative': {
                'id': creative.id,
                'image_url': creative.image_url,
                'headline': creative.headline,
                'primary_text': creative.primary_text,
                'description': creative.description,
                'call_to_action': creative.call_to_action
            }
        }

        # Include image variations if generated
        if result.get('image_variations'):
            response_data['image_variations'] = result['image_variations']

        # Include performance prediction
        if performance_prediction.get('success'):
            response_data['performance_prediction'] = {
                'predicted_ctr': f"{performance_prediction['predicted_ctr']}%",
                'engagement_score': performance_prediction['engagement_score'],
                'quality_score': performance_prediction['quality_score'],
                'recommendations': performance_prediction['recommendations']
            }

            # Update analytics event with performance metrics
            try:
                analytics_event.predicted_ctr = performance_prediction['predicted_ctr']
                analytics_event.quality_score = performance_prediction['quality_score']
                analytics_event.engagement_score = performance_prediction['engagement_score']
                db.session.commit()
            except:
                pass

        return jsonify(response_data)

    except Exception as e:
        logger.error(f"Error generating from website: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@social_bp.route("/api/generate-copy", methods=["POST"])
@login_required
def generate_copy():
    """Generate ad copy only"""
    data = request.get_json()

    business_name = data.get('business_name')
    services = data.get('services', [])
    platform = data.get('platform', 'facebook')
    objective = data.get('objective', 'leads')
    tone = data.get('tone', 'professional')

    if not business_name:
        return jsonify({'success': False, 'error': 'Business name required'}), 400

    try:
        service = AdGenerationService()

        business_context = {
            'business_name': business_name,
            'services': services if isinstance(services, list) else [services],
            'industry': data.get('industry')
        }

        result = service.generate_ad_copy(
            business_context=business_context,
            platform=platform,
            objective=objective,
            tone=tone
        )

        return jsonify(result)

    except Exception as e:
        logger.error(f"Error generating copy: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@social_bp.route("/api/generate-image", methods=["POST"])
@login_required
def generate_image():
    """Generate ad image only"""
    data = request.get_json()

    prompt = data.get('prompt')
    style = data.get('style', 'vivid')
    size = data.get('size', '1024x1024')
    variations = data.get('variations', 1)

    if not prompt:
        return jsonify({'success': False, 'error': 'Image prompt required'}), 400

    try:
        service = AdGenerationService()
        result = service.generate_image(
            prompt=prompt,
            style=style,
            size=size,
            variations=variations
        )
        return jsonify(result)

    except Exception as e:
        logger.error(f"Error generating image: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@social_bp.route("/api/save-creative", methods=["POST"])
@login_required
def save_creative():
    """Save or update a creative"""
    data = request.get_json()

    creative_id = data.get('id')

    if creative_id:
        # Update existing
        creative = AdCreative.query.get(creative_id)
        if not creative or creative.user_id != current_user.id:
            return jsonify({'success': False, 'error': 'Creative not found'}), 404
    else:
        # Create new
        creative = AdCreative(
            user_id=current_user.id,
            account_id=current_user.account_id if hasattr(current_user, 'account_id') else None,
            generation_method='manual'
        )
        db.session.add(creative)

    # Update fields
    creative.name = data.get('name', creative.name)
    creative.platform = data.get('platform', creative.platform)
    creative.headline = data.get('headline')
    creative.primary_text = data.get('primary_text')
    creative.description = data.get('description')
    creative.call_to_action = data.get('call_to_action')
    creative.image_url = data.get('image_url')
    creative.status = data.get('status', 'draft')

    db.session.commit()

    return jsonify({
        'success': True,
        'creative_id': creative.id
    })


@social_bp.route("/api/creatives", methods=["GET"])
@login_required
def list_creatives():
    """List user's ad creatives"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    platform = request.args.get('platform')
    status = request.args.get('status')

    query = AdCreative.query.filter_by(user_id=current_user.id)

    if platform:
        query = query.filter_by(platform=platform)
    if status:
        query = query.filter_by(status=status)

    creatives = query.order_by(AdCreative.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return jsonify({
        'success': True,
        'creatives': [{
            'id': c.id,
            'name': c.name,
            'platform': c.platform,
            'headline': c.headline,
            'image_url': c.image_url,
            'status': c.status,
            'created_at': c.created_at.isoformat()
        } for c in creatives.items],
        'total': creatives.total,
        'pages': creatives.pages,
        'current_page': creatives.page
    })


@social_bp.route("/api/creative/<int:creative_id>", methods=["GET"])
@login_required
def get_creative(creative_id):
    """Get single creative details"""
    creative = AdCreative.query.get(creative_id)

    if not creative or creative.user_id != current_user.id:
        return jsonify({'success': False, 'error': 'Creative not found'}), 404

    return jsonify({
        'success': True,
        'creative': {
            'id': creative.id,
            'name': creative.name,
            'platform': creative.platform,
            'headline': creative.headline,
            'primary_text': creative.primary_text,
            'description': creative.description,
            'call_to_action': creative.call_to_action,
            'image_url': creative.image_url,
            'image_prompt': creative.image_prompt,
            'status': creative.status,
            'generation_method': creative.generation_method,
            'industry': creative.industry,
            'created_at': creative.created_at.isoformat()
        }
    })


@social_bp.route("/api/creative/<int:creative_id>", methods=["DELETE"])
@login_required
def delete_creative(creative_id):
    """Delete a creative"""
    creative = AdCreative.query.get(creative_id)

    if not creative or creative.user_id != current_user.id:
        return jsonify({'success': False, 'error': 'Creative not found'}), 404

    db.session.delete(creative)
    db.session.commit()

    return jsonify({'success': True})


@social_bp.route("/api/analytics/track", methods=["POST"])
@login_required
def track_analytics_event():
    """Track analytics event from frontend"""
    data = request.get_json()

    event_type = data.get('event_type')
    creative_id = data.get('creative_id')

    if not event_type:
        return jsonify({'success': False, 'error': 'event_type required'}), 400

    # Validate event_type
    valid_events = [
        'ad_generated', 'creative_saved', 'image_downloaded',
        'creative_exported', 'creative_viewed', 'creative_edited', 'variation_created'
    ]
    if event_type not in valid_events:
        return jsonify({'success': False, 'error': 'Invalid event_type'}), 400

    try:
        # Get creative if provided
        creative = None
        if creative_id:
            creative = AdCreative.query.get(creative_id)
            if not creative or creative.user_id != current_user.id:
                return jsonify({'success': False, 'error': 'Creative not found'}), 404

        # Create analytics event
        event = AdAnalyticsEvent(
            user_id=current_user.id,
            account_id=current_user.account_id if hasattr(current_user, 'account_id') else None,
            creative_id=creative_id,
            event_type=event_type,
            platform=data.get('platform') or (creative.platform if creative else None),
            industry=data.get('industry') or (creative.industry if creative else None),
            generation_method=data.get('generation_method'),
            image_count=data.get('image_count', 0),
            ai_cost=data.get('ai_cost'),
            event_data=data.get('event_data'),
            session_id=session.get('session_id')
        )

        db.session.add(event)
        db.session.commit()

        return jsonify({'success': True, 'event_id': event.id})

    except Exception as e:
        logger.error(f"Error tracking analytics event: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@social_bp.route("/api/analytics/dashboard", methods=["GET"])
@login_required
def analytics_dashboard():
    """Get analytics dashboard data for user's ad creatives"""
    # Date range filter
    days = request.args.get('days', 30, type=int)
    from_date = datetime.utcnow() - __import__('datetime').timedelta(days=days)

    # Get user's analytics events
    events = AdAnalyticsEvent.query.filter(
        AdAnalyticsEvent.user_id == current_user.id,
        AdAnalyticsEvent.created_at >= from_date
    ).all()

    # Aggregate statistics
    total_generated = len([e for e in events if e.event_type == 'ad_generated'])
    total_saved = len([e for e in events if e.event_type == 'creative_saved'])
    total_downloaded = len([e for e in events if e.event_type == 'image_downloaded'])
    total_exported = len([e for e in events if e.event_type == 'creative_exported'])

    total_cost = sum([e.ai_cost for e in events if e.ai_cost])
    avg_quality_score = sum([e.quality_score for e in events if e.quality_score]) / max(1, len([e for e in events if e.quality_score]))
    avg_predicted_ctr = sum([e.predicted_ctr for e in events if e.predicted_ctr]) / max(1, len([e for e in events if e.predicted_ctr]))

    # Platform breakdown
    platform_counts = {}
    for event in events:
        if event.platform:
            platform_counts[event.platform] = platform_counts.get(event.platform, 0) + 1

    # Industry breakdown
    industry_counts = {}
    for event in events:
        if event.industry:
            industry_counts[event.industry] = industry_counts.get(event.industry, 0) + 1

    # Event timeline (last 30 days)
    timeline = []
    for i in range(days):
        date = (datetime.utcnow() - __import__('datetime').timedelta(days=days-i-1)).date()
        day_events = [e for e in events if e.created_at.date() == date]
        timeline.append({
            'date': date.isoformat(),
            'ad_generated': len([e for e in day_events if e.event_type == 'ad_generated']),
            'creative_saved': len([e for e in day_events if e.event_type == 'creative_saved']),
            'image_downloaded': len([e for e in day_events if e.event_type == 'image_downloaded'])
        })

    return jsonify({
        'success': True,
        'summary': {
            'total_generated': total_generated,
            'total_saved': total_saved,
            'total_downloaded': total_downloaded,
            'total_exported': total_exported,
            'total_cost': round(total_cost, 2),
            'avg_quality_score': round(avg_quality_score, 1),
            'avg_predicted_ctr': round(avg_predicted_ctr, 2)
        },
        'platform_breakdown': platform_counts,
        'industry_breakdown': industry_counts,
        'timeline': timeline,
        'period_days': days
    })


# ==================== EXPORT / OAUTH ENDPOINTS ====================

@social_bp.route("/api/export/facebook/oauth-url", methods=["GET"])
@login_required
def get_facebook_oauth_url():
    """Get Facebook OAuth authorization URL"""
    try:
        service = SocialExportService()

        # Build redirect URI (must match Facebook App settings)
        redirect_uri = request.args.get('redirect_uri') or \
                      request.url_root.rstrip('/') + '/social/api/export/facebook/callback'

        # Generate state parameter for security (store in session)
        import secrets
        state = secrets.token_urlsafe(32)
        session['fb_oauth_state'] = state

        oauth_url = service.get_facebook_oauth_url(
            redirect_uri=redirect_uri,
            state=state
        )

        return jsonify({
            'success': True,
            'oauth_url': oauth_url,
            'redirect_uri': redirect_uri
        })

    except Exception as e:
        logger.error(f"Error generating OAuth URL: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@social_bp.route("/api/export/facebook/callback", methods=["GET"])
@login_required
def facebook_oauth_callback():
    """Handle Facebook OAuth callback"""
    code = request.args.get('code')
    state = request.args.get('state')
    error = request.args.get('error')

    if error:
        return jsonify({'success': False, 'error': error}), 400

    if not code:
        return jsonify({'success': False, 'error': 'No authorization code provided'}), 400

    # Verify state parameter
    stored_state = session.pop('fb_oauth_state', None)
    if not stored_state or stored_state != state:
        return jsonify({'success': False, 'error': 'Invalid state parameter'}), 400

    try:
        service = SocialExportService()

        redirect_uri = request.args.get('redirect_uri') or \
                      request.url_root.rstrip('/') + '/social/api/export/facebook/callback'

        # Exchange code for access token
        token_result = service.exchange_code_for_token(code, redirect_uri)

        if not token_result.get('success'):
            return jsonify(token_result), 400

        # Store access token in session (in production, store encrypted in database)
        session['fb_access_token'] = token_result['access_token']
        session['fb_token_expires_at'] = token_result['expires_at']

        # Get user's ad accounts
        accounts_result = service.get_ad_accounts(token_result['access_token'])

        if accounts_result.get('success'):
            session['fb_ad_accounts'] = accounts_result['ad_accounts']

        return jsonify({
            'success': True,
            'message': 'Facebook account connected successfully',
            'ad_accounts': accounts_result.get('ad_accounts', [])
        })

    except Exception as e:
        logger.error(f"Error in OAuth callback: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@social_bp.route("/api/export/facebook/connection-status", methods=["GET"])
@login_required
def facebook_connection_status():
    """Check if user has connected Facebook account"""
    access_token = session.get('fb_access_token')
    expires_at = session.get('fb_token_expires_at')
    ad_accounts = session.get('fb_ad_accounts', [])

    if not access_token:
        return jsonify({
            'success': True,
            'connected': False
        })

    # Check if token is expired
    from datetime import datetime
    if expires_at:
        try:
            expires = datetime.fromisoformat(expires_at)
            if datetime.utcnow() >= expires:
                # Token expired
                session.pop('fb_access_token', None)
                session.pop('fb_token_expires_at', None)
                session.pop('fb_ad_accounts', None)
                return jsonify({
                    'success': True,
                    'connected': False,
                    'message': 'Token expired'
                })
        except:
            pass

    return jsonify({
        'success': True,
        'connected': True,
        'ad_accounts': ad_accounts,
        'expires_at': expires_at
    })


@social_bp.route("/api/export/facebook/disconnect", methods=["POST"])
@login_required
def disconnect_facebook():
    """Disconnect Facebook account"""
    session.pop('fb_access_token', None)
    session.pop('fb_token_expires_at', None)
    session.pop('fb_ad_accounts', None)

    return jsonify({
        'success': True,
        'message': 'Facebook account disconnected'
    })


@social_bp.route("/api/export/facebook", methods=["POST"])
@login_required
def export_to_facebook():
    """Export creative to Facebook Ads Manager"""
    data = request.get_json()

    creative_id = data.get('creative_id')
    ad_account_id = data.get('ad_account_id')
    page_id = data.get('page_id')
    destination_url = data.get('destination_url')

    if not all([creative_id, ad_account_id, page_id, destination_url]):
        return jsonify({
            'success': False,
            'error': 'creative_id, ad_account_id, page_id, and destination_url required'
        }), 400

    # Check if user has connected Facebook
    access_token = session.get('fb_access_token')
    if not access_token:
        return jsonify({
            'success': False,
            'error': 'Facebook account not connected',
            'connect_required': True
        }), 401

    # Get creative
    creative = AdCreative.query.get(creative_id)
    if not creative or creative.user_id != current_user.id:
        return jsonify({'success': False, 'error': 'Creative not found'}), 404

    try:
        service = SocialExportService()

        # Export creative
        result = service.export_creative_to_facebook(
            access_token=access_token,
            ad_account_id=ad_account_id,
            page_id=page_id,
            creative={
                'name': creative.name,
                'headline': creative.headline,
                'primary_text': creative.primary_text,
                'description': creative.description,
                'call_to_action': creative.call_to_action,
                'image_url': creative.image_url
            },
            destination_url=destination_url
        )

        if result.get('success'):
            # Update creative status
            creative.status = 'published'
            creative.published_at = datetime.utcnow()
            creative.used_in_campaign = True
            db.session.commit()

            # Log analytics event
            try:
                analytics_event = AdAnalyticsEvent(
                    user_id=current_user.id,
                    account_id=current_user.account_id if hasattr(current_user, 'account_id') else None,
                    creative_id=creative.id,
                    event_type='creative_exported',
                    platform='facebook',
                    event_data={
                        'ad_account_id': ad_account_id,
                        'facebook_creative_id': result.get('creative_id')
                    },
                    session_id=session.get('session_id')
                )
                db.session.add(analytics_event)
                db.session.commit()
            except:
                pass

        return jsonify(result)

    except Exception as e:
        logger.error(f"Error exporting to Facebook: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@social_bp.route("/api/export/instagram", methods=["POST"])
@login_required
def export_to_instagram():
    """Export creative to Instagram via Facebook Marketing API"""
    # Instagram export uses same flow as Facebook
    # Just need to specify Instagram account ID instead of Page ID
    return export_to_facebook()
