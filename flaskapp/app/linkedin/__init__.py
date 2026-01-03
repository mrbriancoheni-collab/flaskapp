# app/linkedin/__init__.py
from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required, current_user
import logging
import os
from datetime import datetime, date, timedelta

from app import db
from app.auth.utils import current_account_id
from app.models_linkedin import LinkedInScheduledPost, LinkedInCategory, LinkedInCategoryTopic, LinkedInCampaign
from app.services.ai_prompts_init import get_prompt_for_service

logger = logging.getLogger(__name__)

linkedin_bp = Blueprint("linkedin_bp", __name__, url_prefix="/account/linkedin")

# Check if AI is available
try:
    import anthropic
    _AI_OK = True
except Exception:
    _AI_OK = False


@linkedin_bp.app_context_processor
def linkedin_ctx_injector():
    """Add LinkedIn-specific context variables"""
    def has_endpoint(endpoint_name: str) -> bool:
        from flask import current_app
        try:
            return endpoint_name in current_app.view_functions
        except Exception:
            return False

    return {
        "has_endpoint": has_endpoint,
    }


@linkedin_bp.route("/")
@login_required
def index():
    """LinkedIn overview/dashboard"""
    return render_template(
        "linkedin/index.html",
        ai_available=_AI_OK,
    )


@linkedin_bp.route("/ads")
@login_required
def ads():
    """LinkedIn Ads Optimizer - similar to Google Ads"""
    # Demo data for LinkedIn ads
    ads_data = {
        "account_name": "Demo Home Services Co.",
        "campaigns": [
            {
                "id": "LC-1001",
                "name": "Home Services Professionals - Sponsored Content",
                "type": "SPONSORED_CONTENT",
                "status": "Active",
                "daily_budget": 100,
                "objective": "Lead Generation",
                "targeting": "Homeowners 35-65"
            },
            {
                "id": "LC-1002",
                "name": "HVAC Decision Makers - InMail",
                "type": "SPONSORED_INMAIL",
                "status": "Paused",
                "daily_budget": 75,
                "objective": "Website Visits",
                "targeting": "Facility Managers"
            }
        ],
        "creatives": [
            {
                "id": "CR-2001",
                "campaign_id": "LC-1001",
                "format": "Single Image",
                "headline": "Stop Overpaying for HVAC Services",
                "intro_text": "Smart homeowners trust our certified technicians for all their heating and cooling needs.",
                "cta": "Learn More",
                "status": "Active",
                "impressions": 12500,
                "clicks": 187,
                "ctr": "1.5%",
                "leads": 23
            },
            {
                "id": "CR-2002",
                "campaign_id": "LC-1001",
                "format": "Carousel",
                "headline": "5 Signs Your Water Heater Needs Replacement",
                "intro_text": "Don't wait for a cold shower emergency. Know the warning signs.",
                "cta": "Get Quote",
                "status": "Active",
                "impressions": 8300,
                "clicks": 94,
                "ctr": "1.1%",
                "leads": 11
            }
        ],
        "lead_forms": [
            {
                "id": "LF-3001",
                "name": "HVAC Quote Request",
                "fields": ["Name", "Email", "Phone", "Service Type", "Preferred Date"],
                "submissions": 34,
                "completion_rate": "68%"
            }
        ]
    }

    return render_template(
        "linkedin/ads.html",
        ads_data=ads_data,
        connected=False,  # Set to True when OAuth is implemented
        ai_connected=_AI_OK,
    )


