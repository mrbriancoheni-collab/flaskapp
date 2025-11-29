"""
Account Setup Wizard Routes

Provides a guided setup experience for new Google Ads accounts or
account restructuring using the AccountStructureAgent.
"""

from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import json

from ..models import db, Account
from ..models_ads import AdsCampaign, AdsAdGroup, AdsKeyword
from ..auth.utils import login_required, current_account_id
from ..agents.account_structure_agent import AccountStructureAgent
from ..agents.strategic import StrategicDirectorAgent
from ..agents.decision_log import DecisionLog
from ..agents.base import AgentDecision, DecisionRiskLevel

account_wizard_bp = Blueprint('account_wizard', __name__, url_prefix='/account/google/ads/setup-wizard')


@account_wizard_bp.route('/', methods=['GET'])
@login_required
def wizard_home():
    """
    Landing page for the account setup wizard.
    Shows current account and wizard status.
    """
    # Get current account
    account_id = current_account_id()
    if not account_id:
        return "No account found", 404

    account = Account.query.get(account_id)
    if not account:
        return "Account not found", 404

    # Check if there's a recent wizard session
    wizard_data = _get_wizard_session(account_id)

    account_status = [{
        'account': account,
        'has_wizard_data': wizard_data is not None,
        'wizard_completed': wizard_data.get('completed', False) if wizard_data else False,
        'last_analysis': wizard_data.get('analysis_date') if wizard_data else None
    }]

    return render_template('google/account_setup_wizard.html',
                         account_status=account_status,
                         page_title='Account Setup Wizard')


@account_wizard_bp.route('/start/<int:account_id>', methods=['GET'])
@login_required
def start_wizard(account_id: int):
    """
    Start the wizard for a specific account.
    """
    # Verify account belongs to current user
    current_acct_id = current_account_id()
    if not current_acct_id or account_id != current_acct_id:
        return "Unauthorized", 403

    account = Account.query.get_or_404(account_id)

    # Initialize wizard session
    wizard_session = {
        'account_id': account_id,
        'started_at': datetime.now().isoformat(),
        'step': 'analyze',
        'completed': False
    }

    # Store in database as JSON in a wizard_sessions table (or use session storage)
    _save_wizard_session(account_id, wizard_session)

    return redirect(url_for('account_wizard.analyze_account', account_id=account_id))


