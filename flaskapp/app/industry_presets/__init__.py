# app/industry_presets/__init__.py
"""
Industry-Specific Presets Module
Provides pre-configured marketing setups for different business types.
"""
from __future__ import annotations

from typing import Any, Dict, List

from flask import (
    Blueprint,
    current_app,
    render_template,
    jsonify,
    request,
    session,
    redirect,
    url_for,
    flash,
)
from sqlalchemy import text

from app import db
from app.auth.utils import login_required, current_account_id, is_paid_account

industry_bp = Blueprint("industry_bp", __name__, url_prefix="/account/industry")


# Industry preset definitions
INDUSTRY_PRESETS = {
    "plumber": {
        "name": "Plumbing Services",
        "icon": "fa-wrench",
        "color": "blue",
        "description": "Emergency plumbing, drain cleaning, water heaters",
        "keywords": [
            "emergency plumber near me",
            "24 hour plumber",
            "drain cleaning service",
            "water heater repair",
            "pipe repair",
            "toilet repair",
            "faucet installation",
            "sewer line repair",
            "plumbing inspection",
            "leak detection"
        ],
        "negative_keywords": [
            "free", "diy", "how to", "jobs", "careers", "salary", "training", "school"
        ],
        "ad_headlines": [
            "24/7 Emergency Plumber",
            "Licensed & Insured Plumbers",
            "Same-Day Service Available",
            "Free Estimates - Call Now",
            "Local Plumbing Experts"
        ],
        "ad_descriptions": [
            "Fast, reliable plumbing services. Licensed professionals ready to help 24/7. Call now!",
            "From leaky faucets to major repairs. Honest pricing, quality work guaranteed."
        ],
        "review_response_templates": {
            "positive": "Thank you so much for the kind review, {name}! We're thrilled we could help with your plumbing needs. We appreciate your trust in our team!",
            "negative": "We're sorry to hear about your experience, {name}. Please contact us directly so we can make this right. Customer satisfaction is our top priority."
        },
        "seasonal_campaigns": {
            "winter": {"focus": "Frozen pipe prevention", "budget_multiplier": 1.3},
            "summer": {"focus": "Sprinkler systems", "budget_multiplier": 1.0}
        }
    },
    "electrician": {
        "name": "Electrical Services",
        "icon": "fa-bolt",
        "color": "yellow",
        "description": "Residential & commercial electrical work",
        "keywords": [
            "electrician near me",
            "electrical repair",
            "panel upgrade",
            "outlet installation",
            "lighting installation",
            "ceiling fan installation",
            "electrical inspection",
            "circuit breaker repair",
            "generator installation",
            "EV charger installation"
        ],
        "negative_keywords": [
            "free", "diy", "how to", "jobs", "careers", "salary", "apprentice"
        ],
        "ad_headlines": [
            "Licensed Electricians",
            "Safe & Reliable Service",
            "24/7 Emergency Electrical",
            "Free Safety Inspections",
            "Certified Master Electricians"
        ],
        "ad_descriptions": [
            "Professional electrical services for home and business. Licensed, bonded, insured. Call today!",
            "From repairs to full rewiring. Safety is our priority. Free estimates available."
        ],
        "review_response_templates": {
            "positive": "Thank you for your wonderful review, {name}! Safety is our top priority, and we're glad we could provide excellent service. Thank you for choosing us!",
            "negative": "We apologize for any inconvenience, {name}. Your safety matters to us. Please reach out so we can address your concerns properly."
        }
    },
    "hvac": {
        "name": "HVAC Services",
        "icon": "fa-temperature-half",
        "color": "red",
        "description": "Heating, cooling, and air quality",
        "keywords": [
            "hvac repair near me",
            "ac repair",
            "furnace repair",
            "air conditioning installation",
            "heating repair",
            "hvac maintenance",
            "duct cleaning",
            "thermostat installation",
            "heat pump service",
            "emergency hvac"
        ],
        "negative_keywords": [
            "free", "diy", "how to", "jobs", "careers", "parts"
        ],
        "ad_headlines": [
            "Fast AC & Heating Repair",
            "Licensed HVAC Technicians",
            "24/7 Emergency Service",
            "Financing Available",
            "Same-Day Appointments"
        ],
        "ad_descriptions": [
            "Stay comfortable year-round. Expert HVAC repair and installation. Licensed and insured.",
            "AC not working? We'll fix it fast. Free estimates, honest pricing. Call now!"
        ],
        "review_response_templates": {
            "positive": "Thank you for the great review, {name}! We're so glad we could keep you comfortable. We appreciate your business!",
            "negative": "We're sorry your experience wasn't perfect, {name}. Please contact us - we want to ensure you're comfortable in your home."
        },
        "seasonal_campaigns": {
            "summer": {"focus": "AC repair and tune-ups", "budget_multiplier": 1.5},
            "winter": {"focus": "Heating and furnace", "budget_multiplier": 1.5},
            "spring": {"focus": "AC maintenance", "budget_multiplier": 1.2},
            "fall": {"focus": "Furnace tune-ups", "budget_multiplier": 1.2}
        }
    },
    "roofer": {
        "name": "Roofing Services",
        "icon": "fa-house-chimney",
        "color": "gray",
        "description": "Roof repair, replacement, and inspections",
        "keywords": [
            "roof repair near me",
            "roofing contractor",
            "roof replacement",
            "roof inspection",
            "storm damage repair",
            "shingle repair",
            "roof leak repair",
            "gutter installation",
            "emergency roof repair",
            "metal roofing"
        ],
        "negative_keywords": [
            "free", "diy", "how to", "jobs", "careers", "materials only"
        ],
        "ad_headlines": [
            "Expert Roof Repairs",
            "Storm Damage Specialists",
            "Free Roof Inspections",
            "Licensed & Insured Roofers",
            "Financing Available"
        ],
        "ad_descriptions": [
            "Protect your home with quality roofing. Free inspections, insurance claim assistance. Call today!",
            "Roof damage? We respond fast. Licensed contractors with 5-star ratings. Get a free quote."
        ],
        "review_response_templates": {
            "positive": "Thank you for trusting us with your roof, {name}! We're glad you're happy with the results. Your home is in good hands!",
            "negative": "We're sorry to hear about this, {name}. Your satisfaction matters to us. Please contact us so we can resolve this."
        }
    },
    "landscaper": {
        "name": "Landscaping Services",
        "icon": "fa-leaf",
        "color": "green",
        "description": "Lawn care, design, and maintenance",
        "keywords": [
            "landscaping near me",
            "lawn care service",
            "landscape design",
            "lawn mowing",
            "tree trimming",
            "mulching service",
            "sprinkler installation",
            "hardscaping",
            "garden design",
            "yard cleanup"
        ],
        "negative_keywords": [
            "free", "diy", "how to", "jobs", "careers", "equipment"
        ],
        "ad_headlines": [
            "Professional Landscaping",
            "Beautiful Yards Guaranteed",
            "Free Design Consultation",
            "Weekly Lawn Maintenance",
            "Transform Your Outdoor Space"
        ],
        "ad_descriptions": [
            "Create the yard of your dreams. Professional landscaping and lawn care. Free estimates!",
            "From weekly mowing to complete redesigns. Trusted by homeowners. Book today!"
        ],
        "review_response_templates": {
            "positive": "Thank you for the kind words, {name}! We love helping create beautiful outdoor spaces. Enjoy your yard!",
            "negative": "We're sorry your experience wasn't perfect, {name}. Please reach out so we can make things right."
        }
    },
    "cleaning": {
        "name": "Cleaning Services",
        "icon": "fa-broom",
        "color": "cyan",
        "description": "House cleaning, commercial cleaning",
        "keywords": [
            "house cleaning near me",
            "maid service",
            "deep cleaning service",
            "move out cleaning",
            "office cleaning",
            "carpet cleaning",
            "window cleaning",
            "commercial cleaning",
            "recurring cleaning",
            "one time cleaning"
        ],
        "negative_keywords": [
            "free", "jobs", "careers", "hiring", "products"
        ],
        "ad_headlines": [
            "Professional House Cleaning",
            "Trusted Cleaning Experts",
            "Book Online in 60 Seconds",
            "Background-Checked Cleaners",
            "Satisfaction Guaranteed"
        ],
        "ad_descriptions": [
            "Come home to a clean house. Professional, reliable, background-checked cleaners. Book now!",
            "From weekly cleaning to deep cleans. Flexible scheduling, honest pricing. Get a quote today!"
        ],
        "review_response_templates": {
            "positive": "Thank you so much, {name}! We're thrilled you loved our cleaning service. See you next time!",
            "negative": "We're sorry we didn't meet your expectations, {name}. Please contact us - we'd like to make it right."
        }
    },
    "pest_control": {
        "name": "Pest Control",
        "icon": "fa-bug",
        "color": "orange",
        "description": "Residential & commercial pest control",
        "keywords": [
            "pest control near me",
            "exterminator",
            "termite treatment",
            "bed bug treatment",
            "ant control",
            "rodent control",
            "mosquito control",
            "cockroach exterminator",
            "wildlife removal",
            "pest inspection"
        ],
        "negative_keywords": [
            "free", "diy", "home remedies", "jobs", "careers"
        ],
        "ad_headlines": [
            "Fast Pest Elimination",
            "Licensed Exterminators",
            "Same-Day Service",
            "Family & Pet Safe",
            "Guaranteed Results"
        ],
        "ad_descriptions": [
            "Get rid of pests for good. Licensed, eco-friendly treatments. Free inspections available!",
            "Don't let pests take over. Fast, effective, guaranteed pest control. Call now!"
        ],
        "review_response_templates": {
            "positive": "Thank you for the great review, {name}! We're glad we could help make your home pest-free. We appreciate your business!",
            "negative": "We're sorry about your experience, {name}. Pest issues can be tricky. Please contact us for a follow-up treatment."
        }
    },
    "garage_door": {
        "name": "Garage Door Services",
        "icon": "fa-warehouse",
        "color": "slate",
        "description": "Repair, installation, and maintenance",
        "keywords": [
            "garage door repair near me",
            "garage door installation",
            "garage door opener repair",
            "broken garage door spring",
            "garage door replacement",
            "emergency garage door repair",
            "garage door maintenance",
            "new garage door",
            "garage door cable repair",
            "garage door off track"
        ],
        "negative_keywords": [
            "free", "diy", "how to", "jobs", "careers", "parts only"
        ],
        "ad_headlines": [
            "Garage Door Repair Experts",
            "Same-Day Service Available",
            "Spring & Opener Specialists",
            "Licensed & Insured",
            "24/7 Emergency Repairs"
        ],
        "ad_descriptions": [
            "Broken garage door? We fix it fast. Springs, openers, cables - all repairs. Call now!",
            "New doors and repairs. Professional installation, honest pricing. Free estimates!"
        ],
        "review_response_templates": {
            "positive": "Thank you for the wonderful review, {name}! We're glad your garage door is working perfectly. Thanks for choosing us!",
            "negative": "We apologize for any issues, {name}. Please contact us so we can make sure your garage door works properly."
        }
    },
    "locksmith": {
        "name": "Locksmith Services",
        "icon": "fa-key",
        "color": "amber",
        "description": "Residential, commercial, automotive",
        "keywords": [
            "locksmith near me",
            "emergency locksmith",
            "car lockout service",
            "lock change",
            "rekey locks",
            "key duplication",
            "smart lock installation",
            "commercial locksmith",
            "safe opening",
            "lock repair"
        ],
        "negative_keywords": [
            "free", "diy", "how to", "jobs", "careers", "lock picks"
        ],
        "ad_headlines": [
            "24/7 Emergency Locksmith",
            "Locked Out? We Help Fast",
            "Licensed & Bonded",
            "15-Minute Response Time",
            "All Lock Types Serviced"
        ],
        "ad_descriptions": [
            "Locked out? We're there in 15 minutes. 24/7 emergency locksmith service. Call now!",
            "Home, car, business - we handle all locks. Licensed, fast, affordable. Get help now!"
        ],
        "review_response_templates": {
            "positive": "Thank you, {name}! We know being locked out is stressful, and we're glad we could help quickly. Thanks for choosing us!",
            "negative": "We're sorry about your experience, {name}. Please reach out so we can address your concerns."
        }
    },
    "general_contractor": {
        "name": "General Contractor",
        "icon": "fa-hard-hat",
        "color": "yellow",
        "description": "Remodeling, renovations, construction",
        "keywords": [
            "general contractor near me",
            "home remodeling",
            "kitchen remodel",
            "bathroom remodel",
            "home addition",
            "basement finishing",
            "deck building",
            "home renovation",
            "construction company",
            "handyman services"
        ],
        "negative_keywords": [
            "free", "diy", "jobs", "careers", "subcontractor"
        ],
        "ad_headlines": [
            "Licensed General Contractor",
            "Quality Home Remodeling",
            "Free Project Estimates",
            "Kitchen & Bath Experts",
            "Transform Your Home"
        ],
        "ad_descriptions": [
            "From kitchens to whole-home remodels. Licensed, insured, quality craftsmanship. Free estimates!",
            "Build your dream home. Expert contractors, transparent pricing. Schedule a consultation today!"
        ],
        "review_response_templates": {
            "positive": "Thank you for the amazing review, {name}! We loved working on your project. Enjoy your beautiful new space!",
            "negative": "We're sorry to hear this, {name}. Please contact us directly - we stand behind our work and want to make this right."
        }
    }
}