@linkedin_bp.route("/ads/optimize", methods=["POST"])
@login_required
def ads_optimize():
    """Generate AI optimization suggestions for LinkedIn Ads"""
    if not _AI_OK:
        return jsonify({
            "error": "AI not configured. Please add ANTHROPIC_API_KEY to environment."
        }), 400

    try:
        # Get the current ads data (in real implementation, fetch from LinkedIn API)
        # For now, we'll use mock data

        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            return jsonify({"error": "Missing ANTHROPIC_API_KEY"}), 400

        client = anthropic.Anthropic(api_key=api_key)

        prompt = """You are a LinkedIn Ads expert helping home services businesses optimize their campaigns.

Analyze this LinkedIn Ads account and provide specific optimization recommendations:

Account: Demo Home Services Co.
Current Campaigns:
- Home Services Professionals - Sponsored Content (Active, $100/day budget)
- HVAC Decision Makers - InMail (Paused, $75/day budget)

Top performing creative:
- "Stop Overpaying for HVAC Services" - 1.5% CTR, 23 leads
- "5 Signs Your Water Heater Needs Replacement" - 1.1% CTR, 11 leads

Provide 3-5 specific, actionable recommendations to:
1. Improve click-through rates
2. Generate more qualified leads
3. Reduce cost per lead
4. Optimize targeting for home services buyers

Format as a JSON object with:
- summary: Brief overview (1-2 sentences)
- recommendations: Array of objects with {title, description, priority (high/medium/low)}
"""

        message = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}]
        )

        # Extract the response text
        response_text = message.content[0].text

        # Try to parse as JSON, otherwise wrap it
        import json
        try:
            result = json.loads(response_text)
        except:
            result = {
                "summary": "AI analysis complete.",
                "recommendations": [
                    {
                        "title": "LinkedIn Ads Optimization",
                        "description": response_text,
                        "priority": "high"
                    }
                ]
            }

        return jsonify(result)

    except Exception as e:
        logger.exception("Error generating LinkedIn Ads optimization")
        return jsonify({"error": str(e)}), 500


@linkedin_bp.route("/post-generator", methods=["GET", "POST"])
@login_required
def post_generator():
    """LinkedIn Thought Leader Post Generator"""
    account_id = current_account_id()

    # Get query parameters to pre-fill the form
    prefill_data = {
        'category_id': request.args.get('category_id', ''),
        'expertise': request.args.get('expertise', ''),
        'industry': request.args.get('industry', 'digital marketing'),
        'topic': request.args.get('topic', ''),
        'tone': request.args.get('tone', 'professional'),
        'include_hashtags': request.args.get('include_hashtags', ''),
        'include_cta': request.args.get('include_cta', ''),
    }

    # Auto-generate if all required fields are present in URL
    auto_generate = bool(prefill_data['expertise'] and prefill_data['topic'])

    # Get available categories for the dropdown
    categories = []
    if account_id:
        try:
            categories = LinkedInCategory.query.filter_by(
                account_id=account_id
            ).order_by(LinkedInCategory.priority.asc()).all()
        except Exception as e:
            logger.error(f"Error loading categories: {e}")
            categories = []

    return render_template(
        "linkedin/post_generator.html",
        ai_available=_AI_OK,
        prefill=prefill_data,
        auto_generate=auto_generate,
        categories=categories,
    )


