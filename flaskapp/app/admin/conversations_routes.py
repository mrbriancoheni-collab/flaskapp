"""
Admin routes for viewing email conversations and AI auto-responses

Routes:
- /admin/conversations - List all active conversations
- /admin/conversations/<id> - View conversation thread
- /admin/conversations/alerts - Unread alerts dashboard
"""
from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from sqlalchemy import desc, and_, or_
from datetime import datetime, timedelta

from app import db
from app.auth.decorators import require_admin_cloaked as require_admin
from app.auth.session_helpers import login_required
from app.models_leads import EmailConversation, EmailConversationMessage, ConversationAlert, LeadContact, Lead

conversations_bp = Blueprint("conversations_bp", __name__, url_prefix="/admin/conversations")


@conversations_bp.route("/")
@login_required
@require_admin
def list_conversations():
    """List all email conversations with filters"""

    # Get filter parameters
    status = request.args.get('status', 'active')
    requires_human = request.args.get('requires_human')
    sentiment = request.args.get('sentiment')
    page = request.args.get('page', 1, type=int)
    per_page = 25

    # Build query
    query = EmailConversation.query

    if status and status != 'all':
        query = query.filter(EmailConversation.status == status)

    if requires_human == 'true':
        query = query.filter(EmailConversation.requires_human == True)
    elif requires_human == 'false':
        query = query.filter(EmailConversation.requires_human == False)

    if sentiment:
        query = query.filter(EmailConversation.last_sentiment == sentiment)

    # Order by most recent activity
    query = query.order_by(desc(EmailConversation.last_message_at))

    # Paginate
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    conversations = pagination.items

    # Get unread alerts count
    unread_alerts_count = ConversationAlert.query.filter_by(is_read=False).count()

    return render_template(
        "admin/conversations_list.html",
        conversations=conversations,
        pagination=pagination,
        status=status,
        requires_human=requires_human,
        sentiment=sentiment,
        unread_alerts_count=unread_alerts_count
    )


@conversations_bp.route("/<int:conversation_id>")
@login_required
@require_admin
def view_conversation(conversation_id: int):
    """View full conversation thread with all messages"""

    conversation = EmailConversation.query.get_or_404(conversation_id)

    # Get all messages in chronological order
    messages = EmailConversationMessage.query.filter_by(
        conversation_id=conversation_id
    ).order_by(EmailConversationMessage.created_at).all()

    # Mark related alerts as read
    ConversationAlert.query.filter(
        and_(
            ConversationAlert.conversation_id == conversation_id,
            ConversationAlert.is_read == False
        )
    ).update({'is_read': True, 'read_at': datetime.utcnow()})
    db.session.commit()

    return render_template(
        "admin/conversation_thread.html",
        conversation=conversation,
        messages=messages
    )


@conversations_bp.route("/alerts")
@login_required
@require_admin
def alerts_dashboard():
    """Dashboard showing unread conversation alerts"""

    # Get filter
    severity = request.args.get('severity', 'all')
    alert_type = request.args.get('type', 'all')
    show = request.args.get('show', 'unread')  # unread, all

    # Build query
    query = ConversationAlert.query

    if show == 'unread':
        query = query.filter(ConversationAlert.is_read == False)

    if severity != 'all':
        query = query.filter(ConversationAlert.severity == severity)

    if alert_type != 'all':
        query = query.filter(ConversationAlert.alert_type == alert_type)

    # Order by most recent
    alerts = query.order_by(desc(ConversationAlert.created_at)).limit(100).all()

    # Group by severity for dashboard
    urgent_count = ConversationAlert.query.filter_by(is_read=False, severity='urgent').count()
    warning_count = ConversationAlert.query.filter_by(is_read=False, severity='warning').count()
    info_count = ConversationAlert.query.filter_by(is_read=False, severity='info').count()

    return render_template(
        "admin/conversation_alerts.html",
        alerts=alerts,
        urgent_count=urgent_count,
        warning_count=warning_count,
        info_count=info_count,
        severity=severity,
        alert_type=alert_type,
        show=show
    )


@conversations_bp.route("/alerts/<int:alert_id>/mark-read", methods=["POST"])
@login_required
@require_admin
def mark_alert_read(alert_id: int):
    """Mark alert as read"""

    alert = ConversationAlert.query.get_or_404(alert_id)
    alert.is_read = True
    alert.read_at = datetime.utcnow()
    db.session.commit()

    return jsonify({'success': True})


@conversations_bp.route("/alerts/mark-all-read", methods=["POST"])
@login_required
@require_admin
def mark_all_alerts_read():
    """Mark all alerts as read"""

    ConversationAlert.query.filter_by(is_read=False).update({
        'is_read': True,
        'read_at': datetime.utcnow()
    })
    db.session.commit()

    flash("All alerts marked as read", "success")
    return redirect(url_for('conversations_bp.alerts_dashboard'))


@conversations_bp.route("/<int:conversation_id>/escalate", methods=["POST"])
@login_required
@require_admin
def escalate_conversation(conversation_id: int):
    """Manually escalate conversation to human"""

    conversation = EmailConversation.query.get_or_404(conversation_id)
    conversation.requires_human = True
    conversation.status = 'escalated'
    conversation.escalated_at = datetime.utcnow()
    db.session.commit()

    flash("Conversation escalated - AI will not auto-respond", "info")
    return redirect(url_for('conversations_bp.view_conversation', conversation_id=conversation_id))


@conversations_bp.route("/<int:conversation_id>/close", methods=["POST"])
@login_required
@require_admin
def close_conversation(conversation_id: int):
    """Close conversation"""

    conversation = EmailConversation.query.get_or_404(conversation_id)
    conversation.status = 'closed'
    db.session.commit()

    flash("Conversation closed", "success")
    return redirect(url_for('conversations_bp.list_conversations'))


@conversations_bp.route("/stats")
@login_required
@require_admin
def conversation_stats():
    """Get conversation statistics for dashboard widget"""

    # Last 7 days stats
    seven_days_ago = datetime.utcnow() - timedelta(days=7)

    total_conversations = EmailConversation.query.filter(
        EmailConversation.created_at >= seven_days_ago
    ).count()

    ai_responses = EmailConversationMessage.query.filter(
        and_(
            EmailConversationMessage.is_ai_generated == True,
            EmailConversationMessage.sent_at >= seven_days_ago
        )
    ).count()

    escalated = EmailConversation.query.filter(
        and_(
            EmailConversation.requires_human == True,
            EmailConversation.escalated_at >= seven_days_ago
        )
    ).count()

    unread_alerts = ConversationAlert.query.filter_by(is_read=False).count()

    positive_sentiment = EmailConversation.query.filter(
        and_(
            EmailConversation.last_sentiment == 'positive',
            EmailConversation.last_message_at >= seven_days_ago
        )
    ).count()

    interested = EmailConversation.query.filter(
        and_(
            EmailConversation.last_sentiment == 'interested',
            EmailConversation.last_message_at >= seven_days_ago
        )
    ).count()

    return jsonify({
        'total_conversations_7d': total_conversations,
        'ai_responses_7d': ai_responses,
        'escalated_7d': escalated,
        'unread_alerts': unread_alerts,
        'positive_sentiment_7d': positive_sentiment,
        'interested_7d': interested
    })