def get_preset(industry_key: str) -> Dict[str, Any]:
    """Get a specific industry preset."""
    return INDUSTRY_PRESETS.get(industry_key, {})


def get_all_presets() -> Dict[str, Dict[str, Any]]:
    """Get all industry presets."""
    return INDUSTRY_PRESETS


def apply_preset_to_account(aid: int, industry_key: str) -> bool:
    """
    Apply an industry preset to an account.
    Stores the selection and configures default settings.
    """
    preset = get_preset(industry_key)
    if not preset:
        return False

    try:
        with db.engine.connect() as conn:
            # Update account industry setting
            conn.execute(
                text("""
                    UPDATE accounts
                    SET industry = :industry,
                        industry_preset = :preset_key,
                        updated_at = NOW()
                    WHERE id = :aid
                """),
                {"aid": aid, "industry": preset["name"], "preset_key": industry_key}
            )
            conn.commit()
        return True
    except Exception as e:
        current_app.logger.error(f"Error applying preset: {e}")
        return False


# -------------------- Routes --------------------

@industry_bp.route("/", methods=["GET"])
@login_required
def index():
    """Show industry selection page."""
    presets = get_all_presets()
    return render_template(
        "industry_presets/index.html",
        presets=presets
    )


@industry_bp.route("/select/<industry_key>", methods=["POST"])
@login_required
def select_industry(industry_key: str):
    """Apply an industry preset to the current account."""
    aid = current_account_id()
    if not aid:
        return jsonify({"error": "Account not found"}), 404

    if apply_preset_to_account(aid, industry_key):
        flash(f"Industry preset applied! Your marketing is now optimized for {INDUSTRY_PRESETS[industry_key]['name']}.", "success")
        return redirect(url_for("daily_tasks_bp.index"))
    else:
        flash("Failed to apply preset. Please try again.", "error")
        return redirect(url_for("industry_bp.index"))


@industry_bp.route("/api/preset/<industry_key>", methods=["GET"])
@login_required
def api_get_preset(industry_key: str):
    """Get preset details via API."""
    preset = get_preset(industry_key)
    if not preset:
        return jsonify({"error": "Preset not found"}), 404
    return jsonify(preset)


@industry_bp.route("/api/keywords/<industry_key>", methods=["GET"])
@login_required
def api_get_keywords(industry_key: str):
    """Get keywords for an industry."""
    preset = get_preset(industry_key)
    if not preset:
        return jsonify({"error": "Preset not found"}), 404
    return jsonify({
        "keywords": preset.get("keywords", []),
        "negative_keywords": preset.get("negative_keywords", [])
    })
