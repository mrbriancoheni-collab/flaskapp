from __future__ import annotations

from flask import render_template

from app import db
from app.auth.utils import login_required, current_account_id
from app.integrations import integrations_hub_bp


def _build_sections(aid: int) -> list[dict]:
    # ── Section 1: Ad Platforms ──────────────────────────────────────────────

    try:
        from app.models import GoogleAdsAuth
        gads_auth = GoogleAdsAuth.query.filter_by(account_id=aid).first()
        gads_connected = bool(gads_auth)
    except Exception:
        gads_auth = None
        gads_connected = False

    try:
        from app.models_fbads import FBAccount
        fb_connected = bool(FBAccount.query.filter_by(account_id=aid).first())
    except Exception:
        fb_connected = False

    ad_platforms = {
        "title": "Ad Platforms",
        "description": "Where your customers come from",
        "icon": "fa-bullhorn",
        "integrations": [
            {
                "name": "Google Ads",
                "description": "Track clicks, automate bids, and see which keywords bring paying customers.",
                "icon": "fa-brands fa-google",
                "icon_color": "text-blue-500",
                "connected": gads_connected,
                "status_label": "Connected" if gads_connected else "Not connected",
                "manage_url": "/account/google/ads/",
                "connect_url": "/account/google/connect",
                "stat": None,
                "coming_soon": False,
            },
            {
                "name": "Facebook Ads",
                "description": "Connect your Facebook Ads account to track campaign performance.",
                "icon": "fa-brands fa-facebook",
                "icon_color": "text-blue-600",
                "connected": fb_connected,
                "status_label": "Connected" if fb_connected else "Not connected",
                "manage_url": "/account/fbads/",
                "connect_url": "/account/fbads/",
                "stat": None,
                "coming_soon": False,
            },
            {
                "name": "LinkedIn Ads",
                "description": "Track LinkedIn Ads campaigns alongside your other channels.",
                "icon": "fa-brands fa-linkedin",
                "icon_color": "text-blue-700",
                "connected": False,
                "status_label": "Coming soon",
                "manage_url": None,
                "connect_url": None,
                "stat": None,
                "coming_soon": True,
            },
        ],
    }

    # ── Section 2: CRM & Job Management ─────────────────────────────────────

    try:
        from app.models_skimmer import SkimmerAuth
        skimmer_connected = bool(SkimmerAuth.query.filter_by(account_id=aid).first())
    except Exception:
        skimmer_connected = False

    try:
        from app.models_crm import CRMConnection
        st_connected = bool(
            CRMConnection.query.filter_by(account_id=aid, provider="servicetitan").first()
        )
    except Exception:
        st_connected = False

    crm_section = {
        "title": "CRM & Job Management",
        "description": "Where your jobs and customer records live",
        "icon": "fa-briefcase",
        "integrations": [
            {
                "name": "Skimmer",
                "description": "Automatically track completed pool service jobs as Google Ads conversions and send review requests.",
                "icon": "fa-water",
                "icon_color": "text-cyan-500",
                "connected": skimmer_connected,
                "status_label": "Connected" if skimmer_connected else "Not connected",
                "manage_url": "/account/integrations/skimmer",
                "connect_url": "/account/integrations/skimmer",
                "stat": None,
                "coming_soon": False,
            },
            {
                "name": "ServiceTitan",
                "description": "Sync jobs and customers from ServiceTitan to attribute revenue to ad clicks.",
                "icon": "fa-wrench",
                "icon_color": "text-orange-500",
                "connected": st_connected,
                "status_label": "Connected" if st_connected else "Not connected",
                "manage_url": "/account/servicetitan/",
                "connect_url": "/account/servicetitan/",
                "stat": None,
                "coming_soon": False,
            },
            {
                "name": "Housecall Pro",
                "description": "Import jobs and customer data from Housecall Pro.",
                "icon": "fa-house",
                "icon_color": "text-green-500",
                "connected": False,
                "status_label": "Coming soon",
                "manage_url": None,
                "connect_url": None,
                "stat": None,
                "coming_soon": True,
            },
            {
                "name": "Jobber",
                "description": "Connect Jobber to track which ads turn into booked jobs.",
                "icon": "fa-clipboard-list",
                "icon_color": "text-yellow-500",
                "connected": False,
                "status_label": "Coming soon",
                "manage_url": None,
                "connect_url": None,
                "stat": None,
                "coming_soon": True,
            },
        ],
    }

    # ── Section 3: Call & Lead Tracking ─────────────────────────────────────

    try:
        from app.models_ads import OfflineConversionImport
        call_count = OfflineConversionImport.query.filter_by(account_id=aid).count()
        call_connected = call_count > 0
    except Exception:
        call_count = 0
        call_connected = False

    try:
        from app.models_skimmer import PhoneGclidMap, EmailGclidMap
        phone_count = PhoneGclidMap.query.filter_by(account_id=aid).count()
        email_count = EmailGclidMap.query.filter_by(account_id=aid).count()
        click_connected = (phone_count + email_count) > 0
        click_stat = f"{phone_count + email_count} clicks captured" if click_connected else None
    except Exception:
        click_connected = False
        click_stat = None

    try:
        from app.models_ads import OfflineConversionImport as OCI
        lead_form_connected = bool(
            OCI.query.filter_by(account_id=aid, conversion_name="Google Lead Form").first()
        )
    except Exception:
        lead_form_connected = False

    call_view_connected = gads_connected

    call_section = {
        "title": "Call & Lead Tracking",
        "description": "Close the loop between ads and actual customers",
        "icon": "fa-phone",
        "integrations": [
            {
                "name": "Phone Call Tracking",
                "description": "Track phone calls from Google Ads as conversions — even without a website form submission.",
                "icon": "fa-phone",
                "icon_color": "text-green-500",
                "connected": call_connected,
                "status_label": "Connected" if call_connected else "Not connected",
                "manage_url": "/account/google/ads/offline-conversions",
                "connect_url": "/account/google/ads/offline-conversions",
                "stat": f"{call_count} calls tracked" if call_connected else None,
                "coming_soon": False,
            },
            {
                "name": "Website Click Capture",
                "description": "A one-line script on your website captures Google Ad clicks so we can match them to jobs later.",
                "icon": "fa-code",
                "icon_color": "text-purple-500",
                "connected": click_connected,
                "status_label": "Connected" if click_connected else "Not connected",
                "manage_url": "/track/snippet",
                "connect_url": "/track/snippet",
                "stat": click_stat,
                "coming_soon": False,
            },
            {
                "name": "Google Lead Forms",
                "description": "When someone fills out a lead form directly in Google search results, we capture it automatically.",
                "icon": "fa-file-lines",
                "icon_color": "text-blue-500",
                "connected": lead_form_connected,
                "status_label": "Connected" if lead_form_connected else "Not connected",
                "manage_url": "/account/integrations/lead-forms",
                "connect_url": "/account/integrations/lead-forms",
                "stat": None,
                "coming_soon": False,
            },
            {
                "name": "Google Call View",
                "description": "Uses Google's own call reporting to match callers to ad clicks — no third-party tool needed.",
                "icon": "fa-chart-bar",
                "icon_color": "text-indigo-500",
                "connected": call_view_connected,
                "status_label": "Connected" if call_view_connected else "Not connected",
                "manage_url": "/account/google/ads/",
                "connect_url": "/account/google/connect",
                "stat": "Auto-synced with Google Ads" if call_view_connected else None,
                "coming_soon": False,
            },
        ],
    }

    # ── Section 4: Analytics & Reporting ────────────────────────────────────

    def _google_oauth_connected(product: str) -> bool:
        try:
            row = db.engine.connect().execute(
                db.text(
                    "SELECT id FROM google_oauth_tokens "
                    "WHERE account_id=:aid AND product=:p LIMIT 1"
                ),
                {"aid": aid, "p": product},
            ).mappings().first()
            return row is not None
        except Exception:
            return False

    ga_connected = _google_oauth_connected("ga")
    gsc_connected = _google_oauth_connected("gsc")
    gmb_connected = _google_oauth_connected("gmb")

    analytics_section = {
        "title": "Analytics & Reporting",
        "description": "Understand what's working",
        "icon": "fa-chart-line",
        "integrations": [
            {
                "name": "Google Analytics",
                "description": "Pull website traffic data to see which campaigns drive sessions and conversions.",
                "icon": "fa-brands fa-google",
                "icon_color": "text-orange-500",
                "connected": ga_connected,
                "status_label": "Connected" if ga_connected else "Not connected",
                "manage_url": "/account/google/ga",
                "connect_url": "/account/google/ga",
                "stat": None,
                "coming_soon": False,
            },
            {
                "name": "Google Search Console",
                "description": "Track organic search rankings and clicks alongside your paid ad performance.",
                "icon": "fa-magnifying-glass-chart",
                "icon_color": "text-green-500",
                "connected": gsc_connected,
                "status_label": "Connected" if gsc_connected else "Not connected",
                "manage_url": "/account/google/gsc",
                "connect_url": "/account/google/gsc",
                "stat": None,
                "coming_soon": False,
            },
            {
                "name": "Google Business Profile",
                "description": "Sync your Google Business Profile to track reviews, calls, and direction requests.",
                "icon": "fa-location-dot",
                "icon_color": "text-red-500",
                "connected": gmb_connected,
                "status_label": "Connected" if gmb_connected else "Not connected",
                "manage_url": "/account/gmb/",
                "connect_url": "/account/gmb/",
                "stat": None,
                "coming_soon": False,
            },
        ],
    }

    # ── Section 5: Website ───────────────────────────────────────────────────

    try:
        from app.models_wp import WPSite
        wp_connected = bool(WPSite.query.filter_by(account_id=aid).first())
    except Exception:
        wp_connected = False

    website_section = {
        "title": "Website",
        "description": "Your online presence",
        "icon": "fa-globe",
        "integrations": [
            {
                "name": "WordPress",
                "description": "Connect your WordPress site to push content and track conversions directly.",
                "icon": "fa-brands fa-wordpress",
                "icon_color": "text-blue-700",
                "connected": wp_connected,
                "status_label": "Connected" if wp_connected else "Not connected",
                "manage_url": "/account/wp/",
                "connect_url": "/account/wp/",
                "stat": None,
                "coming_soon": False,
            },
        ],
    }

    # ── Section 6: Payments & Accounting ────────────────────────────────────

    payments_section = {
        "title": "Payments & Accounting",
        "description": "Know the true value of each customer",
        "icon": "fa-receipt",
        "integrations": [
            {
                "name": "QuickBooks",
                "description": "Sync invoice values so Google Ads knows the revenue each click generated.",
                "icon": "fa-book",
                "icon_color": "text-green-600",
                "connected": False,
                "status_label": "Coming soon",
                "manage_url": None,
                "connect_url": None,
                "stat": None,
                "coming_soon": True,
            },
            {
                "name": "Stripe",
                "description": "Automatically import payment values to measure true return on ad spend.",
                "icon": "fa-credit-card",
                "icon_color": "text-purple-600",
                "connected": False,
                "status_label": "Coming soon",
                "manage_url": None,
                "connect_url": None,
                "stat": None,
                "coming_soon": True,
            },
        ],
    }

    return [
        ad_platforms,
        crm_section,
        call_section,
        analytics_section,
        website_section,
        payments_section,
    ]


@integrations_hub_bp.get("/")
@login_required
def hub():
    aid = current_account_id()
    sections = _build_sections(aid)

    all_integrations = [i for s in sections for i in s["integrations"]]
    non_coming_soon = [i for i in all_integrations if not i["coming_soon"]]
    connected_count = sum(1 for i in non_coming_soon if i["connected"])
    total_count = len(non_coming_soon)

    return render_template(
        "integrations/index.html",
        sections=sections,
        connected_count=connected_count,
        total_count=total_count,
    )
