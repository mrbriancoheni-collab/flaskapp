# app/social/__init__.py
"""
Social Media Ad Composer Routes

AI-powered ad creative generation for social media platforms
"""
from flask import Blueprint, render_template, request, jsonify, session
from flask_login import login_required, current_user
import logging

from app.extensions import db
from app.models_social import AdCreative, AdTemplate, AdGenerationJob
from app.services.ad_generation_service import AdGenerationService

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
