# app/admin/routes.py
from __future__ import annotations
from datetime import datetime
from typing import Optional
import logging

from flask import (
    Blueprint, request, render_template, redirect, url_for, flash,
    session, g, current_app
)
from sqlalchemy import or_, desc

from app.extensions import db
from app.auth.session_helpers import login_required
from app.auth.decorators import require_admin_cloaked as require_admin
from app.models import Account, User, CRMContact, CRM_STAGES

logger = logging.getLogger(__name__)

# Try to import Subscription if your project has it
try:
    from app.models import Subscription  # optional
except Exception:
    Subscription = None  # type: ignore

admin_bp = Blueprint("admin_bp", __name__, url_prefix="/admin", template_folder="templates")


def _audit(
    action: str,
    *,
    target_user_id: Optional[int] = None,
    target_account_id: Optional[int] = None,
    note: str = ""
):
    """Write a best-effort admin audit entry without crashing the request."""
    try:
        from app.models import AdminAuditLog  # optional
        entry = AdminAuditLog(
            admin_user_id=getattr(g, "real_admin_user_id", None) or (g.user.id if getattr(g, "user", None) else None),
            action=action,
            target_user_id=target_user_id,
            target_account_id=target_account_id,
            note=(note or "")[:1000],
            created_at=datetime.utcnow(),
            ip=request.headers.get("X-Forwarded-For", request.remote_addr),
            user_agent=request.headers.get("User-Agent", ""),
        )
        db.session.add(entry)
        db.session.commit()
    except Exception:
        db.session.rollback()


def _recent_paid_accounts(limit: int = 8):
    """Return most-recent paid accounts via Subscription when present; else Account plan/plan_code/status."""
    paid_states = tuple(current_app.config.get("PAID_STRIPE_STATES", ("active", "trialing")))
    paid_plans = tuple(current_app.config.get("PAID_PLANS", ("pro", "team", "enterprise")))

    # Preferred: use Subscription if available
    if Subscription is not None and hasattr(Subscription, "status") and hasattr(Subscription, "account_id"):
        subs_q = (
            Subscription.query
            .filter(Subscription.status.in_(paid_states))
            .order_by(desc(getattr(Subscription, "updated_at", Subscription.id)))
        )
        subs = subs_q.limit(limit * 3).all()
        acct_ids = [getattr(s, "account_id", None) for s in subs if getattr(s, "account_id", None)]
        if acct_ids:
            return (
                Account.query.filter(Account.id.in_(acct_ids))
                .order_by(desc(Account.created_at))
                .limit(limit)
                .all()
            )

    # Fallback: rely on Account.* plan columns or status
    qry = Account.query
    if hasattr(Account, "plan"):
        qry = qry.filter(Account.plan.in_(paid_plans))
    elif hasattr(Account, "plan_code"):
        qry = qry.filter(Account.plan_code.in_(paid_plans))
    else:
        # last-resort heuristic
        if hasattr(Account, "status"):
            qry = qry.filter(Account.status == "active")

    return qry.order_by(desc(Account.created_at)).limit(limit).all()


def _primary_user_map(accounts):
    """Pick a likely primary user per account for display (owner/admin/first user)."""
    out = {}
    for a in accounts:
        try:
            users = User.query.filter_by(account_id=a.id).order_by(User.created_at.asc()).all()
            owner = next((u for u in users if getattr(u, "role", "") in ("owner", "admin")), None)
            out[a.id] = owner or (users[0] if users else None)
        except Exception:
            out[a.id] = None
    return out


# -------------------------
# Dashboard
# -------------------------
@admin_bp.get("/")
@login_required
@require_admin
def dashboard():
    accounts = Account.query.order_by(desc(Account.created_at)).limit(8).all()
    users = User.query.order_by(desc(User.created_at)).limit(8).all()

    subs_active = subs_canceled = None
    if Subscription is not None and hasattr(Subscription, "status"):
        subs_active = Subscription.query.filter(Subscription.status.in_(("active", "trialing"))).count()
        subs_canceled = Subscription.query.filter(Subscription.status == "canceled").count()

    paid_new = _recent_paid_accounts(limit=8)
    paid_new_primary_user = _primary_user_map(paid_new)

    return render_template(
        "admin/dashboard.html",
        accounts=accounts,
        users=users,
        subs_active=subs_active,
        subs_canceled=subs_canceled,
        paid_new=paid_new,
        paid_new_primary_user=paid_new_primary_user,
    )


# -------------------------
# Accounts
# -------------------------
@admin_bp.get("/accounts")
@login_required
@require_admin
def accounts():
    q = (request.args.get("q") or "").strip()
    qry = Account.query
    if q:
        cols = []
        for attr in ("name", "plan", "plan_code", "status"):
            if hasattr(Account, attr):
                cols.append(getattr(Account, attr).ilike(f"%{q}%"))
        if cols:
            qry = qry.filter(or_(*cols))

    page = max(int(request.args.get("page", 1)), 1)
    per = min(max(int(request.args.get("per", 25)), 1), 200)
    rows = qry.order_by(desc(Account.created_at)).paginate(page=page, per_page=per, error_out=False)
    return render_template("admin/accounts.html", rows=rows, q=q)


@admin_bp.get("/accounts/<int:account_id>")
@login_required
@require_admin
def account_detail(account_id: int):
    acct = Account.query.get_or_404(account_id)
    users = User.query.filter_by(account_id=acct.id).order_by(User.created_at.asc()).all()
    sub = None
    if Subscription is not None:
        sub = Subscription.query.filter_by(account_id=acct.id).order_by(
            desc(getattr(Subscription, "updated_at", Subscription.id)),
            desc(getattr(Subscription, "created_at", Subscription.id))
        ).first()
    return render_template("admin/account_detail.html", acct=acct, users=users, sub=sub)


# -------------------------
# Impersonation
# -------------------------
@admin_bp.post("/impersonate/<int:user_id>")
@login_required
@require_admin
def impersonate(user_id: int):
    user = User.query.get_or_404(user_id)
    if getattr(user, "role", "") == "admin":
        flash("Refusing to impersonate another admin.", "warning")
        return redirect(url_for("admin_bp.account_detail", account_id=user.account_id))
    session["impersonator_user_id"] = g.user.id
    session["impersonated_user_id"] = user.id
    session.modified = True
    _audit("impersonate_start", target_user_id=user.id, target_account_id=user.account_id)
    flash(f"You are now impersonating {user.email}.", "success")
    return redirect(url_for("account_bp.dashboard"))


@admin_bp.post("/stop-impersonation")
@login_required
def stop_impersonation():
    _audit("impersonate_stop", note=f"prev={session.get('impersonated_user_id')}")
    session.pop("impersonated_user_id", None)
    session.pop("impersonator_user_id", None)
    session.modified = True
    flash("Stopped impersonating.", "success")
    return redirect(url_for("admin_bp.dashboard"))


