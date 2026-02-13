"""
Email Workflow Processor

Processes email workflows with conditional branching logic based on email engagement.
Checks for scheduled emails and sends them based on conditions (email opens, clicks, etc.)
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

from sqlalchemy import and_

from app.extensions import db
from app.models import (
    WorkflowEnrollment, WorkflowStep, EmailTemplate,
    EmailSent, EmailOpen, EmailClick, CRMContact
)

logger = logging.getLogger(__name__)


def process_workflow_enrollments(app, max_per_run: int = 100) -> int:
    """
    Process workflow enrollments that are due to send their next email.

    Args:
        app: Flask application instance
        max_per_run: Maximum number of enrollments to process in one run

    Returns:
        Number of emails sent
    """
    now = datetime.utcnow()

    # Find enrollments that are due to send next email
    due_enrollments = (
        WorkflowEnrollment.query
        .filter(
            WorkflowEnrollment.status == "active",
            WorkflowEnrollment.next_email_scheduled_at <= now
        )
        .order_by(WorkflowEnrollment.next_email_scheduled_at.asc())
        .limit(max_per_run)
        .all()
    )

    if not due_enrollments:
        logger.debug("[WORKFLOW] No enrollments due for processing")
        return 0

    logger.info(f"[WORKFLOW] Processing {len(due_enrollments)} due enrollments")

    emails_sent = 0
    for enrollment in due_enrollments:
        try:
            if _process_enrollment(app, enrollment):
                emails_sent += 1
        except Exception as e:
            logger.exception(f"[WORKFLOW] Error processing enrollment {enrollment.id}: {e}")

    return emails_sent


def _process_enrollment(app, enrollment: WorkflowEnrollment) -> bool:
    """
    Process a single workflow enrollment - send next email based on conditional logic.

    Returns:
        True if an email was sent, False otherwise
    """
    workflow = enrollment.workflow
    if not workflow or not workflow.is_active:
        logger.warning(f"[WORKFLOW] Enrollment {enrollment.id} has inactive workflow")
        enrollment.status = "paused"
        db.session.commit()
        return False

    # Get next step
    next_step_order = enrollment.current_step + 1
    next_step = WorkflowStep.query.filter_by(
        workflow_id=workflow.id,
        step_order=next_step_order
    ).first()

    if not next_step:
        # Workflow completed
        logger.info(f"[WORKFLOW] Enrollment {enrollment.id} completed workflow")
        enrollment.status = "completed"
        enrollment.completed_at = datetime.utcnow()
        enrollment.next_email_scheduled_at = None
        db.session.commit()
        return False

    # Determine which template to send based on conditional logic
    template_id = _determine_template_for_step(enrollment, next_step)
    if not template_id:
        logger.warning(f"[WORKFLOW] No template determined for enrollment {enrollment.id}, step {next_step_order}")
        return False

    template = EmailTemplate.query.get(template_id)
    if not template or not template.is_active:
        logger.warning(f"[WORKFLOW] Template {template_id} not found or inactive for enrollment {enrollment.id}")
        return False

    # Get contact
    contact = enrollment.crm_contact
    if not contact or not contact.email:
        logger.warning(f"[WORKFLOW] Contact {enrollment.crm_contact_id} has no email for enrollment {enrollment.id}")
        enrollment.status = "paused"
        db.session.commit()
        return False

    # Send email
    email_sent = _send_workflow_email(app, contact, template, enrollment, next_step)

    if email_sent:
        # Update enrollment
        enrollment.current_step = next_step_order
        enrollment.last_email_sent_at = datetime.utcnow()
        enrollment.last_email_sent_id = email_sent.id

        # Update step history
        if not enrollment.step_history:
            enrollment.step_history = []
        enrollment.step_history.append({
            "step_order": next_step_order,
            "template_id": template_id,
            "sent_at": datetime.utcnow().isoformat(),
            "condition_type": next_step.condition_type if next_step.condition_type != "none" else None
        })

        # Schedule next email
        _schedule_next_email(enrollment, workflow, next_step_order)

        db.session.commit()

        logger.info(
            f"[WORKFLOW] Sent email for enrollment {enrollment.id}, "
            f"step {next_step_order}, template {template_id} to {contact.email}"
        )
        return True

    return False


def _determine_template_for_step(enrollment: WorkflowEnrollment, step: WorkflowStep) -> Optional[int]:
    """
    Determine which template to send for a step based on conditional logic.

    Returns:
        Template ID to send, or None if conditions aren't met
    """
    # If no condition, use primary template
    if step.condition_type == "none" or step.step_order == 1:
        return step.email_template_id

    # Check condition based on previous email
    if not enrollment.last_email_sent_id:
        logger.warning(f"[WORKFLOW] No previous email for enrollment {enrollment.id} but condition required")
        return step.email_template_id  # Default to primary template

    condition_met = _check_condition(enrollment, step)

    # If condition is met, send primary template
    # If condition is NOT met and there's an alternative template, send that
    # If condition is NOT met and no alternative, send primary template
    if condition_met:
        logger.debug(f"[WORKFLOW] Condition '{step.condition_type}' met for enrollment {enrollment.id}")
        return step.email_template_id
    else:
        if step.alt_email_template_id:
            logger.debug(f"[WORKFLOW] Condition '{step.condition_type}' NOT met for enrollment {enrollment.id}, using alt template")
            return step.alt_email_template_id
        else:
            logger.debug(f"[WORKFLOW] Condition '{step.condition_type}' NOT met for enrollment {enrollment.id}, no alt template")
            return step.email_template_id


def _check_condition(enrollment: WorkflowEnrollment, step: WorkflowStep) -> bool:
    """
    Check if a condition is met for the enrollment.

    Returns:
        True if condition is met, False otherwise
    """
    if not enrollment.last_email_sent_id:
        return False

    if step.condition_type == "email_opened":
        # Check if the last email was opened
        opens_count = EmailOpen.query.filter_by(email_sent_id=enrollment.last_email_sent_id).count()
        return opens_count > 0

    elif step.condition_type == "email_not_opened":
        # Check if the last email was NOT opened
        opens_count = EmailOpen.query.filter_by(email_sent_id=enrollment.last_email_sent_id).count()
        return opens_count == 0

    elif step.condition_type == "link_clicked":
        # Check if any link (or specific link) was clicked
        url_filter = step.condition_data.get("url") if step.condition_data else None

        if url_filter:
            clicks_count = EmailClick.query.filter(
                EmailClick.email_sent_id == enrollment.last_email_sent_id,
                EmailClick.url.like(f"%{url_filter}%")
            ).count()
        else:
            clicks_count = EmailClick.query.filter_by(email_sent_id=enrollment.last_email_sent_id).count()

        return clicks_count > 0

    # Unknown condition type - default to False
    return False


def _send_workflow_email(
    app,
    contact: CRMContact,
    template: EmailTemplate,
    enrollment: WorkflowEnrollment,
    step: WorkflowStep
) -> Optional[EmailSent]:
    """
    Send an email for a workflow step.

    Returns:
        EmailSent record if sent successfully, None otherwise
    """
    try:
        # Import email service
        from app.services.email_service import send_tracked_email_to_crm_contact
        from jinja2 import Template

        # Prepare template variables
        # CRMContact uses contact_name (full name) and business_name
        contact_name = contact.contact_name or ""
        name_parts = contact_name.split() if contact_name else []
        first_name = name_parts[0] if name_parts else ""
        last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""

        template_vars = {
            "first_name": first_name,
            "last_name": last_name,
            "contact_name": contact_name,
            "email": contact.email or "",
            "company_name": contact.business_name or "",
            "business_name": contact.business_name or "",
            "phone": contact.phone or "",
        }

        # Render email template with variables
        subject = Template(template.subject).render(**template_vars) if template.subject else "Email from Workflow"

        html_body = None
        if template.body_html:
            html_body = Template(template.body_html).render(**template_vars)

        text_body = None
        if template.body_text:
            text_body = Template(template.body_text).render(**template_vars)

        # Send email and create EmailSent record
        email_sent = send_tracked_email_to_crm_contact(
            crm_contact_id=contact.id,
            subject=subject,
            html_body=html_body or text_body or "",
            text_body=text_body,
            campaign_name=f"Workflow: {enrollment.workflow.name}",
            sent_by_user_id=enrollment.enrolled_by_user_id,
            track_clicks=True
        )

        return email_sent

    except Exception as e:
        logger.exception(f"[WORKFLOW] Error sending email for enrollment {enrollment.id}: {e}")
        return None


def _schedule_next_email(enrollment: WorkflowEnrollment, workflow, current_step_order: int):
    """
    Schedule the next email for an enrollment.
    """
    # Get next step
    next_step = WorkflowStep.query.filter_by(
        workflow_id=workflow.id,
        step_order=current_step_order + 1
    ).first()

    if not next_step:
        # No more steps - workflow will complete on next processing
        enrollment.next_email_scheduled_at = datetime.utcnow()
        return

    # Calculate when to send next email
    # Use condition_wait_hours if this is a conditional step, otherwise use delay
    if next_step.condition_type != "none" and next_step.step_order > 1:
        # For conditional steps, wait the condition_wait_hours to check the condition
        wait_hours = next_step.condition_wait_hours
        delay = timedelta(hours=wait_hours)
    else:
        # For regular steps, use the configured delay
        delay = timedelta(days=next_step.delay_days, hours=next_step.delay_hours)

    enrollment.next_email_scheduled_at = datetime.utcnow() + delay
    logger.debug(
        f"[WORKFLOW] Scheduled next email for enrollment {enrollment.id} at "
        f"{enrollment.next_email_scheduled_at} (delay: {delay})"
    )
