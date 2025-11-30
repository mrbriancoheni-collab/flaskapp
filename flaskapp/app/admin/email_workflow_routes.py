# app/admin/email_workflow_routes.py
from __future__ import annotations
from datetime import datetime, timedelta
from typing import Optional
import logging

from flask import (
    Blueprint, request, render_template, redirect, url_for, flash, jsonify
)
from sqlalchemy import or_, desc

from app.extensions import db
from app.auth.decorators import require_admin_cloaked as require_admin
from app.models import (
    EmailTemplate, EmailWorkflow, WorkflowStep, ContactGroup,
    ContactGroupMember, WorkflowEnrollment, CRMContact, User
)

logger = logging.getLogger(__name__)

email_workflow_bp = Blueprint(
    "email_workflow_bp",
    __name__,
    url_prefix="/admin/email-workflows",
    template_folder="templates"
)


# ==========================================
# Contact Groups
# ==========================================
@email_workflow_bp.route("/groups")
@require_admin
def list_groups():
    """List all contact groups"""
    groups = ContactGroup.query.order_by(ContactGroup.name).all()

    # Get contact counts for each group
    group_stats = []
    for group in groups:
        group_stats.append({
            "group": group,
            "contact_count": group.contacts.count()
        })

    return render_template("admin/email_workflow/groups_list.html", group_stats=group_stats)


@email_workflow_bp.route("/groups/create", methods=["GET", "POST"])
@require_admin
def create_group():
    """Create a new contact group"""
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()

        if not name:
            flash("Group name is required", "error")
            return redirect(request.url)

        # Check for duplicate
        existing = ContactGroup.query.filter_by(name=name).first()
        if existing:
            flash(f"Group '{name}' already exists", "error")
            return redirect(request.url)

        group = ContactGroup(
            name=name,
            description=description or None
        )

        db.session.add(group)
        db.session.commit()

        flash(f"Contact group '{name}' created successfully", "success")
        return redirect(url_for("email_workflow_bp.list_groups"))

    return render_template("admin/email_workflow/group_form.html", group=None)


@email_workflow_bp.route("/groups/<int:group_id>/edit", methods=["GET", "POST"])
@require_admin
def edit_group(group_id: int):
    """Edit a contact group"""
    group = ContactGroup.query.get_or_404(group_id)

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()

        if not name:
            flash("Group name is required", "error")
            return redirect(request.url)

        # Check for duplicate (excluding current group)
        existing = ContactGroup.query.filter(
            ContactGroup.name == name,
            ContactGroup.id != group_id
        ).first()
        if existing:
            flash(f"Group '{name}' already exists", "error")
            return redirect(request.url)

        group.name = name
        group.description = description or None
        group.updated_at = datetime.utcnow()

        db.session.commit()

        flash(f"Contact group '{name}' updated successfully", "success")
        return redirect(url_for("email_workflow_bp.list_groups"))

    return render_template("admin/email_workflow/group_form.html", group=group)


@email_workflow_bp.route("/groups/<int:group_id>/delete", methods=["POST"])
@require_admin
def delete_group(group_id: int):
    """Delete a contact group"""
    group = ContactGroup.query.get_or_404(group_id)

    group_name = group.name
    db.session.delete(group)
    db.session.commit()

    flash(f"Contact group '{group_name}' deleted successfully", "success")
    return redirect(url_for("email_workflow_bp.list_groups"))


# ==========================================
# Email Templates
# ==========================================
@email_workflow_bp.route("/templates")
@require_admin
def list_templates():
    """List all email templates"""
    templates = EmailTemplate.query.order_by(desc(EmailTemplate.updated_at)).all()
    return render_template("admin/email_workflow/templates_list.html", templates=templates)


@email_workflow_bp.route("/templates/create", methods=["GET", "POST"])
@require_admin
def create_template():
    """Create a new email template"""
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        subject = request.form.get("subject", "").strip()
        body_html = request.form.get("body_html", "").strip()
        body_text = request.form.get("body_text", "").strip()
        is_active = request.form.get("is_active") == "on"

        if not name:
            flash("Template name is required", "error")
            return redirect(request.url)

        if not subject:
            flash("Subject is required", "error")
            return redirect(request.url)

        # Check for duplicate
        existing = EmailTemplate.query.filter_by(name=name).first()
        if existing:
            flash(f"Template '{name}' already exists", "error")
            return redirect(request.url)

        from flask import g
        template = EmailTemplate(
            name=name,
            description=description or None,
            subject=subject,
            body_html=body_html or None,
            body_text=body_text or None,
            is_active=is_active,
            created_by_user_id=g.user.id if hasattr(g, "user") else None
        )

        db.session.add(template)
        db.session.commit()

        flash(f"Email template '{name}' created successfully", "success")
        return redirect(url_for("email_workflow_bp.list_templates"))

    return render_template("admin/email_workflow/template_form.html", template=None)