# -------------------------
# Audit Logs
# -------------------------
@admin_bp.get("/logs")
@login_required
@require_admin
def logs():
    try:
        from app.models import AdminAuditLog
    except Exception:
        flash("Audit log model missing.", "warning")
        return render_template("admin/logs.html", rows=None)

    page = max(int(request.args.get("page", 1)), 1)
    per = min(max(int(request.args.get("per", 50)), 1), 200)
    rows = AdminAuditLog.query.order_by(desc(AdminAuditLog.created_at)).paginate(page=page, per_page=per, error_out=False)
    return render_template("admin/logs.html", rows=rows)


# -------------------------
# Simple CRM
# -------------------------
@admin_bp.get("/crm")
@login_required
@require_admin
def crm_list():
    q = (request.args.get("q") or "").strip()
    stage = (request.args.get("stage") or "").strip()

    qry = CRMContact.query
    if q:
        like = f"%{q}%"
        qry = qry.filter(
            or_(
                CRMContact.business_name.ilike(like),
                CRMContact.contact_name.ilike(like),
                CRMContact.email.ilike(like),
                CRMContact.phone.ilike(like),
                CRMContact.domain.ilike(like),
                CRMContact.notes.ilike(like),
            )
        )
    if stage:
        qry = qry.filter(CRMContact.stage == stage)

    page = max(int(request.args.get("page", 1)), 1)
    per = min(max(int(request.args.get("per", 25)), 1), 200)
    rows = qry.order_by(desc(CRMContact.updated_at)).paginate(page=page, per_page=per, error_out=False)

    return render_template("admin/crm_list.html", rows=rows, q=q, stage=stage, stages=CRM_STAGES)


@admin_bp.get("/crm/new")
@login_required
@require_admin
def crm_new():
    return render_template("admin/crm_form.html", item=None, STAGES=CRM_STAGES)


@admin_bp.post("/crm/new")
@login_required
@require_admin
def crm_create():
    form = request.form
    item = CRMContact(
        stage=form.get("stage") or "stranger",
        business_name=form.get("business_name") or "",
        contact_name=form.get("contact_name") or "",
        email=form.get("email") or "",
        phone=form.get("phone") or "",
        domain=form.get("domain") or "",
        address1=form.get("address1") or "",
        address2=form.get("address2") or "",
        city=form.get("city") or "",
        region=form.get("region") or "",
        postal_code=form.get("postal_code") or "",
        country=form.get("country") or "",
        source=form.get("source") or "",
        notes=form.get("notes") or "",
        owner_user_id=int(form.get("owner_user_id")) if form.get("owner_user_id") else None,
        account_id=int(form.get("account_id")) if form.get("account_id") else None,
    )
    db.session.add(item)
    db.session.commit()
    _audit("crm_create", note=f"id={item.id} {item.business_name}")
    flash("Contact created.", "success")
    return redirect(url_for("admin_bp.crm_detail", contact_id=item.id))


@admin_bp.get("/crm/<int:contact_id>")
@login_required
@require_admin
def crm_detail(contact_id: int):
    from app.models import EmailSent, CompanyContact

    item = CRMContact.query.get_or_404(contact_id)

    # Get email history with tracking stats
    emails = (
        EmailSent.query
        .filter_by(crm_contact_id=contact_id)
        .order_by(desc(EmailSent.sent_at))
        .limit(50)
        .all()
    )

    # Get company contacts (team members)
    company_contacts = (
        CompanyContact.query
        .filter_by(crm_contact_id=contact_id)
        .order_by(CompanyContact.discovered_at.desc())
        .all()
    )

    return render_template(
        "admin/crm_detail.html",
        item=item,
        stages=CRM_STAGES,
        emails=emails,
        company_contacts=company_contacts
    )


@admin_bp.get("/crm/<int:contact_id>/edit")
@login_required
@require_admin
def crm_edit(contact_id: int):
    item = CRMContact.query.get_or_404(contact_id)
    return render_template("admin/crm_form.html", item=item, STAGES=CRM_STAGES)


@admin_bp.post("/crm/<int:contact_id>/edit")
@login_required
@require_admin
def crm_update(contact_id: int):
    item = CRMContact.query.get_or_404(contact_id)
    form = request.form

    item.stage = form.get("stage") or item.stage
    item.business_name = form.get("business_name") or item.business_name
    item.contact_name = form.get("contact_name") or item.contact_name
    item.email = form.get("email") or item.email
    item.phone = form.get("phone") or item.phone
    item.domain = form.get("domain") or item.domain
    item.address1 = form.get("address1") or item.address1
    item.address2 = form.get("address2") or item.address2
    item.city = form.get("city") or item.city
    item.region = form.get("region") or item.region
    item.postal_code = form.get("postal_code") or item.postal_code
    item.country = form.get("country") or item.country
    item.source = form.get("source") or item.source
    item.notes = form.get("notes") or item.notes
    item.owner_user_id = int(form.get("owner_user_id")) if form.get("owner_user_id") else item.owner_user_id
    item.account_id = int(form.get("account_id")) if form.get("account_id") else item.account_id

    db.session.commit()
    _audit("crm_update", note=f"id={item.id} {item.business_name}")
    flash("Contact updated.", "success")
    return redirect(url_for("admin_bp.crm_detail", contact_id=item.id))


# -------------------------
# SERP Scraper for Lead Generation
# -------------------------
@admin_bp.get("/serp-scraper")
@login_required
@require_admin
def serp_scraper():
    """Show the SERP scraper form"""
    return render_template("admin/serp_scraper.html")


@admin_bp.route("/serp-scraper/manual")
@login_required
@require_admin
def serp_scraper_manual():
    """Show the manual SERP import form"""
    return render_template("admin/serp_scraper_manual.html")