@linkedin_bp.route("/post-generator/generate", methods=["POST"])
@login_required
def generate_post():
    """Generate thought leader post using AI with category/POV support"""
    if not _AI_OK:
        return jsonify({
            "error": "AI not configured. Please add ANTHROPIC_API_KEY to environment."
        }), 400

    account_id = current_account_id()
    if not account_id:
        return jsonify({"error": "Unable to determine account"}), 400

    try:
        # Extract form data
        category_id = request.form.get("category_id", "")
        expertise = request.form.get("expertise", "")
        industry = request.form.get("industry", "home services")
        topic = request.form.get("topic", "")
        tone = request.form.get("tone", "professional")
        include_hashtags = request.form.get("include_hashtags") == "on"
        include_cta = request.form.get("include_cta") == "on"

        # Get category POV if provided
        category_name = ""
        pov_statement = ""

        if category_id:
            category = LinkedInCategory.query.filter_by(
                id=int(category_id),
                account_id=account_id
            ).first()

            if category:
                category_name = category.name
                pov_statement = category.pov_statement
                if not expertise and category.unique_expertise:
                    expertise = category.unique_expertise

        # Fallback validation
        if not expertise or not topic:
            return jsonify({"error": "Expertise and topic are required"}), 400

        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            return jsonify({"error": "Missing ANTHROPIC_API_KEY"}), 400

        client = anthropic.Anthropic(api_key=api_key)

        # Get the LinkedIn prompt template from database (admin-editable)
        linkedin_prompt_config = get_prompt_for_service('linkedin_thought_leadership')

        if linkedin_prompt_config:
            # Use admin-editable prompt template
            prompt_template = linkedin_prompt_config['prompt_template']

            # Fill in the template
            prompt = prompt_template.format(
                industry=industry,
                category_name=category_name or "General",
                pov_statement=pov_statement or "Unique perspective based on expertise",
                expertise=expertise,
                topic=topic,
                tone=tone,
                include_hashtags="yes" if include_hashtags else "no",
                include_cta="yes" if include_cta else "no"
            )

            model = linkedin_prompt_config['model']
            temperature = linkedin_prompt_config['temperature']
            max_tokens = linkedin_prompt_config['max_tokens']
        else:
            # Fallback to hardcoded prompt if not in database
            prompt = f"""You are a LinkedIn thought leader post writer for professionals in the {industry} industry.

{"CATEGORY & POV:" if category_name else ""}
{f"- Content Category: {category_name}" if category_name else ""}
{f"- Unique Point of View: {pov_statement}" if pov_statement else ""}
- User's Expertise: {expertise}

TOPIC FOR THIS POST:
{topic}

CONTENT STRATEGY:
- Tone: {tone}
- Post Length: 150-300 words

Write a compelling LinkedIn post that:
1. Hooks readers in the first line
2. Demonstrates unique expertise and insights
3. Provides actionable value
4. Uses short paragraphs for mobile readability
{"5. Includes 3-5 relevant hashtags at the end" if include_hashtags else ""}
{"6. Ends with a clear call-to-action" if include_cta else ""}

Generate the post now:"""

            model = "claude-3-5-sonnet-20241022"
            temperature = 0.7
            max_tokens = 1000

        message = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[{"role": "user", "content": prompt}]
        )

        # Extract the response text
        post_text = message.content[0].text.strip()

        return jsonify({
            "post": post_text,
            "metadata": {
                "category": category_name if category_name else None,
                "expertise": expertise,
                "topic": topic,
                "tone": tone,
                "generated_at": datetime.now().isoformat()
            }
        })

    except Exception as e:
        logger.exception("Error generating LinkedIn post")
        return jsonify({"error": str(e)}), 500


@linkedin_bp.route("/schedule")
@login_required
def schedule():
    """View scheduled posts calendar"""
    account_id = current_account_id()
    if not account_id:
        flash("Unable to determine account", "error")
        return redirect(url_for("linkedin_bp.index"))

    # Get all scheduled posts for this account
    scheduled_posts = LinkedInScheduledPost.get_scheduled_for_account(account_id, status="scheduled")

    return render_template(
        "linkedin/schedule.html",
        scheduled_posts=scheduled_posts,
        ai_available=_AI_OK,
    )


@linkedin_bp.route("/schedule/save", methods=["POST"])
@login_required
def schedule_save():
    """Save a scheduled post"""
    account_id = current_account_id()
    if not account_id:
        return jsonify({"error": "Unable to determine account"}), 400

    try:
        # Get form data
        post_text = request.form.get("post_text", "").strip()
        scheduled_date_str = request.form.get("scheduled_date", "").strip()
        scheduled_time = request.form.get("scheduled_time", "09:00").strip()

        # Get metadata
        expertise = request.form.get("expertise", "")
        industry = request.form.get("industry", "")
        topic = request.form.get("topic", "")
        tone = request.form.get("tone", "")

        # Validation
        if not post_text:
            return jsonify({"error": "Post text is required"}), 400

        if not scheduled_date_str:
            return jsonify({"error": "Scheduled date is required"}), 400

        # Parse and validate date
        try:
            scheduled_date = datetime.strptime(scheduled_date_str, "%Y-%m-%d").date()
        except ValueError:
            return jsonify({"error": "Invalid date format. Use YYYY-MM-DD"}), 400

        # Validate date is in the future
        today = date.today()
        if scheduled_date < today:
            return jsonify({"error": "Cannot schedule posts in the past"}), 400

        # Validate date is within 1 week
        max_date = today + timedelta(days=7)
        if scheduled_date > max_date:
            return jsonify({"error": "Can only schedule up to 1 week in advance"}), 400

        # Check if already scheduled for this date (1 post per day limit)
        existing = LinkedInScheduledPost.get_for_date(account_id, scheduled_date)
        if existing:
            return jsonify({
                "error": f"You already have a post scheduled for {scheduled_date.strftime('%B %d, %Y')}. Only 1 post per day allowed."
            }), 400

        # Create scheduled post
        scheduled_post = LinkedInScheduledPost(
            account_id=account_id,
            post_text=post_text,
            scheduled_date=scheduled_date,
            scheduled_time=scheduled_time,
            expertise=expertise,
            industry=industry,
            topic=topic,
            tone=tone,
            status="scheduled"
        )

        db.session.add(scheduled_post)
        db.session.commit()

        return jsonify({
            "success": True,
            "message": f"Post scheduled for {scheduled_date.strftime('%B %d, %Y')}",
            "post": scheduled_post.to_dict()
        })

    except Exception as e:
        db.session.rollback()
        logger.exception("Error saving scheduled post")
        return jsonify({"error": str(e)}), 500