@email_workflow_bp.route("/templates/<int:template_id>/edit", methods=["GET", "POST"])
@require_admin
def edit_template(template_id: int):
    """Edit an email template"""
    template = EmailTemplate.query.get_or_404(template_id)

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        subject = request.form.get("subject", "").strip()
        body_html = request.form.get("body_html", "").strip()
        body_text = request.form.get("body_text", "").strip()
        is_active = request.form.get("is_active") == "on"

        if not name:
            flash("Template name is required", "error")
            return redirect(request.url)

        if not subject:
            flash("Subject is required", "error")
            return redirect(request.url)

        # Check for duplicate (excluding current template)
        existing = EmailTemplate.query.filter(
            EmailTemplate.name == name,
            EmailTemplate.id != template_id
        ).first()
        if existing:
            flash(f"Template '{name}' already exists", "error")
            return redirect(request.url)

        template.name = name
        template.description = description or None
        template.subject = subject
        template.body_html = body_html or None
        template.body_text = body_text or None
        template.is_active = is_active
        template.updated_at = datetime.utcnow()

        db.session.commit()

        flash(f"Email template '{name}' updated successfully", "success")
        return redirect(url_for("email_workflow_bp.list_templates"))

    return render_template("admin/email_workflow/template_form.html", template=template)


@email_workflow_bp.route("/templates/<int:template_id>/delete", methods=["POST"])
@require_admin
def delete_template(template_id: int):
    """Delete an email template"""
    template = EmailTemplate.query.get_or_404(template_id)

    # Check if template is used in any workflows
    workflows_using = WorkflowStep.query.filter_by(email_template_id=template_id).count()
    if workflows_using > 0:
        flash(f"Cannot delete template '{template.name}' - it is used in {workflows_using} workflow(s)", "error")
        return redirect(url_for("email_workflow_bp.list_templates"))

    template_name = template.name
    db.session.delete(template)
    db.session.commit()

    flash(f"Email template '{template_name}' deleted successfully", "success")
    return redirect(url_for("email_workflow_bp.list_templates"))


# ==========================================
# Email Workflows
# ==========================================
@email_workflow_bp.route("/workflows")
@require_admin
def list_workflows():
    """List all email workflows"""
    workflows = EmailWorkflow.query.order_by(desc(EmailWorkflow.updated_at)).all()

    # Get stats for each workflow
    workflow_stats = []
    for wf in workflows:
        workflow_stats.append({
            "workflow": wf,
            "step_count": len(wf.steps),
            "active_enrollments": wf.enrollments.filter_by(status="active").count(),
            "total_enrollments": wf.enrollments.count()
        })

    return render_template("admin/email_workflow/workflows_list.html", workflow_stats=workflow_stats)


@email_workflow_bp.route("/workflows/create", methods=["GET", "POST"])
@require_admin
def create_workflow():
    """Create a new email workflow"""
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        is_active = request.form.get("is_active") == "on"
        target_group_ids = request.form.getlist("target_groups[]")

        if not name:
            flash("Workflow name is required", "error")
            return redirect(request.url)

        # Check for duplicate
        existing = EmailWorkflow.query.filter_by(name=name).first()
        if existing:
            flash(f"Workflow '{name}' already exists", "error")
            return redirect(request.url)

        from flask import g
        workflow = EmailWorkflow(
            name=name,
            description=description or None,
            is_active=is_active,
            target_groups=[int(gid) for gid in target_group_ids if gid] if target_group_ids else None,
            created_by_user_id=g.user.id if hasattr(g, "user") else None
        )

        db.session.add(workflow)
        db.session.commit()

        flash(f"Email workflow '{name}' created successfully", "success")
        return redirect(url_for("email_workflow_bp.edit_workflow", workflow_id=workflow.id))

    groups = ContactGroup.query.order_by(ContactGroup.name).all()
    return render_template("admin/email_workflow/workflow_form.html", workflow=None, groups=groups)


@email_workflow_bp.route("/workflows/<int:workflow_id>/edit", methods=["GET", "POST"])
@require_admin
def edit_workflow(workflow_id: int):
    """Edit an email workflow and its steps"""
    workflow = EmailWorkflow.query.get_or_404(workflow_id)

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        is_active = request.form.get("is_active") == "on"
        target_group_ids = request.form.getlist("target_groups[]")

        if not name:
            flash("Workflow name is required", "error")
            return redirect(request.url)

        # Check for duplicate (excluding current workflow)
        existing = EmailWorkflow.query.filter(
            EmailWorkflow.name == name,
            EmailWorkflow.id != workflow_id
        ).first()
        if existing:
            flash(f"Workflow '{name}' already exists", "error")
            return redirect(request.url)

        workflow.name = name
        workflow.description = description or None
        workflow.is_active = is_active
        workflow.target_groups = [int(gid) for gid in target_group_ids if gid] if target_group_ids else None
        workflow.updated_at = datetime.utcnow()

        db.session.commit()

        flash(f"Email workflow '{name}' updated successfully", "success")
        return redirect(request.url)

    groups = ContactGroup.query.order_by(ContactGroup.name).all()
    templates = EmailTemplate.query.filter_by(is_active=True).order_by(EmailTemplate.name).all()

    return render_template(
        "admin/email_workflow/workflow_form.html",
        workflow=workflow,
        groups=groups,
        templates=templates
    )


