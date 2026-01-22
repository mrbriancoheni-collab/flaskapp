# app/creative_studio/__init__.py
"""
AI Creative Studio Module
Generates ad creatives, headlines, descriptions, and images using AI.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from flask import (
    Blueprint,
    current_app,
    render_template,
    jsonify,
    request,
    flash,
    redirect,
    url_for,
)
from sqlalchemy import text

from app import db
from app.auth.utils import login_required, current_account_id, is_paid_account

creative_bp = Blueprint("creative_bp", __name__, url_prefix="/account/creative-studio")


def _get_account_industry(aid: int) -> Optional[str]:
    """Get the industry preset for an account."""
    try:
        with db.engine.connect() as conn:
            row = conn.execute(
                text("SELECT industry_preset FROM accounts WHERE id = :aid"),
                {"aid": aid}
            ).mappings().first()
            return row.get("industry_preset") if row else None
    except Exception:
        return None


def _get_business_info(aid: int) -> Dict[str, Any]:
    """Get business information for an account."""
    try:
        with db.engine.connect() as conn:
            row = conn.execute(
                text("""
                    SELECT business_name, business_phone, business_website,
                           city, state, industry
                    FROM accounts WHERE id = :aid
                """),
                {"aid": aid}
            ).mappings().first()
            return dict(row) if row else {}
    except Exception:
        return {}


def generate_ad_headlines(
    business_name: str,
    industry: str,
    keywords: List[str],
    unique_selling_points: List[str]
) -> List[str]:
    """
    Generate Google Ads headlines (max 30 characters each).
    Returns 10-15 headline options.
    """
    headlines = []

    # Pattern 1: Business name + action
    if len(business_name) <= 20:
        headlines.append(f"{business_name} - Call Now")
        headlines.append(f"Call {business_name} Today")

    # Pattern 2: Location-based
    headlines.extend([
        "Local Experts Near You",
        "Serving Your Area 24/7",
        "Your Neighborhood Pros",
    ])

    # Pattern 3: Benefit-focused
    headlines.extend([
        "Fast & Reliable Service",
        "Licensed & Insured",
        "Free Estimates Available",
        "Same-Day Appointments",
        "Satisfaction Guaranteed",
        "Trusted Since Day One",
    ])

    # Pattern 4: Urgency
    headlines.extend([
        "Book Online Now",
        "Call Today - Save 10%",
        "Limited Time Offer",
        "Don't Wait - Call Now",
    ])

    # Pattern 5: Social proof
    headlines.extend([
        "5-Star Rated Service",
        "1000+ Happy Customers",
        "Top Rated in Your Area",
    ])

    # Filter to 30 chars max
    headlines = [h for h in headlines if len(h) <= 30]

    return headlines[:15]


def generate_ad_descriptions(
    business_name: str,
    industry: str,
    keywords: List[str],
    unique_selling_points: List[str]
) -> List[str]:
    """
    Generate Google Ads descriptions (max 90 characters each).
    Returns 4-6 description options.
    """
    descriptions = []

    # Pattern 1: Benefit + CTA
    descriptions.append(
        f"Professional {industry.lower()} services you can trust. Licensed experts ready to help. Call now!"
    )

    # Pattern 2: Features
    descriptions.append(
        "Fast response times, honest pricing, and quality work guaranteed. Schedule your appointment today."
    )

    # Pattern 3: Trust signals
    descriptions.append(
        "Licensed, bonded, and insured professionals. Serving your community with pride. Free estimates!"
    )

    # Pattern 4: Urgency + offer
    descriptions.append(
        "Book today and save! Limited appointments available. Satisfaction guaranteed or your money back."
    )

    # Filter to 90 chars max
    descriptions = [d for d in descriptions if len(d) <= 90]

    return descriptions[:6]


def generate_social_post(
    business_name: str,
    industry: str,
    post_type: str = "promotional"
) -> Dict[str, str]:
    """
    Generate social media post content.
    """
    posts = {
        "promotional": {
            "text": f"🔧 Need {industry.lower()} help? {business_name} is here for you!\n\n✅ Licensed & Insured\n✅ Free Estimates\n✅ Same-Day Service\n\nCall us today! 📞 #LocalBusiness #{industry.replace(' ', '')}",
            "hashtags": ["#LocalBusiness", "#SmallBusiness", f"#{industry.replace(' ', '')}", "#ServicePros"]
        },
        "educational": {
            "text": f"💡 Pro Tip from {business_name}:\n\nRegular maintenance saves money in the long run! Schedule your annual checkup today and avoid costly repairs later.\n\n#ProTip #{industry.replace(' ', '')} #MaintenanceMatters",
            "hashtags": ["#ProTip", "#HomeOwnerTips", "#Maintenance"]
        },
        "testimonial": {
            "text": f"⭐⭐⭐⭐⭐\n\n\"Amazing service! The team at {business_name} was professional, on time, and did excellent work. Highly recommend!\"\n\nThank you for trusting us! 🙏\n\n#{industry.replace(' ', '')} #CustomerReview",
            "hashtags": ["#CustomerReview", "#5Stars", "#ThankYou"]
        },
        "seasonal": {
            "text": f"🌟 Seasonal Special from {business_name}!\n\nBook this month and get 10% off your service. Limited spots available!\n\n📞 Call now to schedule\n\n#{industry.replace(' ', '')} #SpecialOffer #LimitedTime",
            "hashtags": ["#SpecialOffer", "#SeasonalDeal", "#BookNow"]
        }
    }

    return posts.get(post_type, posts["promotional"])


def generate_email_subject_lines(
    business_name: str,
    email_type: str = "promotional"
) -> List[str]:
    """Generate email subject line options."""
    subjects = {
        "promotional": [
            f"Special Offer from {business_name} - Don't Miss Out!",
            "Your Exclusive Discount Awaits 🎉",
            f"{business_name}: Limited Time Savings Inside",
            "We've Got a Deal Just for You",
            "Save Big This Month - Details Inside"
        ],
        "follow_up": [
            "How Did We Do?",
            f"A Quick Note from {business_name}",
            "We'd Love Your Feedback",
            "Thank You for Choosing Us!",
            "Your Opinion Matters to Us"
        ],
        "reminder": [
            "Don't Forget - Your Appointment is Coming Up",
            "Friendly Reminder from {business_name}",
            "It's Time for Your Annual Service",
            "Schedule Your Checkup Today",
            "We Miss You! Time for a Visit?"
        ]
    }

    return subjects.get(email_type, subjects["promotional"])


# -------------------- Routes --------------------

@creative_bp.route("/", methods=["GET"])
@login_required
def index():
    """Creative studio main page."""
    aid = current_account_id()
    if not aid:
        return redirect(url_for("account_bp.dashboard"))

    business_info = _get_business_info(aid)
    industry = _get_account_industry(aid) or "general"

    return render_template(
        "creative_studio/index.html",
        business_info=business_info,
        industry=industry,
        is_paid=is_paid_account()
    )


@creative_bp.route("/generate/ads", methods=["POST"])
@login_required
def generate_ads():
    """Generate Google Ads creatives."""
    aid = current_account_id()
    if not aid:
        return jsonify({"error": "Account not found"}), 404

    data = request.get_json() or {}
    business_name = data.get("business_name", "Your Business")
    industry = data.get("industry", "services")
    keywords = data.get("keywords", [])
    usps = data.get("unique_selling_points", [])

    headlines = generate_ad_headlines(business_name, industry, keywords, usps)
    descriptions = generate_ad_descriptions(business_name, industry, keywords, usps)

    return jsonify({
        "headlines": headlines,
        "descriptions": descriptions
    })


@creative_bp.route("/generate/social", methods=["POST"])
@login_required
def generate_social():
    """Generate social media post."""
    aid = current_account_id()
    if not aid:
        return jsonify({"error": "Account not found"}), 404

    data = request.get_json() or {}
    business_name = data.get("business_name", "Your Business")
    industry = data.get("industry", "services")
    post_type = data.get("post_type", "promotional")

    post = generate_social_post(business_name, industry, post_type)

    return jsonify(post)


@creative_bp.route("/generate/email", methods=["POST"])
@login_required
def generate_email():
    """Generate email subject lines."""
    aid = current_account_id()
    if not aid:
        return jsonify({"error": "Account not found"}), 404

    data = request.get_json() or {}
    business_name = data.get("business_name", "Your Business")
    email_type = data.get("email_type", "promotional")

    subjects = generate_email_subject_lines(business_name, email_type)

    return jsonify({"subject_lines": subjects})