@admin_bp.post("/serp-scraper/manual/parse")
@login_required
@require_admin
def serp_scraper_manual_parse():
    """Parse manually pasted Google SERP HTML"""
    from app.services.serp_scraper import GoogleSerpScraper
    from bs4 import BeautifulSoup

    html_content = request.form.get("html_content", "").strip()
    service_type = request.form.get("service_type", "").strip()
    location = request.form.get("location", "").strip()
    auto_add = request.form.get("auto_add") == "on"

    if not html_content:
        flash("Please paste the Google search HTML.", "warning")
        return redirect(url_for("admin_bp.serp_scraper_manual"))

    if not service_type or not location:
        flash("Service type and location are required.", "warning")
        return redirect(url_for("admin_bp.serp_scraper_manual"))

    try:
        # Parse the HTML
        soup = BeautifulSoup(html_content, 'html.parser')

        # Use the scraper's extraction methods
        scraper = GoogleSerpScraper()

        # Extract LSA and PPC leads
        lsa_leads = scraper._extract_lsa(soup, location)
        ppc_leads = scraper._extract_ppc_ads(soup, location)

        leads = lsa_leads + ppc_leads

        current_app.logger.info(f"Manual SERP parse: found {len(leads)} leads (LSA: {len(lsa_leads)}, PPC: {len(ppc_leads)})")

        if not leads:
            flash("No advertiser leads found in the HTML. Make sure you copied the full page source including ads.", "warning")
            return redirect(url_for("admin_bp.serp_scraper_manual"))

        # Store results in session for review
        session["scraper_results"] = [
            {
                "business_name": lead.business_name,
                "domain": lead.domain,
                "phone": lead.phone,
                "city": lead.city,
                "region": lead.region,
                "source": lead.source,
                "ad_type": lead.ad_type,
                "snippet": lead.snippet,
            }
            for lead in leads
        ]
        session.modified = True

        # Auto-add to CRM if requested
        added_count = 0
        if auto_add:
            for lead in leads:
                # Check if already exists
                existing = None
                if lead.domain:
                    existing = CRMContact.query.filter_by(domain=lead.domain).first()
                if not existing and lead.business_name:
                    existing = CRMContact.query.filter_by(business_name=lead.business_name).first()

                if not existing:
                    contact = CRMContact(
                        business_name=lead.business_name or "Unknown",
                        domain=lead.domain,
                        phone=lead.phone,
                        city=lead.city,
                        region=lead.region,
                        source=f"{lead.source} ({service_type})",
                        stage="stranger",
                        notes=f"Ad Type: {lead.ad_type}\n{lead.snippet or ''}"
                    )
                    db.session.add(contact)
                    added_count += 1

            db.session.commit()
            _audit("serp_manual_import", note=f"service={service_type} location={location} added={added_count}")
            flash(f"Successfully imported {added_count} new leads to CRM.", "success")
        else:
            flash(f"Found {len(leads)} leads. Review below before adding to CRM.", "success")

        return render_template("admin/serp_results.html", leads=leads, auto_added=auto_add, added_count=added_count)

    except Exception as e:
        current_app.logger.error(f"Error parsing manual SERP HTML: {e}", exc_info=True)
        flash(f"Error parsing HTML: {str(e)}", "danger")
        return redirect(url_for("admin_bp.serp_scraper_manual"))


@admin_bp.post("/serp-scraper")
@login_required
@require_admin
def serp_scraper_run():
    """Run the SERP scraper and add results to CRM"""
    from app.services.serp_scraper import scrape_home_services
    import logging

    service_type = request.form.get("service_type", "").strip()
    location = request.form.get("location", "").strip()
    max_results = min(int(request.form.get("max_results", 20)), 50)
    auto_add = request.form.get("auto_add") == "on"

    if not service_type or not location:
        flash("Service type and location are required.", "warning")
        return redirect(url_for("admin_bp.serp_scraper"))

    try:
        # Set up detailed logging
        scraper_logger = logging.getLogger('app.services.serp_scraper')
        scraper_logger.setLevel(logging.DEBUG)

        current_app.logger.info(f"Starting SERP scrape: service={service_type}, location={location}, max={max_results}")

        # Run the scraper
        leads = scrape_home_services(service_type, location, max_results)

        current_app.logger.info(f"SERP scrape completed: found {len(leads)} leads")

        if not leads:
            # More helpful error message
            error_msg = f"No leads found for '{service_type}' in '{location}'. This could be due to:\n"
            error_msg += "• Google blocking the request (CAPTCHA)\n"
            error_msg += "• Google's HTML structure changed\n"
            error_msg += "• No results for this search term\n\n"
            error_msg += "Check application logs for details."
            flash(error_msg, "warning")
            current_app.logger.warning(f"SERP scraper returned 0 leads for: {service_type} {location}")
            return redirect(url_for("admin_bp.serp_scraper"))

        # Store results in session for review
        session["scraper_results"] = [
            {
                "business_name": lead.business_name,
                "domain": lead.domain,
                "phone": lead.phone,
                "city": lead.city,
                "region": lead.region,
                "source": lead.source,
                "ad_type": lead.ad_type,
                "snippet": lead.snippet,
            }
            for lead in leads
        ]
        session.modified = True

        # Auto-add to CRM if requested
        added_count = 0
        if auto_add:
            for lead in leads:
                # Check if already exists (by domain or business name)
                existing = None
                if lead.domain:
                    existing = CRMContact.query.filter_by(domain=lead.domain).first()
                if not existing and lead.business_name:
                    existing = CRMContact.query.filter_by(business_name=lead.business_name).first()

                if not existing:
                    contact = CRMContact(
                        business_name=lead.business_name or "Unknown",
                        domain=lead.domain,
                        phone=lead.phone,
                        city=lead.city,
                        region=lead.region,
                        source=f"{lead.source} ({service_type})",
                        stage="stranger",
                        notes=f"Ad Type: {lead.ad_type}\n{lead.snippet or ''}"
                    )
                    db.session.add(contact)
                    added_count += 1

            db.session.commit()
            _audit("serp_scrape", note=f"service={service_type} location={location} added={added_count}")
            flash(f"Found {len(leads)} leads, added {added_count} new contacts to CRM.", "success")
        else:
            flash(f"Found {len(leads)} leads. Review below before adding to CRM.", "success")

        return render_template("admin/serp_results.html", leads=leads, auto_added=auto_add, added_count=added_count)

    except Exception as e:
        logger.exception("Error running SERP scraper")
        flash(f"Error scraping: {str(e)}", "error")
        return redirect(url_for("admin_bp.serp_scraper"))


@admin_bp.post("/serp-scraper/add-selected")
@login_required
@require_admin
def serp_scraper_add_selected():
    """Add selected leads from scraper results to CRM"""
    selected_indices = request.form.getlist("selected")
    results = session.get("scraper_results", [])

    if not selected_indices or not results:
        flash("No leads selected.", "warning")
        return redirect(url_for("admin_bp.serp_scraper"))

    added_count = 0
    for idx_str in selected_indices:
        try:
            idx = int(idx_str)
            if 0 <= idx < len(results):
                lead = results[idx]

                # Check if already exists
                existing = None
                if lead.get("domain"):
                    existing = CRMContact.query.filter_by(domain=lead["domain"]).first()
                if not existing and lead.get("business_name"):
                    existing = CRMContact.query.filter_by(business_name=lead["business_name"]).first()

                if not existing:
                    contact = CRMContact(
                        business_name=lead.get("business_name") or "Unknown",
                        domain=lead.get("domain"),
                        phone=lead.get("phone"),
                        city=lead.get("city"),
                        region=lead.get("region"),
                        source=lead.get("source", "google_serp"),
                        stage="stranger",
                        notes=f"Ad Type: {lead.get('ad_type')}\n{lead.get('snippet', '')}"
                    )
                    db.session.add(contact)
                    added_count += 1

        except (ValueError, IndexError):
            continue

    db.session.commit()
    _audit("serp_add_selected", note=f"added={added_count}")

    # Clear session results
    session.pop("scraper_results", None)
    session.modified = True

    flash(f"Added {added_count} contacts to CRM.", "success")
    return redirect(url_for("admin_bp.crm_list"))


