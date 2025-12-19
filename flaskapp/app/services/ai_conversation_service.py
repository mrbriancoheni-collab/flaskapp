"""
AI Conversation Service - Auto-respond to prospect email replies

Handles:
- Analyzing incoming email sentiment and intent
- Generating context-aware AI responses
- Determining if human escalation is needed
- Creating conversation alerts
"""
import os
import logging
import re
from datetime import datetime
from typing import Dict, Optional, Tuple
import openai

from app.extensions import db
from app.models_leads import (
    EmailConversation,
    EmailConversationMessage,
    ConversationAlert,
    LeadContact,
    Lead
)

logger = logging.getLogger(__name__)


class AIConversationService:
    """Generate AI responses to prospect email replies"""

    def __init__(self):
        self.openai_api_key = os.getenv('OPENAI_API_KEY')
        if not self.openai_api_key:
            raise ValueError("OPENAI_API_KEY environment variable not set")

        openai.api_key = self.openai_api_key
        self.model = os.getenv('OPENAI_MODEL', 'gpt-4o-mini')

    def process_inbound_reply(
        self,
        from_email: str,
        to_email: str,
        subject: str,
        body_text: str,
        body_html: Optional[str] = None,
        message_id: Optional[str] = None,
        in_reply_to: Optional[str] = None,
        references: Optional[str] = None
    ) -> Dict:
        """
        Process an inbound email reply and generate AI response

        Returns:
            {
                'success': bool,
                'conversation_id': int,
                'response_sent': bool,
                'requires_human': bool,
                'message': str
            }
        """
        try:
            # 1. Find or create conversation
            conversation = self._find_or_create_conversation(
                from_email, to_email, subject, in_reply_to, references
            )

            if not conversation:
                return {
                    'success': False,
                    'message': 'Could not find associated lead/contact for this email'
                }

            # 2. Save inbound message
            inbound_message = self._save_inbound_message(
                conversation=conversation,
                from_email=from_email,
                to_email=to_email,
                subject=subject,
                body_text=body_text,
                body_html=body_html,
                message_id=message_id,
                in_reply_to=in_reply_to,
                references=references
            )

            # 3. Analyze sentiment and intent
            analysis = self._analyze_message(body_text, conversation)

            # Update conversation with analysis
            conversation.last_sentiment = analysis['sentiment']
            conversation.last_prospect_reply_at = datetime.utcnow()
            conversation.prospect_messages += 1
            conversation.total_messages += 1
            conversation.last_message_at = datetime.utcnow()

            # Update message with analysis
            inbound_message.sentiment = analysis['sentiment']
            inbound_message.contains_question = analysis['contains_question']
            inbound_message.urgency_level = analysis['urgency']

            db.session.commit()

            # 4. Determine if human escalation needed
            requires_human = self._should_escalate_to_human(analysis, conversation)

            if requires_human:
                conversation.requires_human = True
                conversation.status = 'escalated'
                conversation.escalated_at = datetime.utcnow()
                db.session.commit()

                # Create alert
                self._create_alert(
                    conversation=conversation,
                    alert_type='needs_human',
                    message=f"Prospect reply requires human attention: {analysis['reason_for_escalation']}",
                    severity='urgent'
                )

                return {
                    'success': True,
                    'conversation_id': conversation.id,
                    'response_sent': False,
                    'requires_human': True,
                    'message': 'Conversation escalated to human'
                }

            # 5. Generate AI response
            ai_response = self._generate_ai_response(
                conversation=conversation,
                inbound_message=inbound_message,
                analysis=analysis
            )

            if not ai_response['success']:
                # Failed to generate response - escalate
                conversation.requires_human = True
                conversation.status = 'escalated'
                db.session.commit()

                self._create_alert(
                    conversation=conversation,
                    alert_type='needs_human',
                    message=f"AI failed to generate response: {ai_response['error']}",
                    severity='urgent'
                )

                return {
                    'success': True,
                    'conversation_id': conversation.id,
                    'response_sent': False,
                    'requires_human': True,
                    'message': 'AI response generation failed - escalated to human'
                }

            # 6. Send AI response
            send_result = self._send_ai_response(
                conversation=conversation,
                response_text=ai_response['response'],
                prompt_used=ai_response['prompt'],
                confidence=ai_response['confidence']
            )

            if send_result['success']:
                # Update conversation
                conversation.last_ai_reply_at = datetime.utcnow()
                conversation.ai_messages += 1
                conversation.total_messages += 1
                conversation.last_message_at = datetime.utcnow()
                db.session.commit()

                # Create info alert
                self._create_alert(
                    conversation=conversation,
                    alert_type='new_reply',
                    message=f"AI responded to prospect ({analysis['sentiment']} sentiment)",
                    severity='info'
                )

            return {
                'success': True,
                'conversation_id': conversation.id,
                'response_sent': send_result['success'],
                'requires_human': False,
                'message': 'AI response sent successfully'
            }

        except Exception as e:
            logger.error(f"Error processing inbound reply: {e}", exc_info=True)
            return {
                'success': False,
                'message': str(e)
            }

    def _find_or_create_conversation(
        self,
        from_email: str,
        to_email: str,
        subject: str,
        in_reply_to: Optional[str],
        references: Optional[str]
    ) -> Optional[EmailConversation]:
        """Find existing conversation or create new one"""

        # Extract thread ID from references or in_reply_to
        thread_id = self._extract_thread_id(in_reply_to, references)

        # Try to find existing conversation by thread_id
        if thread_id:
            conversation = EmailConversation.query.filter_by(thread_id=thread_id).first()
            if conversation:
                return conversation

        # Try to find contact by email
        contact = LeadContact.query.filter_by(email=from_email).first()

        if not contact:
            logger.warning(f"No contact found for email: {from_email}")
            return None

        # Create new conversation
        conversation = EmailConversation(
            lead_contact_id=contact.id,
            thread_id=thread_id or f"thread-{contact.id}-{int(datetime.utcnow().timestamp())}",
            subject=subject,
            status='active',
            last_message_at=datetime.utcnow()
        )

        db.session.add(conversation)
        db.session.commit()

        logger.info(f"Created new conversation {conversation.id} for contact {contact.id}")

        return conversation

    def _extract_thread_id(self, in_reply_to: Optional[str], references: Optional[str]) -> Optional[str]:
        """Extract thread ID from email headers"""
        # Use in_reply_to as thread ID if available
        if in_reply_to:
            return in_reply_to.strip('<>')

        # Otherwise use first reference
        if references:
            refs = references.split()
            if refs:
                return refs[0].strip('<>')

        return None

    def _save_inbound_message(
        self,
        conversation: EmailConversation,
        from_email: str,
        to_email: str,
        subject: str,
        body_text: str,
        body_html: Optional[str],
        message_id: Optional[str],
        in_reply_to: Optional[str],
        references: Optional[str]
    ) -> EmailConversationMessage:
        """Save inbound message to database"""

        message = EmailConversationMessage(
            conversation_id=conversation.id,
            direction='inbound',
            from_email=from_email,
            to_email=to_email,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            message_id=message_id,
            in_reply_to=in_reply_to,
            references=references,
            received_at=datetime.utcnow()
        )

        db.session.add(message)
        db.session.commit()

        logger.info(f"Saved inbound message {message.id} to conversation {conversation.id}")

        return message

    def _analyze_message(self, body_text: str, conversation: EmailConversation) -> Dict:
        """Analyze message sentiment and intent using AI"""

        # Get conversation context
        contact = conversation.contact
        lead = contact.lead if contact else None

        context = f"""
Prospect: {contact.name if contact else 'Unknown'} ({contact.email if contact else 'Unknown'})
Company: {lead.company_name if lead else 'Unknown'}
Previous messages in thread: {conversation.total_messages}
Previous sentiment: {conversation.last_sentiment or 'Unknown'}
"""

        prompt = f"""Analyze this email reply from a prospect and provide:
1. Sentiment (positive, negative, neutral, interested, not_interested)
2. Contains question (yes/no)
3. Urgency level (low, medium, high, critical)
4. Should escalate to human (yes/no and why)
5. Key intent (what does the prospect want?)

Context:
{context}

Prospect's email:
{body_text}

Respond in JSON format:
{{
    "sentiment": "...",
    "contains_question": true/false,
    "urgency": "...",
    "escalate_to_human": true/false,
    "reason_for_escalation": "..." (if escalating),
    "intent": "..."
}}
"""

        try:
            response = openai.ChatCompletion.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are an expert at analyzing business emails and determining intent."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=500
            )

            import json
            analysis = json.loads(response.choices[0].message.content)

            return analysis

        except Exception as e:
            logger.error(f"Error analyzing message: {e}")
            # Return safe defaults
            return {
                'sentiment': 'neutral',
                'contains_question': '?' in body_text,
                'urgency': 'medium',
                'escalate_to_human': False,
                'intent': 'unclear'
            }

    def _should_escalate_to_human(self, analysis: Dict, conversation: EmailConversation) -> bool:
        """Determine if conversation should be escalated to human"""

        # Check AI analysis recommendation
        if analysis.get('escalate_to_human'):
            return True

        # Escalate if negative sentiment
        if analysis.get('sentiment') == 'negative':
            return True

        # Escalate if critical urgency
        if analysis.get('urgency') == 'critical':
            return True

        # Escalate if conversation has too many back-and-forths
        if conversation.total_messages > 10:
            return True

        # Escalate if prospect explicitly asks for human
        intent = analysis.get('intent', '').lower()
        if any(keyword in intent for keyword in ['speak to', 'talk to', 'human', 'person', 'manager']):
            return True

        return False

    def _generate_ai_response(
        self,
        conversation: EmailConversation,
        inbound_message: EmailConversationMessage,
        analysis: Dict
    ) -> Dict:
        """Generate AI response to prospect email"""

        # Get full conversation history
        previous_messages = EmailConversationMessage.query.filter_by(
            conversation_id=conversation.id
        ).order_by(EmailConversationMessage.created_at).limit(10).all()

        # Build conversation history
        history = []
        for msg in previous_messages:
            role = "assistant" if msg.direction == "outbound" else "user"
            history.append({
                "role": role,
                "content": msg.body_text[:1000]  # Limit to 1000 chars
            })

        # Get contact and lead info
        contact = conversation.contact
        lead = contact.lead if contact else None

        context = f"""
You are responding to: {contact.name or 'the prospect'} at {lead.company_name if lead else 'their company'}
Their sentiment: {analysis.get('sentiment')}
Their intent: {analysis.get('intent')}
Service they're interested in: {lead.company_name if lead else 'home services'}
"""

        system_prompt = f"""You are a helpful sales assistant for FieldSprout, a home services marketing platform.
You are responding to prospect email replies professionally and helpfully.

Guidelines:
- Be friendly, professional, and helpful
- Keep responses concise (2-3 paragraphs max)
- Answer their questions directly
- If they're interested, offer next steps (demo, call, etc.)
- If they're not interested, thank them politely
- Never be pushy or aggressive
- Use their name when appropriate
- Sign as "The FieldSprout Team"

Context:
{context}
"""

        try:
            response = openai.ChatCompletion.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    *history,
                    {"role": "user", "content": inbound_message.body_text}
                ],
                temperature=0.7,
                max_tokens=500
            )

            ai_response = response.choices[0].message.content

            return {
                'success': True,
                'response': ai_response,
                'prompt': system_prompt,
                'confidence': 0.85  # Could calculate based on model confidence
            }

        except Exception as e:
            logger.error(f"Error generating AI response: {e}", exc_info=True)
            return {
                'success': False,
                'error': str(e)
            }

    def _send_ai_response(
        self,
        conversation: EmailConversation,
        response_text: str,
        prompt_used: str,
        confidence: float
    ) -> Dict:
        """Send AI-generated response via email"""

        contact = conversation.contact

        # Determine email provider
        email_provider = os.getenv('EMAIL_PROVIDER', 'brevo').lower()

        try:
            if email_provider == 'brevo':
                from app.services.brevo_outreach import BrevoOutreachService
                service = BrevoOutreachService()
            else:
                from app.services.mailgun_outreach import MailgunOutreachService
                service = MailgunOutreachService()

            # Send email
            result = service.send_email(
                to_email=contact.email,
                subject=f"Re: {conversation.subject}",
                body_text=response_text,
                body_html=response_text.replace('\n', '<br>')
            )

            if result.get('success'):
                # Save outbound message
                outbound_message = EmailConversationMessage(
                    conversation_id=conversation.id,
                    direction='outbound',
                    from_email=os.getenv('BREVO_FROM_EMAIL', 'hi@fieldsprout.io'),
                    to_email=contact.email,
                    subject=f"Re: {conversation.subject}",
                    body_text=response_text,
                    body_html=response_text.replace('\n', '<br>'),
                    is_ai_generated=True,
                    ai_model=self.model,
                    ai_prompt_used=prompt_used,
                    ai_confidence=confidence,
                    sent_at=datetime.utcnow(),
                    message_id=result.get('message_id')
                )

                db.session.add(outbound_message)
                db.session.commit()

                logger.info(f"AI response sent for conversation {conversation.id}")

            return result

        except Exception as e:
            logger.error(f"Error sending AI response: {e}", exc_info=True)
            return {
                'success': False,
                'error': str(e)
            }

    def _create_alert(
        self,
        conversation: EmailConversation,
        alert_type: str,
        message: str,
        severity: str = 'info'
    ):
        """Create conversation alert for admin dashboard"""

        alert = ConversationAlert(
            conversation_id=conversation.id,
            alert_type=alert_type,
            message=message,
            severity=severity
        )

        db.session.add(alert)
        db.session.commit()

        logger.info(f"Created {severity} alert for conversation {conversation.id}: {alert_type}")