@linkedin_bp.route("/schedule/list", methods=["GET"])
@login_required
def schedule_list():
    """Get list of scheduled posts as JSON"""
    account_id = current_account_id()
    if not account_id:
        return jsonify({"error": "Unable to determine account"}), 400

    try:
        scheduled_posts = LinkedInScheduledPost.get_scheduled_for_account(account_id, status="scheduled")
        return jsonify({
            "posts": [post.to_dict() for post in scheduled_posts],
            "count": len(scheduled_posts)
        })

    except Exception as e:
        logger.exception("Error fetching scheduled posts")
        return jsonify({"error": str(e)}), 500


@linkedin_bp.route("/schedule/<int:post_id>/delete", methods=["POST", "DELETE"])
@login_required
def schedule_delete(post_id):
    """Delete/cancel a scheduled post"""
    account_id = current_account_id()
    if not account_id:
        return jsonify({"error": "Unable to determine account"}), 400

    try:
        # Find the post
        post = LinkedInScheduledPost.query.filter_by(
            id=post_id,
            account_id=account_id
        ).first()

        if not post:
            return jsonify({"error": "Scheduled post not found"}), 404

        # Only allow deletion of scheduled posts
        if post.status != "scheduled":
            return jsonify({"error": f"Cannot delete post with status: {post.status}"}), 400

        # Delete the post
        db.session.delete(post)
        db.session.commit()

        return jsonify({
            "success": True,
            "message": "Scheduled post deleted"
        })

    except Exception as e:
        db.session.rollback()
        logger.exception("Error deleting scheduled post")
        return jsonify({"error": str(e)}), 500


@linkedin_bp.route("/schedule/<int:post_id>/update", methods=["POST", "PUT"])
@login_required
def schedule_update(post_id):
    """Update a scheduled post"""
    account_id = current_account_id()
    if not account_id:
        return jsonify({"error": "Unable to determine account"}), 400

    try:
        # Find the post
        post = LinkedInScheduledPost.query.filter_by(
            id=post_id,
            account_id=account_id
        ).first()

        if not post:
            return jsonify({"error": "Scheduled post not found"}), 404

        # Only allow updating of scheduled posts
        if post.status != "scheduled":
            return jsonify({"error": f"Cannot update post with status: {post.status}"}), 400

        # Get update data
        post_text = request.form.get("post_text")
        scheduled_date_str = request.form.get("scheduled_date")
        scheduled_time = request.form.get("scheduled_time")

        # Update fields if provided
        if post_text is not None:
            post.post_text = post_text.strip()

        if scheduled_date_str:
            try:
                new_date = datetime.strptime(scheduled_date_str, "%Y-%m-%d").date()

                # Validate new date
                today = date.today()
                if new_date < today:
                    return jsonify({"error": "Cannot schedule posts in the past"}), 400

                max_date = today + timedelta(days=7)
                if new_date > max_date:
                    return jsonify({"error": "Can only schedule up to 1 week in advance"}), 400

                # Check if another post exists on new date
                if new_date != post.scheduled_date:
                    existing = LinkedInScheduledPost.get_for_date(account_id, new_date)
                    if existing and existing.id != post_id:
                        return jsonify({
                            "error": f"You already have a post scheduled for {new_date.strftime('%B %d, %Y')}"
                        }), 400

                post.scheduled_date = new_date

            except ValueError:
                return jsonify({"error": "Invalid date format. Use YYYY-MM-DD"}), 400

        if scheduled_time:
            post.scheduled_time = scheduled_time.strip()

        db.session.commit()

        return jsonify({
            "success": True,
            "message": "Scheduled post updated",
            "post": post.to_dict()
        })

    except Exception as e:
        db.session.rollback()
        logger.exception("Error updating scheduled post")
        return jsonify({"error": str(e)}), 500