# -------------------------
# Domain Crawler for Lead Enrichment
# -------------------------
@admin_bp.route("/domain-crawler")
@login_required
@require_admin
def domain_crawler():
    """Domain crawler management page"""
    from app.models import CRMContact

    # Get stats
    total_contacts = CRMContact.query.filter(CRMContact.domain.isnot(None)).count()
    never_crawled = CRMContact.query.filter(
        CRMContact.domain.isnot(None),
        CRMContact.last_crawled_at.is_(None)
    ).count()

    # Get contacts missing contact info
    missing_email = CRMContact.query.filter(
        CRMContact.domain.isnot(None),
        CRMContact.email.is_(None)
    ).count()
    missing_phone = CRMContact.query.filter(
        CRMContact.domain.isnot(None),
        CRMContact.phone.is_(None)
    ).count()

    stats = {
        'total_contacts': total_contacts,
        'never_crawled': never_crawled,
        'missing_email': missing_email,
        'missing_phone': missing_phone
    }

    return render_template("admin/domain_crawler.html", stats=stats)


@admin_bp.post("/domain-crawler/crawl")
@login_required
@require_admin
def domain_crawler_run():
    """Run domain crawler on CRM contacts"""
    from app.models import CRMContact
    from app.services.domain_crawler import DomainCrawler
    from datetime import datetime, timedelta

    max_crawls = request.form.get("max_crawls", type=int, default=10)
    force_recrawl = request.form.get("force_recrawl", type=bool, default=False)

    try:
        # Get contacts to crawl
        query = CRMContact.query.filter(CRMContact.domain.isnot(None))

        if not force_recrawl:
            # Only crawl if:
            # 1. Never crawled before, OR
            # 2. Last crawled more than 30 days ago, OR
            # 3. Missing email or phone
            thirty_days_ago = datetime.utcnow() - timedelta(days=30)
            query = query.filter(
                db.or_(
                    CRMContact.last_crawled_at.is_(None),
                    CRMContact.last_crawled_at < thirty_days_ago,
                    CRMContact.email.is_(None),
                    CRMContact.phone.is_(None)
                )
            )

        contacts = query.limit(max_crawls).all()

        if not contacts:
            flash("No contacts need crawling at this time.", "info")
            return redirect(url_for("admin_bp.domain_crawler"))

        crawler = DomainCrawler()
        updated_count = 0
        enriched_fields = {'email': 0, 'phone': 0, 'name': 0}
        team_contacts_found = 0

        for contact in contacts:
            try:
                current_app.logger.info(f"Crawling domain: {contact.domain}")
                result = crawler.crawl_domain(contact.domain)

                # Update contact with found information
                updated = False
                if result['email'] and not contact.email:
                    contact.email = result['email']
                    enriched_fields['email'] += 1
                    updated = True

                if result['phone'] and not contact.phone:
                    contact.phone = result['phone']
                    enriched_fields['phone'] += 1
                    updated = True

                if result['name'] and not contact.contact_name:
                    contact.contact_name = result['name']
                    enriched_fields['name'] += 1
                    updated = True

                # Find team contacts (CEO, owner, marketing, etc.)
                team_contacts = crawler.find_team_contacts(contact.domain)
                if team_contacts:
                    from app.models import CompanyContact
                    for tc in team_contacts:
                        # Check if this contact already exists
                        existing = CompanyContact.query.filter_by(
                            crm_contact_id=contact.id,
                            full_name=tc['name']
                        ).first()

                        if not existing:
                            company_contact = CompanyContact(
                                crm_contact_id=contact.id,
                                full_name=tc['name'],
                                title=tc.get('title'),
                                email=tc.get('email'),
                                phone=tc.get('phone'),
                                role_category=tc.get('role_category'),
                                source=tc.get('source')
                            )
                            db.session.add(company_contact)
                            team_contacts_found += 1

                # Update crawl tracking
                contact.last_crawled_at = datetime.utcnow()
                contact.crawl_attempts += 1

                if updated:
                    updated_count += 1

            except Exception as e:
                current_app.logger.error(f"Error crawling {contact.domain}: {e}")
                contact.crawl_attempts += 1
                continue

        db.session.commit()
        _audit("domain_crawl", note=f"crawled={len(contacts)} enriched={updated_count} team_contacts={team_contacts_found}")

        msg = f"Crawled {len(contacts)} domains. "
        msg += f"Enriched {updated_count} contacts: "
        msg += f"{enriched_fields['email']} emails, {enriched_fields['phone']} phones, {enriched_fields['name']} names. "
        msg += f"Found {team_contacts_found} team contacts (CEO, owner, marketing, etc.)."
        flash(msg, "success")

    except Exception as e:
        current_app.logger.error(f"Domain crawler error: {e}", exc_info=True)
        flash(f"Error running crawler: {str(e)}", "danger")

    return redirect(url_for("admin_bp.domain_crawler"))


# -------------------------
# Email Functionality
# -------------------------
@admin_bp.get("/email/compose")
@login_required
@require_admin
def email_compose():
    """Show email composition form"""
    # Get contact_id or account_id from query params
    contact_id = request.args.get("contact_id", type=int)
    account_id = request.args.get("account_id", type=int)
    bulk = request.args.get("bulk", type=bool, default=False)

    recipient = None
    recipient_type = None

    if contact_id:
        recipient = CRMContact.query.get_or_404(contact_id)
        recipient_type = "contact"
    elif account_id:
        recipient = Account.query.get_or_404(account_id)
        recipient_type = "account"
    elif bulk:
        recipient_type = "bulk"

    # Get all CRM contacts for bulk email
    all_contacts = CRMContact.query.filter(CRMContact.email.isnot(None), CRMContact.email != "").order_by(CRMContact.business_name).all()

    return render_template(
        "admin/email_compose.html",
        recipient=recipient,
        recipient_type=recipient_type,
        all_contacts=all_contacts,
        bulk=bulk,
        stages=CRM_STAGES
    )


