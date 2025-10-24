# app/linkedin/__init__.py
from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required, current_user
import logging
import os
from datetime import datetime, date, timedelta

from app import db
from app.auth.utils import current_account_id
from app.models_linkedin import LinkedInScheduledPost

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


@linkedin_bp.route("/post-generator")
@login_required
def post_generator():
    """LinkedIn Thought Leader Post Generator"""
    return render_template(
        "linkedin/post_generator.html",
        ai_available=_AI_OK,
    )


@linkedin_bp.route("/post-generator/generate", methods=["POST"])
@login_required
def generate_post():
    """Generate thought leader post using AI"""
    if not _AI_OK:
        return jsonify({
            "error": "AI not configured. Please add ANTHROPIC_API_KEY to environment."
        }), 400

    try:
        # Extract form data
        expertise = request.form.get("expertise", "")
        industry = request.form.get("industry", "home services")
        topic = request.form.get("topic", "")
        tone = request.form.get("tone", "professional")
        include_hashtags = request.form.get("include_hashtags") == "on"
        include_cta = request.form.get("include_cta") == "on"

        if not expertise or not topic:
            return jsonify({"error": "Expertise and topic are required"}), 400

        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            return jsonify({"error": "Missing ANTHROPIC_API_KEY"}), 400

        client = anthropic.Anthropic(api_key=api_key)

        # Build the prompt
        prompt = f"""You are a LinkedIn thought leader post writer for professionals in the {industry} industry.

User's unique expertise: {expertise}

Topic to write about: {topic}

Tone: {tone}

Write a compelling LinkedIn post that:
1. Hooks readers in the first line
2. Demonstrates unique expertise and insights
3. Provides actionable value
4. Uses short paragraphs for mobile readability
5. Is 150-300 words (optimal LinkedIn length)
{"6. Includes 3-5 relevant hashtags at the end" if include_hashtags else ""}
{"7. Ends with a clear call-to-action (question, comment prompt, or DM invitation)" if include_cta else ""}

Important:
- Start strong - first line should make people want to read more
- Use personal stories or specific examples when relevant
- Break up text with line breaks for readability
- Don't use emojis unless the tone is casual
- Sound like a real person, not a corporate account

Generate the post now:"""

        message = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}]
        )

        # Extract the response text
        post_text = message.content[0].text.strip()

        return jsonify({
            "post": post_text,
            "metadata": {
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