# ==================== Category Management Routes ====================

@linkedin_bp.route("/categories")
@login_required
def categories():
    """View and manage thought leadership categories"""
    account_id = current_account_id()
    if not account_id:
        flash("Unable to determine account", "error")
        return redirect(url_for("linkedin_bp.index"))

    try:
        # Get all categories for this account
        categories_list = LinkedInCategory.query.filter_by(
            account_id=account_id
        ).order_by(LinkedInCategory.priority.asc(), LinkedInCategory.name.asc()).all()

        return render_template(
            "linkedin/categories.html",
            categories=categories_list,
            ai_available=_AI_OK,
        )
    except Exception as e:
        logger.error(f"Error loading LinkedIn categories: {e}", exc_info=True)

        # Check if it's a table doesn't exist error
        error_msg = str(e).lower()
        if "doesn't exist" in error_msg or "no such table" in error_msg:
            # Try to create the tables
            try:
                from app.models_linkedin import ensure_linkedin_tables
                ensure_linkedin_tables()
                flash("LinkedIn tables created. Please refresh the page.", "success")
            except Exception as create_error:
                logger.error(f"Failed to create LinkedIn tables: {create_error}", exc_info=True)
                flash(f"Database error: LinkedIn tables don't exist. Please contact support.", "error")
        else:
            flash(f"Error loading categories: {str(e)}", "error")

        return redirect(url_for("linkedin_bp.index"))


@linkedin_bp.route("/categories/new", methods=["GET", "POST"])
@login_required
def category_new():
    """Create a new thought leadership category"""
    account_id = current_account_id()
    if not account_id:
        flash("Unable to determine account", "error")
        return redirect(url_for("linkedin_bp.index"))

    if request.method == "POST":
        try:
            # Get form data
            name = request.form.get("name", "").strip()
            description = request.form.get("description", "").strip()
            pov_statement = request.form.get("pov_statement", "").strip()
            unique_expertise = request.form.get("unique_expertise", "").strip()
            post_frequency = request.form.get("post_frequency", "weekly")
            priority = int(request.form.get("priority", "1"))
            is_active = request.form.get("is_active") == "on"

            # Validation
            if not name:
                flash("Category name is required", "error")
                return redirect(url_for("linkedin_bp.category_new"))

            if not pov_statement:
                flash("Point of View statement is required", "error")
                return redirect(url_for("linkedin_bp.category_new"))

            # Check category limit (recommend 3-5)
            category_count = LinkedInCategory.count_for_account(account_id)
            if category_count >= 10:
                flash("Maximum 10 categories allowed. Consider consolidating or removing inactive categories.", "warning")
                return redirect(url_for("linkedin_bp.categories"))

            # Create category
            category = LinkedInCategory(
                account_id=account_id,
                name=name,
                description=description,
                pov_statement=pov_statement,
                unique_expertise=unique_expertise,
                post_frequency=post_frequency,
                priority=priority,
                is_active=is_active
            )

            db.session.add(category)
            db.session.commit()

            flash(f"Category '{name}' created successfully!", "success")
            return redirect(url_for("linkedin_bp.category_edit", category_id=category.id))

        except Exception as e:
            db.session.rollback()
            logger.exception("Error creating category")
            flash(f"Error creating category: {str(e)}", "error")
            return redirect(url_for("linkedin_bp.category_new"))

    # GET request - show form
    return render_template(
        "linkedin/category_form.html",
        category=None,
        ai_available=_AI_OK,
    )