@account_wizard_bp.route('/analyze/<int:account_id>', methods=['GET', 'POST'])
@login_required
def analyze_account(account_id: int):
    """
    Analyze account structure and show recommendations.
    """
    # Verify account belongs to current user
    current_acct_id = current_account_id()
    if not current_acct_id or account_id != current_acct_id:
        return "Unauthorized", 403

    account = Account.query.get_or_404(account_id)

    if request.method == 'GET':
        # Show analysis page
        wizard_data = _get_wizard_session(account_id)
        return render_template('google/wizard_analyze.html',
                             account=account,
                             wizard_data=wizard_data,
                             page_title=f'Analyze Account - {account.name}')

    # POST: Run analysis
    try:
        # Gather account data
        campaigns = AdsCampaign.query.filter_by(account_id=account_id).all()
        ad_groups = AdsAdGroup.query.join(AdsCampaign).filter(
            AdsCampaign.account_id == account_id
        ).all()
        keywords = AdsKeyword.query.join(AdsAdGroup).join(AdsCampaign).filter(
            AdsCampaign.account_id == account_id
        ).all()

        # Prepare context for analysis
        business_type = request.form.get('business_type', 'general')
        monthly_budget = float(request.form.get('monthly_budget', 0))

        context = {
            'campaigns': [_campaign_to_dict(c) for c in campaigns],
            'ad_groups': [_ad_group_to_dict(ag) for ag in ad_groups],
            'keywords': [_keyword_to_dict(kw) for kw in keywords],
            'account_age_days': (datetime.now() - account.created_at).days if hasattr(account, 'created_at') and account.created_at else 0,
            'business_type': business_type,
            'monthly_budget': monthly_budget
        }

        # Run AccountStructureAgent analysis
        agent = AccountStructureAgent(
            account_id=str(account_id),
            agent_config={}
        )

        opportunities = agent.analyze(context)
        decisions = agent.decide(opportunities)

        # Save analysis results
        wizard_data = _get_wizard_session(account_id) or {}
        wizard_data.update({
            'analysis_date': datetime.now().isoformat(),
            'business_type': business_type,
            'monthly_budget': monthly_budget,
            'opportunities': [_opportunity_to_dict(opp) for opp in opportunities],
            'decisions': [_decision_to_dict(d) for d in decisions],
            'step': 'review'
        })
        _save_wizard_session(account_id, wizard_data)

        return jsonify({
            'success': True,
            'opportunities_found': len(opportunities),
            'decisions_generated': len(decisions),
            'redirect': url_for('account_wizard.review_recommendations', account_id=account_id)
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 400


@account_wizard_bp.route('/review/<int:account_id>', methods=['GET'])
@login_required
def review_recommendations(account_id: int):
    """
    Review and customize recommendations.
    """
    # Verify account belongs to current user
    current_acct_id = current_account_id()
    if not current_acct_id or account_id != current_acct_id:
        return "Unauthorized", 403

    account = Account.query.get_or_404(account_id)

    wizard_data = _get_wizard_session(account_id)
    if not wizard_data or not wizard_data.get('opportunities'):
        return redirect(url_for('account_wizard.analyze_account', account_id=account_id))

    return render_template('google/wizard_review.html',
                         account=account,
                         wizard_data=wizard_data,
                         page_title=f'Review Recommendations - {account.name}')


@account_wizard_bp.route('/apply/<int:account_id>', methods=['POST'])
@login_required
def apply_recommendations(account_id: int):
    """
    Apply selected recommendations.
    """
    # Verify account belongs to current user
    current_acct_id = current_account_id()
    if not current_acct_id or account_id != current_acct_id:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403

    account = Account.query.get_or_404(account_id)

    wizard_data = _get_wizard_session(account_id)
    if not wizard_data:
        return jsonify({'success': False, 'error': 'No wizard session found'}), 400

    try:
        # Get selected decision IDs
        selected_decisions = request.json.get('decision_ids', [])

        # Create agent decision records for approval workflow
        decisions_data = wizard_data.get('decisions', [])
        created_decisions = []

        # Initialize decision log
        decision_log = DecisionLog()

        for decision_data in decisions_data:
            if decision_data.get('id') in selected_decisions or decision_data.get('index') in selected_decisions:
                # Map risk_level string to enum
                risk_level_str = decision_data.get('risk_level', 'medium').upper()
                risk_level = getattr(DecisionRiskLevel, risk_level_str, DecisionRiskLevel.MEDIUM)

                # Create AgentDecision object
                decision = AgentDecision(
                    agent_id='account_structure_agent',
                    agent_type='strategic',
                    decision_type=decision_data.get('decision_type'),
                    title=decision_data.get('title'),
                    description=decision_data.get('description'),
                    reasoning=decision_data.get('reasoning'),
                    account_id=account_id,
                    customer_id='',  # Google Ads customer ID not stored on Account model
                    action_data=decision_data.get('action_data', {}),
                    risk_level=risk_level,
                    requires_approval=decision_data.get('risk_level', 'medium') != 'low',
                    confidence=decision_data.get('confidence', 0.75),
                    expected_monthly_savings=decision_data.get('expected_monthly_savings', 0),
                    expected_monthly_leads=decision_data.get('expected_monthly_leads', 0),
                    status='pending',
                    created_at=datetime.now()
                )

                # Log the decision to the database
                decision_log.log_decision(decision)
                created_decisions.append(decision)

        # Mark wizard as completed
        wizard_data['completed'] = True
        wizard_data['completed_at'] = datetime.now().isoformat()
        wizard_data['applied_decisions'] = len(created_decisions)
        _save_wizard_session(account_id, wizard_data)

        return jsonify({
            'success': True,
            'decisions_created': len(created_decisions),
            'message': f'Created {len(created_decisions)} recommendations for review',
            'redirect': url_for('agents_bp.approval_queue')
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 400


@account_wizard_bp.route('/api/quick-analyze/<int:account_id>', methods=['POST'])
@login_required
def quick_analyze(account_id: int):
    """
    Quick analysis endpoint for AJAX requests.
    Returns structure insights without full wizard flow.
    """
    # Verify account belongs to current user
    current_acct_id = current_account_id()
    if not current_acct_id or account_id != current_acct_id:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403

    account = Account.query.get_or_404(account_id)

    try:
        # Gather minimal account data
        campaigns = AdsCampaign.query.filter_by(account_id=account_id).all()
        campaign_count = len(campaigns)

        # Quick structure check (using 'network' field from AdsCampaign)
        has_search = any(c.network == 'SEARCH' for c in campaigns)
        has_pmax = any(c.network == 'PMax' or c.network == 'PERFORMANCE_MAX' for c in campaigns)

        total_budget = sum(c.daily_budget_cents or 0 for c in campaigns) * 30 / 100

        # Quick recommendations
        recommendations = []

        if campaign_count == 0:
            recommendations.append({
                'type': 'no_campaigns',
                'priority': 'critical',
                'message': 'Account has no campaigns. Use the wizard to set up a complete campaign structure.',
                'action': 'Start Wizard'
            })
        elif not has_search and has_pmax:
            recommendations.append({
                'type': 'missing_search',
                'priority': 'high',
                'message': 'Account only has Performance Max campaigns. Add Search campaigns for better control.',
                'action': 'Add Search Campaigns'
            })
        elif has_search and not has_pmax:
            recommendations.append({
                'type': 'missing_pmax',
                'priority': 'medium',
                'message': 'Account only has Search campaigns. Add Performance Max to expand reach.',
                'action': 'Add Performance Max'
            })

        return jsonify({
            'success': True,
            'campaign_count': campaign_count,
            'has_search': has_search,
            'has_pmax': has_pmax,
            'total_monthly_budget': total_budget,
            'recommendations': recommendations
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 400


# Helper functions

def _get_wizard_session(account_id: int) -> Optional[Dict]:
    """Get wizard session data for an account."""
    # In production, this would query a wizard_sessions table
    # For now, use Flask session
    session_key = f'wizard_{account_id}'
    return session.get(session_key)


def _save_wizard_session(account_id: int, data: Dict):
    """Save wizard session data."""
    session_key = f'wizard_{account_id}'
    session[session_key] = data
    session.modified = True


def _campaign_to_dict(campaign: AdsCampaign) -> Dict:
    """Convert AdsCampaign model to dict for agent analysis."""
    return {
        'id': campaign.id,
        'name': campaign.name,
        'advertising_channel_type': campaign.network or 'SEARCH',
        'type': campaign.network or 'SEARCH',
        'daily_budget_cents': campaign.daily_budget_cents or 0,
        'status': campaign.status,
        'roas': 0,  # Not stored in AdsCampaign model
        'monthly_spend': (campaign.daily_budget_cents or 0) * 30 / 100,
        'impression_share': 0  # Not stored in AdsCampaign model
    }


def _ad_group_to_dict(ad_group: AdsAdGroup) -> Dict:
    """Convert AdsAdGroup model to dict for agent analysis."""
    return {
        'id': ad_group.id,
        'name': ad_group.name,
        'campaign_id': ad_group.campaign_id,
        'status': ad_group.status,
        'cpc_bid_cents': ad_group.max_cpc_cents or 0
    }


def _keyword_to_dict(keyword: AdsKeyword) -> Dict:
    """Convert AdsKeyword model to dict for agent analysis."""
    return {
        'id': keyword.id,
        'text': keyword.text,
        'match_type': keyword.match_type,
        'ad_group_id': keyword.ad_group_id,
        'status': keyword.status
    }


def _opportunity_to_dict(opp: Dict) -> Dict:
    """Serialize opportunity for session storage."""
    return {
        'type': opp.get('type'),
        'priority': opp.get('priority'),
        'issues': opp.get('issues', []),
        'recommendations': opp.get('recommendations', []),
        'data': opp.get('data', {})
    }


def _decision_to_dict(decision) -> Dict:
    """Serialize AgentDecision for session storage."""
    return {
        'id': getattr(decision, 'id', None),
        'index': id(decision),  # Use object id as temporary identifier
        'decision_type': decision.decision_type,
        'title': decision.title,
        'description': decision.description,
        'reasoning': decision.reasoning,
        'confidence': decision.confidence,
        'risk_level': decision.risk_level,
        'expected_monthly_savings': decision.expected_monthly_savings,
        'expected_monthly_leads': decision.expected_monthly_leads,
        'action_data': decision.action_data
    }
