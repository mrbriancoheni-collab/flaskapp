"""
ServiceTitan Integration Admin Routes
Manages ServiceTitan CRM integration settings and data synchronization.
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, g
from datetime import datetime, timedelta

from app import db
from app.auth.session_helpers import require_admin
from app.models import (
    ServiceTitanConnection,
    ServiceTitanCustomer,
    ServiceTitanJob,
    ServiceTitanCapacity,
    ServiceTitanSyncLog
)
from app.services.servicetitan_service import ServiceTitanService


servicetitan_bp = Blueprint("servicetitan_bp", __name__, url_prefix="/admin/servicetitan")


@servicetitan_bp.route("/")
@require_admin
def dashboard():
    """ServiceTitan integration dashboard"""
    user = g.user
    account_id = user.account_id

    connection = ServiceTitanConnection.query.filter_by(account_id=account_id).first()

    # Get sync statistics
    recent_syncs = ServiceTitanSyncLog.query.filter_by(
        account_id=account_id
    ).order_by(ServiceTitanSyncLog.started_at.desc()).limit(10).all()

    # Get data counts
    customer_count = ServiceTitanCustomer.query.filter_by(account_id=account_id).count()
    job_count = ServiceTitanJob.query.filter_by(account_id=account_id).count()

    # Get recent capacity data
    recent_capacity = ServiceTitanCapacity.query.filter_by(
        account_id=account_id
    ).filter(
        ServiceTitanCapacity.capacity_date >= datetime.utcnow().date()
    ).order_by(ServiceTitanCapacity.capacity_date.asc()).limit(7).all()

    # Calculate current capacity score for ads optimization
    capacity_score = None
    budget_multiplier = None
    if connection:
        service = ServiceTitanService(account_id)
        budget_multiplier = service.get_capacity_based_budget_multiplier(days_ahead=7)

        if recent_capacity:
            avg_score = sum(float(c.capacity_score or 0) for c in recent_capacity) / len(recent_capacity)
            capacity_score = round(avg_score, 1)

    return render_template(
        "admin/servicetitan/dashboard.html",
        connection=connection,
        recent_syncs=recent_syncs,
        customer_count=customer_count,
        job_count=job_count,
        recent_capacity=recent_capacity,
        capacity_score=capacity_score,
        budget_multiplier=budget_multiplier
    )


@servicetitan_bp.route("/settings", methods=["GET", "POST"])
@require_admin
def settings():
    """Configure ServiceTitan API connection"""
    user = g.user
    account_id = user.account_id

    connection = ServiceTitanConnection.query.filter_by(account_id=account_id).first()

    if request.method == "POST":
        tenant_id = request.form.get("tenant_id", "").strip()
        client_id = request.form.get("client_id", "").strip()
        client_secret = request.form.get("client_secret", "").strip()
        app_key = request.form.get("app_key", "").strip()
        sync_frequency = request.form.get("sync_frequency", type=int, default=4)
        sync_enabled = request.form.get("sync_enabled") == "on"

        if not all([tenant_id, client_id, client_secret]):
            flash("Tenant ID, Client ID, and Client Secret are required", "error")
            return redirect(url_for("servicetitan_bp.settings"))

        if not connection:
            connection = ServiceTitanConnection(
                account_id=account_id,
                created_by_user_id=user.id
            )
            db.session.add(connection)

        connection.tenant_id = tenant_id
        connection.client_id = client_id
        connection.client_secret = client_secret  # TODO: Encrypt this!
        connection.app_key = app_key
        connection.sync_frequency_hours = sync_frequency
        connection.sync_enabled = sync_enabled
        connection.is_active = True

        db.session.commit()

        flash("ServiceTitan connection settings saved successfully", "success")
        return redirect(url_for("servicetitan_bp.dashboard"))

    return render_template(
        "admin/servicetitan/settings.html",
        connection=connection
    )


@servicetitan_bp.route("/test-connection", methods=["POST"])
@require_admin
def test_connection():
    """Test ServiceTitan API connection"""
    user = g.user
    account_id = user.account_id

    service = ServiceTitanService(account_id)
    result = service.test_connection()

    return jsonify(result)


@servicetitan_bp.route("/sync/customers", methods=["POST"])
@require_admin
def sync_customers():
    """Manually trigger customer data sync"""
    user = g.user
    account_id = user.account_id

    # Get optional start date from form
    days_back = request.form.get("days_back", type=int, default=30)
    start_date = datetime.utcnow() - timedelta(days=days_back)

    try:
        service = ServiceTitanService(account_id)
        stats = service.sync_customers(start_date=start_date)

        flash(
            f"Customer sync completed: {stats['fetched']} customers fetched, {stats['failed']} failed",
            "success"
        )
    except Exception as e:
        flash(f"Customer sync failed: {str(e)}", "error")

    return redirect(url_for("servicetitan_bp.dashboard"))


@servicetitan_bp.route("/sync/jobs", methods=["POST"])
@require_admin
def sync_jobs():
    """Manually trigger job data sync"""
    user = g.user
    account_id = user.account_id

    days_back = request.form.get("days_back", type=int, default=30)
    start_date = datetime.utcnow() - timedelta(days=days_back)

    try:
        service = ServiceTitanService(account_id)
        stats = service.sync_jobs(start_date=start_date)

        flash(
            f"Job sync completed: {stats['fetched']} jobs fetched, {stats['failed']} failed",
            "success"
        )
    except Exception as e:
        flash(f"Job sync failed: {str(e)}", "error")

    return redirect(url_for("servicetitan_bp.dashboard"))


@servicetitan_bp.route("/sync/capacity", methods=["POST"])
@require_admin
def sync_capacity():
    """Calculate capacity metrics for upcoming days"""
    user = g.user
    account_id = user.account_id

    days_ahead = request.form.get("days_ahead", type=int, default=14)

    try:
        service = ServiceTitanService(account_id)
        calculated = 0

        # Calculate capacity for each day
        for i in range(days_ahead):
            target_date = datetime.utcnow() + timedelta(days=i)
            service.calculate_capacity_metrics(target_date)
            calculated += 1

        flash(f"Capacity metrics calculated for {calculated} days", "success")
    except Exception as e:
        flash(f"Capacity calculation failed: {str(e)}", "error")

    return redirect(url_for("servicetitan_bp.dashboard"))


@servicetitan_bp.route("/customers")
@require_admin
def list_customers():
    """View synced customers"""
    user = g.user
    account_id = user.account_id

    page = request.args.get("page", 1, type=int)
    per_page = 50

    customers_query = ServiceTitanCustomer.query.filter_by(account_id=account_id)

    # Search filter
    search = request.args.get("search", "").strip()
    if search:
        customers_query = customers_query.filter(
            db.or_(
                ServiceTitanCustomer.name.ilike(f"%{search}%"),
                ServiceTitanCustomer.email.ilike(f"%{search}%"),
                ServiceTitanCustomer.phone.ilike(f"%{search}%")
            )
        )

    customers = customers_query.order_by(
        ServiceTitanCustomer.updated_at.desc()
    ).paginate(page=page, per_page=per_page, error_out=False)

    return render_template(
        "admin/servicetitan/customers.html",
        customers=customers,
        search=search
    )


@servicetitan_bp.route("/jobs")
@require_admin
def list_jobs():
    """View synced jobs"""
    user = g.user
    account_id = user.account_id

    page = request.args.get("page", 1, type=int)
    per_page = 50

    jobs_query = ServiceTitanJob.query.filter_by(account_id=account_id)

    # Status filter
    status = request.args.get("status", "").strip()
    if status:
        jobs_query = jobs_query.filter_by(job_status=status)

    # Date range filter
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    if start_date:
        jobs_query = jobs_query.filter(ServiceTitanJob.scheduled_date >= start_date)
    if end_date:
        jobs_query = jobs_query.filter(ServiceTitanJob.scheduled_date <= end_date)

    jobs = jobs_query.order_by(
        ServiceTitanJob.scheduled_date.desc()
    ).paginate(page=page, per_page=per_page, error_out=False)

    # Get unique statuses for filter dropdown
    statuses = db.session.query(ServiceTitanJob.job_status).filter_by(
        account_id=account_id
    ).distinct().all()
    statuses = [s[0] for s in statuses if s[0]]

    return render_template(
        "admin/servicetitan/jobs.html",
        jobs=jobs,
        statuses=statuses,
        selected_status=status,
        start_date=start_date,
        end_date=end_date
    )


@servicetitan_bp.route("/capacity")
@require_admin
def view_capacity():
    """View capacity metrics and forecasting"""
    user = g.user
    account_id = user.account_id

    # Get capacity data for next 30 days
    capacity_data = ServiceTitanCapacity.query.filter_by(
        account_id=account_id
    ).filter(
        ServiceTitanCapacity.capacity_date >= datetime.utcnow().date()
    ).order_by(ServiceTitanCapacity.capacity_date.asc()).limit(30).all()

    # Calculate recommendations
    service = ServiceTitanService(account_id)
    budget_multiplier = service.get_capacity_based_budget_multiplier(days_ahead=7)

    # Determine recommendation
    if budget_multiplier > 1.2:
        recommendation = "Increase ad spend - High available capacity"
        recommendation_class = "success"
    elif budget_multiplier < 0.8:
        recommendation = "Decrease ad spend - Low available capacity"
        recommendation_class = "warning"
    else:
        recommendation = "Maintain current ad spend - Normal capacity"
        recommendation_class = "info"

    return render_template(
        "admin/servicetitan/capacity.html",
        capacity_data=capacity_data,
        budget_multiplier=budget_multiplier,
        recommendation=recommendation,
        recommendation_class=recommendation_class
    )


@servicetitan_bp.route("/sync-logs")
@require_admin
def sync_logs():
    """View sync operation logs"""
    user = g.user
    account_id = user.account_id

    page = request.args.get("page", 1, type=int)
    per_page = 50

    logs = ServiceTitanSyncLog.query.filter_by(
        account_id=account_id
    ).order_by(
        ServiceTitanSyncLog.started_at.desc()
    ).paginate(page=page, per_page=per_page, error_out=False)

    return render_template(
        "admin/servicetitan/sync_logs.html",
        logs=logs
    )
