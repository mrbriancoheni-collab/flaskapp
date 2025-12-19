"""
Email Webhook Endpoints - Receive inbound email replies from Brevo/Mailgun

Routes:
- /api/email/brevo-webhook - Brevo inbound webhook
- /api/email/mailgun-webhook - Mailgun inbound webhook
"""
from flask import Blueprint, request, jsonify, current_app
import logging

logger = logging.getLogger(__name__)

email_webhook_bp = Blueprint("email_webhook_bp", __name__, url_prefix="/api/email")


@email_webhook_bp.route("/brevo-webhook", methods=["POST"])
def brevo_inbound_webhook():
    """
    Handle inbound emails from Brevo webhook

    Brevo sends webhook when prospect replies to our emails
    Documentation: https://developers.brevo.com/docs/inbound-webhooks
    """
    try:
        data = request.json or request.form.to_dict()

        logger.info(f"Received Brevo webhook: {data.get('event', 'unknown')}")

        # Brevo webhook format
        event_type = data.get('event')

        if event_type != 'inbound_email':
            return jsonify({'status': 'ignored', 'reason': f'Not an inbound email: {event_type}'}), 200

        # Extract email details
        from_email = data.get('sender', {}).get('email') or data.get('from')
        to_email = data.get('to', {}).get('email') or data.get('recipient')
        subject = data.get('subject', '')
        body_text = data.get('body', '') or data.get('text', '')
        body_html = data.get('html', '')
        message_id = data.get('message_id') or data.get('MessageID')
        in_reply_to = data.get('in_reply_to') or data.get('InReplyTo')
        references = data.get('references') or data.get('References')

        if not from_email or not body_text:
            logger.warning("Brevo webhook missing required fields")
            return jsonify({'status': 'error', 'message': 'Missing required fields'}), 400

        # Process the inbound reply
        from app.services.ai_conversation_service import AIConversationService

        service = AIConversationService()
        result = service.process_inbound_reply(
            from_email=from_email,
            to_email=to_email,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            message_id=message_id,
            in_reply_to=in_reply_to,
            references=references
        )

        if result['success']:
            logger.info(f"Successfully processed Brevo inbound email from {from_email}")
            return jsonify({
                'status': 'success',
                'conversation_id': result.get('conversation_id'),
                'response_sent': result.get('response_sent'),
                'requires_human': result.get('requires_human')
            }), 200
        else:
            logger.error(f"Failed to process Brevo inbound email: {result.get('message')}")
            return jsonify({
                'status': 'error',
                'message': result.get('message')
            }), 500

    except Exception as e:
        logger.error(f"Error processing Brevo webhook: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


@email_webhook_bp.route("/mailgun-webhook", methods=["POST"])
def mailgun_inbound_webhook():
    """
    Handle inbound emails from Mailgun webhook

    Mailgun sends webhook when prospect replies to our emails
    Documentation: https://documentation.mailgun.com/en/latest/user_manual.html#receiving-messages
    """
    try:
        # Mailgun sends form data, not JSON
        data = request.form.to_dict()

        logger.info(f"Received Mailgun webhook from {data.get('sender', 'unknown')}")

        # Extract email details (Mailgun format)
        from_email = data.get('sender') or data.get('from')
        to_email = data.get('recipient') or data.get('To')
        subject = data.get('subject', '') or data.get('Subject', '')
        body_text = data.get('body-plain', '') or data.get('stripped-text', '')
        body_html = data.get('body-html', '') or data.get('stripped-html', '')
        message_id = data.get('Message-Id') or data.get('message-id')
        in_reply_to = data.get('In-Reply-To')
        references = data.get('References')

        if not from_email or not body_text:
            logger.warning("Mailgun webhook missing required fields")
            return jsonify({'status': 'error', 'message': 'Missing required fields'}), 400

        # Process the inbound reply
        from app.services.ai_conversation_service import AIConversationService

        service = AIConversationService()
        result = service.process_inbound_reply(
            from_email=from_email,
            to_email=to_email,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            message_id=message_id,
            in_reply_to=in_reply_to,
            references=references
        )

        if result['success']:
            logger.info(f"Successfully processed Mailgun inbound email from {from_email}")
            return jsonify({
                'status': 'success',
                'conversation_id': result.get('conversation_id'),
                'response_sent': result.get('response_sent'),
                'requires_human': result.get('requires_human')
            }), 200
        else:
            logger.error(f"Failed to process Mailgun inbound email: {result.get('message')}")
            return jsonify({
                'status': 'error',
                'message': result.get('message')
            }), 500

    except Exception as e:
        logger.error(f"Error processing Mailgun webhook: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


@email_webhook_bp.route("/test", methods=["GET"])
def test_webhook():
    """Test endpoint to verify webhooks are accessible"""
    return jsonify({
        'status': 'ok',
        'message': 'Email webhook endpoint is working',
        'endpoints': {
            'brevo': '/api/email/brevo-webhook',
            'mailgun': '/api/email/mailgun-webhook'
        }
    }), 200