@admin_bp.post("/email/send")
@login_required
@require_admin
def email_send():
    """Send email to individual or multiple recipients"""
    from app.services.email_service import send_email, send_tracked_email_to_crm_contact, send_bulk_tracked_emails

    subject = request.form.get("subject", "").strip()
    message_body = request.form.get("message", "").strip()
    recipient_type = request.form.get("recipient_type", "")
    campaign_name = request.form.get("campaign_name", "").strip() or None  # Optional campaign name for bulk

    # Get logged-in user for sender info
    sent_by_user_id = g.user.id if hasattr(g, 'user') else None

    # Validation
    if not subject or not message_body:
        flash("Subject and message are required.", "error")
        return redirect(request.referrer or url_for("admin_bp.email_compose"))

    recipients = []

    try:
        if recipient_type == "contact":
            # Single CRM contact - use tracked email with user's email as sender
            contact_id = int(request.form.get("contact_id", 0))
            contact = CRMContact.query.get_or_404(contact_id)

            if not contact.email:
                flash(f"Contact {contact.business_name} has no email address.", "error")
                return redirect(url_for("admin_bp.crm_detail", contact_id=contact.id))

            # Create HTML email body
            html_body = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f9fafb;">
    <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f9fafb; padding: 40px 20px;">
        <tr>
            <td align="center">
                <table width="600" cellpadding="0" cellspacing="0" style="background-color: #ffffff; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
                    <!-- Content -->
                    <tr>
                        <td style="padding: 40px;">
                            <div style="white-space: pre-wrap; font-size: 16px; line-height: 24px; color: #111827;">
{message_body}
                            </div>
                        </td>
                    </tr>

                    <!-- Footer -->
                    <tr>
                        <td style="padding: 20px 40px; text-align: center; background-color: #f9fafb; border-radius: 0 0 8px 8px;">
                            <p style="margin: 0; font-size: 12px; color: #9ca3af;">
                                © 2025 FieldSprout. All rights reserved.
                            </p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>
            """

            # Send tracked email (will use logged-in user's email as sender)
            email_sent = send_tracked_email_to_crm_contact(
                crm_contact_id=contact_id,
                subject=subject,
                html_body=html_body,
                text_body=message_body,
                sent_by_user_id=sent_by_user_id,
                track_clicks=True
            )

            if email_sent and email_sent.delivered:
                flash(f"Email sent successfully to {contact.business_name}.", "success")
                _audit("email_sent", note=f"to={contact.email} subject={subject[:100]}")
                return redirect(url_for("admin_bp.crm_detail", contact_id=contact_id))
            else:
                flash(f"Failed to send email to {contact.business_name}. Check SMTP configuration.", "error")
                return redirect(url_for("admin_bp.crm_detail", contact_id=contact_id))

        elif recipient_type == "account":
            # All users in an account
            account_id = int(request.form.get("account_id", 0))
            account = Account.query.get_or_404(account_id)
            users = User.query.filter_by(account_id=account.id).all()

            for user in users:
                if user.email:
                    recipients.append({
                        "email": user.email,
                        "name": user.name
                    })

        elif recipient_type == "bulk":
            # Multiple CRM contacts - use bulk tracked emails with David credentials
            selected_contacts = request.form.getlist("selected_contacts")

            if not selected_contacts:
                flash("No recipients selected for bulk email.", "error")
                return redirect(url_for("admin_bp.email_compose", bulk=True))

            contact_ids = [int(cid) for cid in selected_contacts]

            # Create HTML email body
            html_body = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f9fafb;">
    <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f9fafb; padding: 40px 20px;">
        <tr>
            <td align="center">
                <table width="600" cellpadding="0" cellspacing="0" style="background-color: #ffffff; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
                    <!-- Content -->
                    <tr>
                        <td style="padding: 40px;">
                            <div style="white-space: pre-wrap; font-size: 16px; line-height: 24px; color: #111827;">
{message_body}
                            </div>
                        </td>
                    </tr>

                    <!-- Footer -->
                    <tr>
                        <td style="padding: 20px 40px; text-align: center; background-color: #f9fafb; border-radius: 0 0 8px 8px;">
                            <p style="margin: 0; font-size: 12px; color: #9ca3af;">
                                © 2025 FieldSprout. All rights reserved.
                            </p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>
            """

            # Default campaign name if not provided
            if not campaign_name:
                from datetime import datetime
                campaign_name = f"Bulk Email {datetime.now().strftime('%Y-%m-%d %H:%M')}"

            # Send bulk tracked emails (will use David credentials)
            results = send_bulk_tracked_emails(
                crm_contact_ids=contact_ids,
                subject=subject,
                html_body=html_body,
                text_body=message_body,
                campaign_name=campaign_name,
                sent_by_user_id=sent_by_user_id
            )

            # Flash message
            if results['sent'] > 0 and results['failed'] == 0:
                flash(f"Bulk email sent successfully to {results['sent']} recipient(s).", "success")
            elif results['sent'] > 0:
                flash(f"Email sent to {results['sent']} recipient(s). {results['failed']} failed.", "warning")
            else:
                flash(f"Failed to send email to all {results['failed']} recipient(s). Check SMTP configuration.", "error")

            _audit("bulk_email_sent", note=f"campaign={campaign_name} sent={results['sent']} failed={results['failed']}")
            return redirect(url_for("admin_bp.crm_list"))

        # For "account" recipient type (emails to internal users), send without tracking
        # These use the logged-in admin's email as sender
        if not recipients:
            flash("No valid email addresses found.", "error")
            return redirect(request.referrer or url_for("admin_bp.email_compose"))

        # Create HTML email body
        html_body = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f9fafb;">
    <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f9fafb; padding: 40px 20px;">
        <tr>
            <td align="center">
                <table width="600" cellpadding="0" cellspacing="0" style="background-color: #ffffff; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
                    <!-- Content -->
                    <tr>
                        <td style="padding: 40px;">
                            <div style="white-space: pre-wrap; font-size: 16px; line-height: 24px; color: #111827;">
{message_body}
                            </div>
                        </td>
                    </tr>

                    <!-- Footer -->
                    <tr>
                        <td style="padding: 20px 40px; text-align: center; background-color: #f9fafb; border-radius: 0 0 8px 8px;">
                            <p style="margin: 0; font-size: 12px; color: #9ca3af;">
                                © 2025 FieldSprout. All rights reserved.
                            </p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>
        """

        # Get sender email and name from logged-in user
        from_email = None
        from_name = None
        if hasattr(g, 'user') and g.user:
            from_email = g.user.email
            from_name = g.user.name

        # Send to all recipients (for account emails)
        success_count = 0
        failed_count = 0

        for recipient in recipients:
            try:
                result = send_email(
                    to=recipient["email"],
                    subject=subject,
                    html_body=html_body,
                    text_body=message_body,
                    from_email=from_email,
                    from_name=from_name
                )

                if result:
                    success_count += 1
                else:
                    failed_count += 1
                    logger.warning(f"Failed to send email to {recipient['email']}")

            except Exception as e:
                failed_count += 1
                logger.exception(f"Error sending email to {recipient['email']}: {e}")

        # Audit log
        _audit(
            "email_sent",
            note=f"type={recipient_type} from={from_email} count={success_count} failed={failed_count} subject={subject[:100]}"
        )

        # Flash message
        if success_count > 0 and failed_count == 0:
            flash(f"Email sent successfully to {success_count} recipient(s).", "success")
        elif success_count > 0:
            flash(f"Email sent to {success_count} recipient(s). {failed_count} failed.", "warning")
        else:
            flash(f"Failed to send email to all {failed_count} recipient(s). Check SMTP configuration.", "error")

        # Redirect based on type
        if recipient_type == "contact":
            contact_id = int(request.form.get("contact_id", 0))
            return redirect(url_for("admin_bp.crm_detail", contact_id=contact_id))
        elif recipient_type == "account":
            account_id = int(request.form.get("account_id", 0))
            return redirect(url_for("admin_bp.account_detail", account_id=account_id))
        else:
            return redirect(url_for("admin_bp.crm_list"))

    except Exception as e:
        logger.exception("Error sending email")
        flash(f"Error sending email: {str(e)}", "error")
        return redirect(request.referrer or url_for("admin_bp.email_compose"))


@admin_bp.get("/email/<int:email_id>")
@login_required
@require_admin
def email_detail(email_id: int):
    """View detailed email performance metrics"""
    from app.models import EmailSent, EmailOpen, EmailClick

    email = EmailSent.query.get_or_404(email_id)

    # Get all opens with details
    opens = (
        EmailOpen.query
        .filter_by(email_sent_id=email_id)
        .order_by(EmailOpen.opened_at.desc())
        .all()
    )

    # Get all clicks with details
    clicks = (
        EmailClick.query
        .filter_by(email_sent_id=email_id)
        .order_by(EmailClick.clicked_at.desc())
        .all()
    )

    # Calculate engagement metrics
    open_rate = 100.0 if email.was_opened else 0.0
    click_rate = (email.click_count / max(email.open_count, 1) * 100) if email.was_opened else 0.0

    return render_template(
        "admin/email_detail.html",
        email=email,
        opens=opens,
        clicks=clicks,
        open_rate=open_rate,
        click_rate=click_rate
    )

@admin_bp.get("/email-analytics")
@login_required
@require_admin
def email_analytics():
    """Email campaign analytics dashboard"""
    from app.models import EmailSent, EmailOpen, EmailClick
    from sqlalchemy import func

    # Overall stats
    total_emails = EmailSent.query.count()
    delivered_emails = EmailSent.query.filter_by(delivered=True).count()
    bounced_emails = EmailSent.query.filter_by(bounced=True).count()

    # Get emails with tracking stats
    emails_opened = EmailSent.query.filter(
        EmailSent.id.in_(
            db.session.query(EmailOpen.email_sent_id).distinct()
        )
    ).count()

    emails_clicked = EmailSent.query.filter(
        EmailSent.id.in_(
            db.session.query(EmailClick.email_sent_id).distinct()
        )
    ).count()

    total_opens = EmailOpen.query.count()
    total_clicks = EmailClick.query.count()

    # Calculate rates
    delivery_rate = (delivered_emails / total_emails * 100) if total_emails > 0 else 0
    open_rate = (emails_opened / delivered_emails * 100) if delivered_emails > 0 else 0
    click_rate = (emails_clicked / emails_opened * 100) if emails_opened > 0 else 0

    # Get campaign performance
    campaign_stats = (
        db.session.query(
            EmailSent.campaign_name,
            func.count(EmailSent.id).label('total'),
            func.sum(func.cast(EmailSent.delivered, db.Integer)).label('delivered'),
            func.sum(func.cast(EmailSent.bounced, db.Integer)).label('bounced')
        )
        .filter(EmailSent.campaign_name.isnot(None))
        .group_by(EmailSent.campaign_name)
        .order_by(desc('total'))
        .limit(20)
        .all()
    )

    # Get subject line performance (top 20)
    subject_performance = (
        db.session.query(
            EmailSent.subject,
            func.count(EmailSent.id).label('sent_count'),
            func.count(EmailOpen.id).label('open_count'),
            func.count(EmailClick.id).label('click_count')
        )
        .outerjoin(EmailOpen, EmailSent.id == EmailOpen.email_sent_id)
        .outerjoin(EmailClick, EmailSent.id == EmailClick.email_sent_id)
        .group_by(EmailSent.subject)
        .order_by(desc('open_count'))
        .limit(20)
        .all()
    )

    # Get recent emails
    recent_emails = (
        EmailSent.query
        .order_by(desc(EmailSent.sent_at))
        .limit(20)
        .all()
    )

    # Get best performing emails (by open rate)
    best_emails = []
    for email in EmailSent.query.filter_by(delivered=True).limit(100).all():
        if email.was_opened:
            best_emails.append({
                'email': email,
                'open_rate': 100.0,  # Single recipient, so 100% if opened
                'click_rate': (email.click_count / max(email.open_count, 1) * 100) if email.was_opened else 0
            })

    # Sort by click rate
    best_emails.sort(key=lambda x: x['click_rate'], reverse=True)
    best_emails = best_emails[:10]

    return render_template(
        "admin/email_analytics.html",
        total_emails=total_emails,
        delivered_emails=delivered_emails,
        bounced_emails=bounced_emails,
        emails_opened=emails_opened,
        emails_clicked=emails_clicked,
        total_opens=total_opens,
        total_clicks=total_clicks,
        delivery_rate=delivery_rate,
        open_rate=open_rate,
        click_rate=click_rate,
        campaign_stats=campaign_stats,
        subject_performance=subject_performance,
        recent_emails=recent_emails,
        best_emails=best_emails
    )


# =============================================================================
# User Flow Analytics
# =============================================================================

@admin_bp.get("/user-flow")
@login_required
@require_admin
def user_flow_analytics():
    """User flow and conversion funnel analytics dashboard"""
    from app.services.page_view_tracking import (
        get_popular_paths,
        get_common_user_flows,
        get_exit_pages,
        get_conversion_funnel_stats,
        get_device_breakdown,
        get_traffic_sources,
        get_pageviews_over_time,
        get_device_trend_over_time,
        get_hourly_traffic_pattern,
        get_top_landing_pages,
        get_average_session_duration,
    )
    from app.models import PageView
    from sqlalchemy import func
    from datetime import datetime, timedelta
    import json

    # Get time range from query params (default: last 7 days)
    range_param = request.args.get("range", "7d")

    # Parse range parameter (1d, 7d, 30d, 90d, 1y, all)
    if range_param == "1d":
        days = 1
        range_label = "Today"
        group_by = "hour"
    elif range_param == "7d":
        days = 7
        range_label = "Last 7 Days"
        group_by = "day"
    elif range_param == "30d":
        days = 30
        range_label = "Last 30 Days"
        group_by = "day"
    elif range_param == "90d":
        days = 90
        range_label = "Last 90 Days"
        group_by = "day"
    elif range_param == "1y":
        days = 365
        range_label = "Last Year"
        group_by = "month"
    elif range_param == "all":
        # Get days since first page view
        first_view = PageView.query.order_by(PageView.viewed_at.asc()).first()
        if first_view:
            days = (datetime.utcnow() - first_view.viewed_at).days + 1
        else:
            days = 7
        range_label = "All Time"
        group_by = "month" if days > 90 else "day"
    else:
        days = 7
        range_label = "Last 7 Days"
        group_by = "day"

    # Overall stats
    since = datetime.utcnow() - timedelta(days=days) if range_param != "all" else datetime(2020, 1, 1)
    total_pageviews = PageView.query.filter(PageView.viewed_at >= since).count()
    unique_sessions = db.session.query(func.count(func.distinct(PageView.session_id))).filter(
        PageView.viewed_at >= since
    ).scalar() or 0

    # Calculate average pages per session
    avg_pages_per_session = round(total_pageviews / unique_sessions, 2) if unique_sessions > 0 else 0

    # Average session duration
    avg_session_duration = get_average_session_duration(days=days)

    # Time series data for graphs
    pageviews_over_time = get_pageviews_over_time(days=days, group_by=group_by)
    device_trends = get_device_trend_over_time(days=days)
    hourly_pattern = get_hourly_traffic_pattern(days=days)

    # Popular paths
    popular_paths = get_popular_paths(days=days, limit=10)

    # Landing pages
    landing_pages = get_top_landing_pages(days=days, limit=10)

    # Common user flows (page to page transitions)
    user_flows = get_common_user_flows(days=days, limit=15)

    # Exit pages
    exit_pages = get_exit_pages(days=days, limit=10)

    # Conversion funnel (customize as needed)
    funnel_paths = ["/", "/pricing", "/signup", "/dashboard"]
    funnel_stats = get_conversion_funnel_stats(funnel_paths, days=days)

    # Device breakdown
    device_breakdown = get_device_breakdown(days=days)

    # Traffic sources
    traffic_sources = get_traffic_sources(days=days)

    # Recent page views for debugging
    recent_views = PageView.query.order_by(PageView.viewed_at.desc()).limit(20).all()

    return render_template(
        "admin/user_flow_analytics.html",
        range_param=range_param,
        range_label=range_label,
        days=days,
        total_pageviews=total_pageviews,
        unique_sessions=unique_sessions,
        avg_pages_per_session=avg_pages_per_session,
        avg_session_duration=avg_session_duration,
        popular_paths=popular_paths,
        landing_pages=landing_pages,
        user_flows=user_flows,
        exit_pages=exit_pages,
        funnel_stats=funnel_stats,
        device_breakdown=device_breakdown,
        traffic_sources=traffic_sources,
        recent_views=recent_views,
        # Graph data (JSON encoded for JavaScript)
        pageviews_over_time_json=json.dumps(pageviews_over_time),
        device_trends_json=json.dumps(device_trends),
        hourly_pattern_json=json.dumps(hourly_pattern),
    )


# =============================================================================
# ROI Settings & Pricing Management
# =============================================================================

@admin_bp.route("/roi-settings")
@login_required
@require_admin
def roi_settings():
    """View and edit ROI calculation parameters."""
    from app.models_roi_settings import ROISettings

    # Get settings by category
    improvement_rates = ROISettings.get_all_by_category('improvement_rates')
    pricing_settings = ROISettings.get_all_by_category('pricing')
    display_settings = ROISettings.get_all_by_category('display')

    return render_template(
        "admin/roi_settings.html",
        improvement_rates=improvement_rates,
        pricing_settings=pricing_settings,
        display_settings=display_settings
    )


@admin_bp.route("/roi-settings/update", methods=["POST"])
@login_required
@require_admin
def roi_settings_update():
    """Update ROI settings."""
    from app.models_roi_settings import ROISettings

    try:
        # Get all form fields that start with 'setting_'
        for key, value in request.form.items():
            if key.startswith('setting_'):
                setting_key = key.replace('setting_', '')
                ROISettings.set_value(setting_key, value, user_id=g.user.id)

        _audit("roi_settings_updated", note="Updated ROI calculation parameters")

        flash("ROI settings updated successfully!", "success")
    except Exception as e:
        logger.exception("Error updating ROI settings")
        flash(f"Error updating settings: {str(e)}", "error")

    return redirect(url_for("admin_bp.roi_settings"))


@admin_bp.route("/pricing-tiers")
@login_required
@require_admin
def pricing_tiers():
    """View and edit service pricing tiers."""
    from app.models_roi_settings import ServicePricing

    tiers = ServicePricing.query.order_by(ServicePricing.min_monthly_spend).all()

    return render_template(
        "admin/pricing_tiers.html",
        tiers=tiers
    )


@admin_bp.route("/pricing-tiers/<int:tier_id>/edit", methods=["GET", "POST"])
@login_required
@require_admin
def pricing_tier_edit(tier_id):
    """Edit a pricing tier."""
    from app.models_roi_settings import ServicePricing

    tier = ServicePricing.query.get_or_404(tier_id)

    if request.method == "POST":
        try:
            tier.tier_name = request.form.get("tier_name")
            tier.min_monthly_spend = int(request.form.get("min_monthly_spend", 0))
            max_spend = request.form.get("max_monthly_spend")
            tier.max_monthly_spend = int(max_spend) if max_spend else None
            tier.base_price = int(float(request.form.get("base_price", 0)) * 100)  # Convert to cents
            tier.percentage_of_savings = float(request.form.get("percentage_of_savings", 0)) / 100  # Convert to decimal
            tier.description = request.form.get("description")
            tier.is_active = request.form.get("is_active") == "on"

            db.session.commit()

            _audit("pricing_tier_updated", note=f"Updated tier: {tier.tier_name}")

            flash(f"Pricing tier '{tier.tier_name}' updated successfully!", "success")
            return redirect(url_for("admin_bp.pricing_tiers"))

        except Exception as e:
            logger.exception("Error updating pricing tier")
            flash(f"Error updating tier: {str(e)}", "error")

    return render_template(
        "admin/pricing_tier_edit.html",
        tier=tier
    )


@admin_bp.route("/pricing-tiers/new", methods=["GET", "POST"])
@login_required
@require_admin
def pricing_tier_new():
    """Create a new pricing tier."""
    from app.models_roi_settings import ServicePricing

    if request.method == "POST":
        try:
            tier = ServicePricing(
                tier_name=request.form.get("tier_name"),
                min_monthly_spend=int(request.form.get("min_monthly_spend", 0)),
                max_monthly_spend=int(request.form.get("max_monthly_spend")) if request.form.get("max_monthly_spend") else None,
                base_price=int(float(request.form.get("base_price", 0)) * 100),
                percentage_of_savings=float(request.form.get("percentage_of_savings", 0)) / 100,
                description=request.form.get("description"),
                is_active=request.form.get("is_active") == "on"
            )

            db.session.add(tier)
            db.session.commit()

            _audit("pricing_tier_created", note=f"Created tier: {tier.tier_name}")

            flash(f"Pricing tier '{tier.tier_name}' created successfully!", "success")
            return redirect(url_for("admin_bp.pricing_tiers"))

        except Exception as e:
            logger.exception("Error creating pricing tier")
            flash(f"Error creating tier: {str(e)}", "error")

    return render_template("admin/pricing_tier_edit.html", tier=None)


# =============================================================================
# Customer Impact & Marketing Success Metrics
# =============================================================================

@admin_bp.route("/marketing-success")
@login_required
@require_admin
def marketing_success():
    """Display aggregate customer impact metrics for marketing purposes."""
    from app.services.customer_impact_service import (
        get_aggregate_impact,
        get_top_performing_customers
    )
    from app.models_ads import CustomerImpact

    # Get aggregate metrics
    aggregate = get_aggregate_impact()

    # Get top performing customers
    top_customers = get_top_performing_customers(limit=20)

    # Get all customer impacts for detailed view
    all_impacts = (
        CustomerImpact.query
        .filter(CustomerImpact.total_savings > 0)
        .order_by(desc(CustomerImpact.updated_at))
        .all()
    )

    # Enhance with account names
    for impact in all_impacts:
        account = Account.query.get(impact.account_id)
        impact.account_name = account.name if account else 'Unknown'

    # Calculate some additional stats
    avg_savings_per_customer = aggregate['total_savings'] / aggregate['customer_count'] if aggregate['customer_count'] > 0 else 0
    avg_leads_per_customer = aggregate['total_additional_leads'] / aggregate['customer_count'] if aggregate['customer_count'] > 0 else 0

    return render_template(
        "admin/marketing_success.html",
        aggregate=aggregate,
        top_customers=top_customers,
        all_impacts=all_impacts,
        avg_savings_per_customer=round(avg_savings_per_customer, 2),
        avg_leads_per_customer=round(avg_leads_per_customer, 2)
    )


@admin_bp.route("/customer-impact/<int:account_id>")
@login_required
@require_admin
def customer_impact_detail(account_id: int):
    """View detailed customer impact metrics for a specific account."""
    from app.models_ads import CustomerImpact

    account = Account.query.get_or_404(account_id)
    impact = CustomerImpact.query.filter_by(account_id=account_id).first()

    return render_template(
        "admin/customer_impact_detail.html",
        account=account,
        impact=impact
    )


@admin_bp.route("/customer-impact/<int:account_id>/set-baseline", methods=["POST"])
@login_required
@require_admin
def set_customer_baseline(account_id: int):
    """Set baseline metrics for a customer."""
    from app.services.customer_impact_service import set_customer_baseline
    import datetime as dt

    try:
        start_date_str = request.form.get("start_date")
        end_date_str = request.form.get("end_date")

        if not start_date_str or not end_date_str:
            flash("Start date and end date are required.", "error")
            return redirect(url_for("admin_bp.customer_impact_detail", account_id=account_id))

        start_date = dt.datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = dt.datetime.strptime(end_date_str, '%Y-%m-%d').date()

        impact = set_customer_baseline(account_id, start_date, end_date)

        _audit("customer_baseline_set", target_account_id=account_id, note=f"Baseline set: {start_date} to {end_date}")

        flash(f"Baseline metrics set successfully! Monthly spend: ${impact.baseline_monthly_spend:.2f}, Monthly leads: {impact.baseline_monthly_leads:.1f}", "success")

    except Exception as e:
        logger.exception("Error setting customer baseline")
        flash(f"Error setting baseline: {str(e)}", "error")

    return redirect(url_for("admin_bp.customer_impact_detail", account_id=account_id))


@admin_bp.route("/customer-impact/<int:account_id>/update", methods=["POST"])
@login_required
@require_admin
def update_customer_impact_route(account_id: int):
    """Manually trigger update of customer impact calculations."""
    from app.services.customer_impact_service import update_customer_impact

    try:
        impact = update_customer_impact(account_id)

        _audit("customer_impact_updated", target_account_id=account_id)

        flash(f"Impact metrics updated! Savings: ${impact.total_savings:.2f}, Additional leads: {impact.total_additional_leads:.0f}", "success")

    except Exception as e:
        logger.exception("Error updating customer impact")
        flash(f"Error updating impact: {str(e)}", "error")

    return redirect(url_for("admin_bp.customer_impact_detail", account_id=account_id))


@admin_bp.route("/customer-impact/update-all", methods=["POST"])
@login_required
@require_admin
def update_all_customer_impacts_route():
    """Update impact calculations for all customers."""
    from app.services.customer_impact_service import update_all_customer_impacts

    try:
        result = update_all_customer_impacts()

        _audit("customer_impact_bulk_update", note=f"Updated {result['updated']} customers")

        flash(f"Updated {result['updated']} customers. Errors: {result['errors']}", "success")

    except Exception as e:
        logger.exception("Error updating all customer impacts")
        flash(f"Error: {str(e)}", "error")

    return redirect(url_for("admin_bp.marketing_success"))


# ===== AI PROMPTS MANAGEMENT =====

@admin_bp.route("/ai-prompts")
@require_admin
def ai_prompts():
    """View and manage all AI prompts."""
    try:
        from app.models_ads import AIPrompt
        prompts = AIPrompt.query.order_by(AIPrompt.prompt_key).all()
        _audit("ai_prompts_view")
        return render_template("admin/ai_prompts.html", prompts=prompts)
    except Exception as e:
        logger.exception("Error loading AI prompts")
        flash(f"Error loading prompts: {str(e)}", "error")
        return redirect(url_for("admin_bp.dashboard"))


@admin_bp.route("/ai-prompts/<int:prompt_id>/edit", methods=["GET", "POST"])
@require_admin
def ai_prompt_edit(prompt_id: int):
    """Edit an AI prompt."""
    try:
        from app.models_ads import AIPrompt
        prompt = AIPrompt.query.get_or_404(prompt_id)

        if request.method == "POST":
            prompt.name = request.form.get("name", prompt.name)
            prompt.description = request.form.get("description", prompt.description)
            prompt.system_message = request.form.get("system_message", prompt.system_message)
            prompt.prompt_template = request.form.get("prompt_template", prompt.prompt_template)
            prompt.model = request.form.get("model", prompt.model)
            prompt.temperature = float(request.form.get("temperature", prompt.temperature))
            prompt.max_tokens = int(request.form.get("max_tokens", prompt.max_tokens))
            prompt.is_active = request.form.get("is_active") == "1"

            db.session.commit()
            _audit("ai_prompt_edit", note=f"Updated prompt {prompt.prompt_key}")
            flash(f"Prompt '{prompt.name}' updated successfully", "success")
            return redirect(url_for("admin_bp.ai_prompts"))

        return render_template("admin/ai_prompt_edit.html", prompt=prompt)

    except Exception as e:
        logger.exception("Error editing AI prompt")
        db.session.rollback()
        flash(f"Error: {str(e)}", "error")
        return redirect(url_for("admin_bp.ai_prompts"))


@admin_bp.route("/ai-prompts/initialize", methods=["POST"])
@require_admin
def ai_prompts_initialize():
    """Initialize missing AI prompts with defaults."""
    try:
        from app.services.ai_prompts_init import initialize_ai_prompts
        count = initialize_ai_prompts()
        _audit("ai_prompts_initialize", note=f"Initialized {count} prompts")
        flash(f"Initialized {count} missing prompts", "success")
    except Exception as e:
        logger.exception("Error initializing AI prompts")
        flash(f"Error initializing prompts: {str(e)}", "error")

    return redirect(url_for("admin_bp.ai_prompts"))