@linkedin_bp.route("/categories/<int:category_id>/edit", methods=["GET", "POST"])
@login_required
def category_edit(category_id):
    """Edit an existing thought leadership category"""
    account_id = current_account_id()
    if not account_id:
        flash("Unable to determine account", "error")
        return redirect(url_for("linkedin_bp.index"))

    # Find the category
    category = LinkedInCategory.query.filter_by(
        id=category_id,
        account_id=account_id
    ).first()

    if not category:
        flash("Category not found", "error")
        return redirect(url_for("linkedin_bp.categories"))

    if request.method == "POST":
        try:
            # Get form data
            category.name = request.form.get("name", "").strip()
            category.description = request.form.get("description", "").strip()
            category.pov_statement = request.form.get("pov_statement", "").strip()
            category.unique_expertise = request.form.get("unique_expertise", "").strip()
            category.post_frequency = request.form.get("post_frequency", "weekly")
            category.priority = int(request.form.get("priority", "1"))
            category.is_active = request.form.get("is_active") == "on"

            # Validation
            if not category.name:
                flash("Category name is required", "error")
                return render_template("linkedin/category_form.html", category=category, ai_available=_AI_OK)

            if not category.pov_statement:
                flash("Point of View statement is required", "error")
                return render_template("linkedin/category_form.html", category=category, ai_available=_AI_OK)

            db.session.commit()

            flash(f"Category '{category.name}' updated successfully!", "success")
            return redirect(url_for("linkedin_bp.categories"))

        except Exception as e:
            db.session.rollback()
            logger.exception("Error updating category")
            flash(f"Error updating category: {str(e)}", "error")

    # GET request - show form with existing data
    # Get topics for this category
    topics = LinkedInCategoryTopic.query.filter_by(category_id=category_id).order_by(
        LinkedInCategoryTopic.used.asc(),
        LinkedInCategoryTopic.created_at.desc()
    ).all()

    return render_template(
        "linkedin/category_form.html",
        category=category,
        topics=topics,
        ai_available=_AI_OK,
    )


@linkedin_bp.route("/categories/<int:category_id>/delete", methods=["POST", "DELETE"])
@login_required
def category_delete(category_id):
    """Delete a thought leadership category"""
    account_id = current_account_id()
    if not account_id:
        return jsonify({"error": "Unable to determine account"}), 400

    try:
        # Find the category
        category = LinkedInCategory.query.filter_by(
            id=category_id,
            account_id=account_id
        ).first()

        if not category:
            return jsonify({"error": "Category not found"}), 404

        category_name = category.name

        # Delete the category (topics will cascade delete)
        db.session.delete(category)
        db.session.commit()

        return jsonify({
            "success": True,
            "message": f"Category '{category_name}' deleted successfully"
        })

    except Exception as e:
        db.session.rollback()
        logger.exception("Error deleting category")
        return jsonify({"error": str(e)}), 500


@linkedin_bp.route("/categories/<int:category_id>/topics/add", methods=["POST"])
@login_required
def category_topic_add(category_id):
    """Add a topic idea to a category"""
    account_id = current_account_id()
    if not account_id:
        return jsonify({"error": "Unable to determine account"}), 400

    try:
        # Verify category belongs to account
        category = LinkedInCategory.query.filter_by(
            id=category_id,
            account_id=account_id
        ).first()

        if not category:
            return jsonify({"error": "Category not found"}), 404

        # Get form data
        topic_idea = request.form.get("topic_idea", "").strip()
        tone = request.form.get("tone", "professional")

        if not topic_idea:
            return jsonify({"error": "Topic idea is required"}), 400

        # Create topic
        topic = LinkedInCategoryTopic(
            category_id=category_id,
            topic_idea=topic_idea,
            tone=tone
        )

        db.session.add(topic)
        db.session.commit()

        return jsonify({
            "success": True,
            "message": "Topic added successfully",
            "topic": topic.to_dict()
        })

    except Exception as e:
        db.session.rollback()
        logger.exception("Error adding topic")
        return jsonify({"error": str(e)}), 500


@linkedin_bp.route("/categories/topics/<int:topic_id>/delete", methods=["POST", "DELETE"])
@login_required
def category_topic_delete(topic_id):
    """Delete a topic idea"""
    account_id = current_account_id()
    if not account_id:
        return jsonify({"error": "Unable to determine account"}), 400

    try:
        # Find the topic and verify it belongs to user's category
        topic = LinkedInCategoryTopic.query.join(LinkedInCategory).filter(
            LinkedInCategoryTopic.id == topic_id,
            LinkedInCategory.account_id == account_id
        ).first()

        if not topic:
            return jsonify({"error": "Topic not found"}), 404

        db.session.delete(topic)
        db.session.commit()

        return jsonify({
            "success": True,
            "message": "Topic deleted successfully"
        })

    except Exception as e:
        db.session.rollback()
        logger.exception("Error deleting topic")
        return jsonify({"error": str(e)}), 500