@email_workflow_bp.route("/workflows/<int:workflow_id>/delete", methods=["POST"])
@require_admin
def delete_workflow(workflow_id: int):
    """Delete an email workflow"""
    workflow = EmailWorkflow.query.get_or_404(workflow_id)

    workflow_name = workflow.name
    db.session.delete(workflow)
    db.session.commit()

    flash(f"Email workflow '{workflow_name}' deleted successfully", "success")
    return redirect(url_for("email_workflow_bp.list_workflows"))


# ==========================================
# Workflow Steps (AJAX)
# ==========================================
@email_workflow_bp.route("/workflows/<int:workflow_id>/steps/add", methods=["POST"])
@require_admin
def add_workflow_step(workflow_id: int):
    """Add a step to a workflow (AJAX)"""
    workflow = EmailWorkflow.query.get_or_404(workflow_id)

    template_id = request.form.get("template_id", type=int)
    delay_days = request.form.get("delay_days", type=int, default=0)
    delay_hours = request.form.get("delay_hours", type=int, default=0)

    # Conditional branching fields
    condition_type = request.form.get("condition_type", "none")
    condition_wait_hours = request.form.get("condition_wait_hours", type=int, default=24)
    alt_template_id = request.form.get("alt_template_id", type=int)
    condition_url = request.form.get("condition_url", "").strip()

    if not template_id:
        return jsonify({"success": False, "error": "Template ID is required"}), 400

    template = EmailTemplate.query.get(template_id)
    if not template:
        return jsonify({"success": False, "error": "Template not found"}), 404

    # Validate alternative template if provided
    alt_template = None
    if alt_template_id:
        alt_template = EmailTemplate.query.get(alt_template_id)
        if not alt_template:
            return jsonify({"success": False, "error": "Alternative template not found"}), 404

    # Get max step order
    max_order = db.session.query(db.func.max(WorkflowStep.step_order)).filter_by(workflow_id=workflow_id).scalar() or 0

    # Build condition_data
    condition_data = None
    if condition_type == "link_clicked" and condition_url:
        condition_data = {"url": condition_url}

    step = WorkflowStep(
        workflow_id=workflow_id,
        email_template_id=template_id,
        step_order=max_order + 1,
        delay_days=delay_days,
        delay_hours=delay_hours,
        condition_type=condition_type,
        condition_wait_hours=condition_wait_hours,
        alt_email_template_id=alt_template_id,
        condition_data=condition_data
    )

    db.session.add(step)
    db.session.commit()

    return jsonify({
        "success": True,
        "step": {
            "id": step.id,
            "order": step.step_order,
            "template_name": template.name,
            "template_subject": template.subject,
            "delay_days": step.delay_days,
            "delay_hours": step.delay_hours,
            "condition_type": step.condition_type,
            "condition_wait_hours": step.condition_wait_hours,
            "alt_template_name": alt_template.name if alt_template else None,
            "alt_template_id": alt_template_id
        }
    })


@email_workflow_bp.route("/workflows/steps/<int:step_id>/delete", methods=["POST"])
@require_admin
def delete_workflow_step(step_id: int):
    """Delete a workflow step (AJAX)"""
    step = WorkflowStep.query.get_or_404(step_id)
    workflow_id = step.workflow_id

    db.session.delete(step)

    # Reorder remaining steps
    remaining_steps = WorkflowStep.query.filter_by(workflow_id=workflow_id).order_by(WorkflowStep.step_order).all()
    for idx, s in enumerate(remaining_steps, start=1):
        s.step_order = idx

    db.session.commit()

    return jsonify({"success": True})


@email_workflow_bp.route("/workflows/steps/<int:step_id>/reorder", methods=["POST"])
@require_admin
def reorder_workflow_step(step_id: int):
    """Reorder a workflow step (AJAX)"""
    step = WorkflowStep.query.get_or_404(step_id)
    new_order = request.form.get("new_order", type=int)

    if not new_order:
        return jsonify({"success": False, "error": "New order is required"}), 400

    workflow_id = step.workflow_id
    old_order = step.step_order

    # Get all steps for this workflow
    steps = WorkflowStep.query.filter_by(workflow_id=workflow_id).order_by(WorkflowStep.step_order).all()

    # Remove the step being moved
    steps = [s for s in steps if s.id != step_id]

    # Insert at new position
    steps.insert(new_order - 1, step)

    # Update all orders
    for idx, s in enumerate(steps, start=1):
        s.step_order = idx

    db.session.commit()

    return jsonify({"success": True})
