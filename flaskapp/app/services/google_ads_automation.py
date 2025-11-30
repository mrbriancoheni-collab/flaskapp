"""
Google Ads Automation Services

Self-healing campaigns, budget optimization, experiments, and anomaly detection.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional, Any, Tuple
from decimal import Decimal
import json
from statistics import mean, stdev

from sqlalchemy import text
from app.extensions import db

logger = logging.getLogger(__name__)


# =============================================================================
# SELF-HEALING CAMPAIGNS (#17)
# =============================================================================

def run_self_healing_campaigns(account_id: int, dry_run: bool = False) -> Dict[str, Any]:
    """
    Execute self-healing campaign automation rules.

    Rules include:
    - Pause ads with CTR <1% after 100+ impressions
    - Increase bids for keywords in position 8-10 with high CVR
    - Decrease bids for keywords with CPA >2x target
    - Add exact match for high-performing broad match queries
    - Pause high-spend keywords with no conversions
    - Auto-add negative keywords

    Args:
        account_id: Account ID
        dry_run: If True, don't apply actions, just return recommendations

    Returns:
        Dict with actions_taken, recommendations, estimated_impact
    """
    actions_taken = []
    recommendations = []

    try:
        # Get active rules for this account
        rules = _get_active_self_healing_rules(account_id)

        for rule in rules:
            rule_type = rule['rule_type']
            conditions = rule['conditions']
            actions_config = rule['actions']

            if rule_type == 'pause_low_ctr':
                result = _execute_pause_low_ctr_rule(account_id, conditions, actions_config, dry_run)
            elif rule_type == 'increase_bid_low_position':
                result = _execute_bid_increase_rule(account_id, conditions, actions_config, dry_run)
            elif rule_type == 'decrease_bid_high_cpa':
                result = _execute_bid_decrease_rule(account_id, conditions, actions_config, dry_run)
            elif rule_type == 'add_exact_from_broad':
                result = _execute_add_exact_keywords_rule(account_id, conditions, actions_config, dry_run)
            elif rule_type == 'pause_high_spend_no_conversion':
                result = _execute_pause_nonconverting_rule(account_id, conditions, actions_config, dry_run)
            elif rule_type == 'auto_negative_keywords':
                result = _execute_auto_negative_rule(account_id, conditions, actions_config, dry_run)
            else:
                continue

            if dry_run:
                recommendations.extend(result['recommendations'])
            else:
                actions_taken.extend(result['actions'])

                # Log each action
                for action in result['actions']:
                    _log_self_healing_action(account_id, rule['id'], action)

        summary = {
            'account_id': account_id,
            'dry_run': dry_run,
            'rules_executed': len(rules),
            'actions_taken': actions_taken if not dry_run else [],
            'recommendations': recommendations if dry_run else [],
            'total_changes': len(actions_taken) if not dry_run else len(recommendations),
            'executed_at': datetime.utcnow().isoformat()
        }

        logger.info(f"[SELF_HEALING] Account {account_id}: {summary['total_changes']} actions {'recommended' if dry_run else 'applied'}")
        return summary

    except Exception as e:
        logger.exception(f"Error running self-healing campaigns: {e}")
        return {'error': str(e), 'actions_taken': [], 'recommendations': []}


def _get_active_self_healing_rules(account_id: int) -> List[Dict]:
    """Get active self-healing rules for an account."""
    try:
        query = text("""
            SELECT id, rule_name, rule_type, conditions, actions,
                   apply_to_campaigns, apply_to_ad_groups, max_actions_per_day
            FROM ads_self_healing_rules
            WHERE account_id = :account_id
            AND is_active = TRUE
        """)

        results = db.session.execute(query, {'account_id': account_id}).fetchall()

        rules = []
        for row in results:
            rules.append({
                'id': row[0],
                'rule_name': row[1],
                'rule_type': row[2],
                'conditions': json.loads(row[3]) if row[3] else {},
                'actions': json.loads(row[4]) if row[4] else {},
                'apply_to_campaigns': json.loads(row[5]) if row[5] else None,
                'apply_to_ad_groups': json.loads(row[6]) if row[6] else None,
                'max_actions_per_day': row[7]
            })

        return rules

    except Exception as e:
        logger.error(f"Error getting self-healing rules: {e}")
        return []


def _execute_pause_low_ctr_rule(account_id: int, conditions: Dict, actions: Dict, dry_run: bool) -> Dict:
    """Pause ads with low CTR."""
    result = {'actions': [], 'recommendations': []}

    try:
        min_ctr = conditions.get('ctr_below', 0.01)
        min_impressions = conditions.get('min_impressions', 100)

        # Find low CTR ads
        query = text("""
            SELECT id, name, ctr, impressions, clicks
            FROM ads
            WHERE account_id = :account_id
            AND status = 'ENABLED'
            AND impressions >= :min_impressions
            AND ctr < :min_ctr
            LIMIT 20
        """)

        results = db.session.execute(query, {
            'account_id': account_id,
            'min_impressions': min_impressions,
            'min_ctr': min_ctr
        }).fetchall()

        for row in results:
            ad_id, ad_name, ctr, impressions, clicks = row

            action = {
                'entity_type': 'ad',
                'entity_id': ad_id,
                'entity_name': ad_name,
                'action_type': 'pause',
                'reason': f'Low CTR {ctr:.2%} after {impressions} impressions',
                'trigger_metrics': {
                    'ctr': float(ctr),
                    'impressions': impressions,
                    'clicks': clicks
                }
            }

            if dry_run:
                result['recommendations'].append(action)
            else:
                # Apply the action
                _pause_ad(account_id, ad_id)
                result['actions'].append(action)

        return result

    except Exception as e:
        logger.error(f"Error executing pause low CTR rule: {e}")
        return result


def _execute_bid_increase_rule(account_id: int, conditions: Dict, actions: Dict, dry_run: bool) -> Dict:
    """Increase bids for keywords in low positions with good CVR."""
    result = {'actions': [], 'recommendations': []}

    try:
        min_cvr = conditions.get('min_cvr', 0.03)
        max_position = conditions.get('max_position', 8.0)
        bid_increase_pct = actions.get('bid_increase_pct', 20)

        # Find keywords to bid up
        query = text("""
            SELECT id, text, avg_position, cvr, max_cpc, conversions, clicks
            FROM keywords
            WHERE account_id = :account_id
            AND status = 'ENABLED'
            AND avg_position >= :max_position
            AND cvr >= :min_cvr
            AND clicks >= 20
            LIMIT 20
        """)

        results = db.session.execute(query, {
            'account_id': account_id,
            'max_position': max_position,
            'min_cvr': min_cvr
        }).fetchall()

        for row in results:
            keyword_id, keyword_text, avg_pos, cvr, current_bid, conversions, clicks = row
            new_bid = float(current_bid) * (1 + bid_increase_pct / 100.0)

            action = {
                'entity_type': 'keyword',
                'entity_id': keyword_id,
                'entity_name': keyword_text,
                'action_type': 'increase_bid',
                'reason': f'Good CVR {cvr:.1%} but low position {avg_pos:.1f}',
                'trigger_metrics': {
                    'cvr': float(cvr),
                    'avg_position': float(avg_pos),
                    'current_bid': float(current_bid),
                    'new_bid': new_bid
                }
            }

            if dry_run:
                result['recommendations'].append(action)
            else:
                # Apply the action
                _update_keyword_bid(account_id, keyword_id, new_bid)
                result['actions'].append(action)

        return result

    except Exception as e:
        logger.error(f"Error executing bid increase rule: {e}")
        return result


def _execute_bid_decrease_rule(account_id: int, conditions: Dict, actions: Dict, dry_run: bool) -> Dict:
    """Decrease bids for keywords with high CPA."""
    result = {'actions': [], 'recommendations': []}

    try:
        target_cpa = conditions.get('target_cpa', 50.0)
        cpa_multiplier = conditions.get('cpa_multiplier', 2.0)
        bid_decrease_pct = actions.get('bid_decrease_pct', 20)

        max_cpa = target_cpa * cpa_multiplier

        query = text("""
            SELECT id, text, cpa, max_cpc, conversions, cost
            FROM keywords
            WHERE account_id = :account_id
            AND status = 'ENABLED'
            AND conversions > 0
            AND cpa > :max_cpa
            LIMIT 20
        """)

        results = db.session.execute(query, {
            'account_id': account_id,
            'max_cpa': max_cpa
        }).fetchall()

        for row in results:
            keyword_id, keyword_text, cpa, current_bid, conversions, cost = row
            new_bid = float(current_bid) * (1 - bid_decrease_pct / 100.0)

            action = {
                'entity_type': 'keyword',
                'entity_id': keyword_id,
                'entity_name': keyword_text,
                'action_type': 'decrease_bid',
                'reason': f'High CPA ${cpa:.2f} (target: ${target_cpa:.2f})',
                'trigger_metrics': {
                    'cpa': float(cpa),
                    'target_cpa': target_cpa,
                    'current_bid': float(current_bid),
                    'new_bid': new_bid,
                    'conversions': conversions
                }
            }

            if dry_run:
                result['recommendations'].append(action)
            else:
                _update_keyword_bid(account_id, keyword_id, new_bid)
                result['actions'].append(action)

        return result

    except Exception as e:
        logger.error(f"Error executing bid decrease rule: {e}")
        return result


def _execute_add_exact_keywords_rule(account_id: int, conditions: Dict, actions: Dict, dry_run: bool) -> Dict:
    """Add exact match keywords from high-performing broad match queries."""
    result = {'actions': [], 'recommendations': []}

    try:
        min_conversions = conditions.get('min_conversions', 3)
        min_cvr = conditions.get('min_cvr', 0.03)

        # Find high-performing search queries
        query = text("""
            SELECT search_query, SUM(conversions) as total_conv,
                   SUM(clicks) as total_clicks, SUM(cost) as total_cost,
                   campaign_id, ad_group_id
            FROM search_terms_report
            WHERE account_id = :account_id
            AND match_type = 'BROAD'
            AND date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
            GROUP BY search_query, campaign_id, ad_group_id
            HAVING total_conv >= :min_conversions
            AND (total_conv / total_clicks) >= :min_cvr
            LIMIT 15
        """)

        results = db.session.execute(query, {
            'account_id': account_id,
            'min_conversions': min_conversions,
            'min_cvr': min_cvr
        }).fetchall()

        for row in results:
            search_query, conversions, clicks, cost, campaign_id, ad_group_id = row
            cvr = conversions / clicks if clicks > 0 else 0

            action = {
                'entity_type': 'keyword',
                'entity_id': None,
                'entity_name': search_query,
                'action_type': 'add_exact_keyword',
                'reason': f'{conversions} conversions from broad match ({cvr:.1%} CVR)',
                'trigger_metrics': {
                    'search_query': search_query,
                    'conversions': conversions,
                    'cvr': cvr,
                    'campaign_id': campaign_id,
                    'ad_group_id': ad_group_id
                }
            }

            if dry_run:
                result['recommendations'].append(action)
            else:
                # Apply the action
                _add_exact_keyword(account_id, campaign_id, ad_group_id, search_query)
                result['actions'].append(action)

        return result

    except Exception as e:
        logger.error(f"Error executing add exact keywords rule: {e}")
        return result


def _execute_pause_nonconverting_rule(account_id: int, conditions: Dict, actions: Dict, dry_run: bool) -> Dict:
    """Pause keywords with high spend but no conversions."""
    result = {'actions': [], 'recommendations': []}

    try:
        min_spend = conditions.get('min_spend', 100.0)
        min_clicks = conditions.get('min_clicks', 50)

        query = text("""
            SELECT id, text, cost, clicks, impressions
            FROM keywords
            WHERE account_id = :account_id
            AND status = 'ENABLED'
            AND cost >= :min_spend
            AND clicks >= :min_clicks
            AND conversions = 0
            LIMIT 20
        """)

        results = db.session.execute(query, {
            'account_id': account_id,
            'min_spend': min_spend,
            'min_clicks': min_clicks
        }).fetchall()

        for row in results:
            keyword_id, keyword_text, cost, clicks, impressions = row

            action = {
                'entity_type': 'keyword',
                'entity_id': keyword_id,
                'entity_name': keyword_text,
                'action_type': 'pause',
                'reason': f'${cost:.2f} spent, {clicks} clicks, 0 conversions',
                'trigger_metrics': {
                    'cost': float(cost),
                    'clicks': clicks,
                    'impressions': impressions,
                    'conversions': 0
                }
            }

            if dry_run:
                result['recommendations'].append(action)
            else:
                _pause_keyword(account_id, keyword_id)
                result['actions'].append(action)

        return result

    except Exception as e:
        logger.error(f"Error executing pause non-converting rule: {e}")
        return result


def _execute_auto_negative_rule(account_id: int, conditions: Dict, actions: Dict, dry_run: bool) -> Dict:
    """Auto-add negative keywords from suggestions."""
    result = {'actions': [], 'recommendations': []}

    try:
        min_confidence = conditions.get('min_confidence', 80)
        min_spend = conditions.get('min_wasted_spend', 25.0)

        query = text("""
            SELECT id, search_query, negative_reason, confidence_score,
                   wasted_spend, suggested_match_type, suggested_level
            FROM ads_negative_keyword_suggestions
            WHERE account_id = :account_id
            AND status = 'pending'
            AND confidence_score >= :min_confidence
            AND wasted_spend >= :min_spend
            ORDER BY wasted_spend DESC
            LIMIT 30
        """)

        results = db.session.execute(query, {
            'account_id': account_id,
            'min_confidence': min_confidence,
            'min_spend': min_spend
        }).fetchall()

        for row in results:
            suggestion_id, search_query, reason, confidence, spend, match_type, level = row

            action = {
                'entity_type': 'negative_keyword',
                'entity_id': suggestion_id,
                'entity_name': search_query,
                'action_type': 'add_negative',
                'reason': f'{reason} - ${spend:.2f} wasted ({confidence:.0f}% confidence)',
                'trigger_metrics': {
                    'search_query': search_query,
                    'wasted_spend': float(spend),
                    'confidence': confidence,
                    'match_type': match_type,
                    'level': level
                }
            }

            if dry_run:
                result['recommendations'].append(action)
            else:
                # Apply the action
                _add_negative_keyword(account_id, search_query, match_type, level)
                _mark_negative_suggestion_applied(suggestion_id)
                result['actions'].append(action)

        return result

    except Exception as e:
        logger.error(f"Error executing auto negative rule: {e}")
        return result


# Helper functions for database operations
def _pause_ad(account_id: int, ad_id: int):
    """Pause an ad."""
    query = text("UPDATE ads SET status = 'PAUSED' WHERE id = :ad_id AND account_id = :account_id")
    db.session.execute(query, {'ad_id': ad_id, 'account_id': account_id})
    db.session.commit()


def _pause_keyword(account_id: int, keyword_id: int):
    """Pause a keyword."""
    query = text("UPDATE keywords SET status = 'PAUSED' WHERE id = :keyword_id AND account_id = :account_id")
    db.session.execute(query, {'keyword_id': keyword_id, 'account_id': account_id})
    db.session.commit()


def _update_keyword_bid(account_id: int, keyword_id: int, new_bid: float):
    """Update keyword bid."""
    query = text("UPDATE keywords SET max_cpc = :new_bid WHERE id = :keyword_id AND account_id = :account_id")
    db.session.execute(query, {'keyword_id': keyword_id, 'new_bid': new_bid, 'account_id': account_id})
    db.session.commit()


def _add_exact_keyword(account_id: int, campaign_id: int, ad_group_id: int, keyword_text: str):
    """Add exact match keyword."""
    # This would integrate with Google Ads API
    logger.info(f"[SELF_HEALING] Adding exact keyword: [{keyword_text}] to campaign {campaign_id}")
    pass


def _add_negative_keyword(account_id: int, keyword_text: str, match_type: str, level: str):
    """Add negative keyword."""
    # This would integrate with Google Ads API
    logger.info(f"[SELF_HEALING] Adding negative keyword: {keyword_text} ({match_type}) at {level} level")
    pass


def _mark_negative_suggestion_applied(suggestion_id: int):
    """Mark negative keyword suggestion as applied."""
    query = text("UPDATE ads_negative_keyword_suggestions SET status = 'applied', applied_at = NOW() WHERE id = :id")
    db.session.execute(query, {'id': suggestion_id})
    db.session.commit()


def _log_self_healing_action(account_id: int, rule_id: int, action: Dict):
    """Log a self-healing action."""
    try:
        query = text("""
            INSERT INTO ads_self_healing_actions (
                account_id, rule_id, entity_type, entity_id, entity_name,
                action_type, action_details, trigger_metrics, status
            ) VALUES (
                :account_id, :rule_id, :entity_type, :entity_id, :entity_name,
                :action_type, :action_details, :trigger_metrics, 'applied'
            )
        """)

        db.session.execute(query, {
            'account_id': account_id,
            'rule_id': rule_id,
            'entity_type': action['entity_type'],
            'entity_id': action.get('entity_id'),
            'entity_name': action['entity_name'],
            'action_type': action['action_type'],
            'action_details': json.dumps(action),
            'trigger_metrics': json.dumps(action.get('trigger_metrics', {}))
        })
        db.session.commit()

    except Exception as e:
        logger.error(f"Error logging self-healing action: {e}")
        db.session.rollback()


# =============================================================================
# BUDGET REALLOCATION ENGINE (#18)
# =============================================================================

def reallocate_budgets(account_id: int, dry_run: bool = False) -> Dict[str, Any]:
    """
    Intelligently reallocate budgets between campaigns based on performance.

    Strategy:
    - Take budget from campaigns hitting target CPA with room to spare
    - Give budget to campaigns hitting target CPA at 80%+ budget utilization
    - Reduce budget from campaigns with CPA >2x target
    - Maximum 20% shift per day

    Returns:
        Dict with reallocations and estimated impact
    """
    reallocations = []

    try:
        # Get campaign performance for last 7 days
        campaigns = _get_campaign_performance_for_reallocation(account_id)

        # Categorize campaigns
        high_performers = []  # Good CPA, budget constrained
        overperformers = []   # Good CPA, budget remaining
        poor_performers = []  # Bad CPA

        target_cpa = 50.0  # TODO: Get from account settings

        for campaign in campaigns:
            cpa = campaign['cpa']
            budget_utilization = campaign['budget_utilization']

            if cpa <= target_cpa:
                if budget_utilization >= 0.80:
                    high_performers.append(campaign)
                else:
                    overperformers.append(campaign)
            elif cpa > target_cpa * 2:
                poor_performers.append(campaign)

        # Calculate reallocations
        for donor in overperformers + poor_performers:
            for recipient in high_performers:
                if donor['id'] == recipient['id']:
                    continue

                # Calculate how much to move (max 20% of donor's budget)
                max_transfer = donor['daily_budget'] * 0.20
                amount_to_move = min(max_transfer, 100.0)  # Max $100/day shift

                if amount_to_move < 10.0:  # Minimum $10 shift
                    continue

                reallocation = {
                    'from_campaign_id': donor['id'],
                    'from_campaign_name': donor['name'],
                    'from_previous_budget': donor['daily_budget'],
                    'to_campaign_id': recipient['id'],
                    'to_campaign_name': recipient['name'],
                    'to_previous_budget': recipient['daily_budget'],
                    'amount_reallocated': amount_to_move,
                    'reason': f"Recipient has {recipient['cpa']:.2f} CPA at {recipient['budget_utilization']:.0%} budget. Donor has {donor['cpa']:.2f} CPA.",
                    'performance_metrics': {
                        'donor_cpa': donor['cpa'],
                        'recipient_cpa': recipient['cpa'],
                        'donor_cvr': donor['cvr'],
                        'recipient_cvr': recipient['cvr']
                    }
                }

                reallocations.append(reallocation)

                if not dry_run:
                    _execute_budget_reallocation(account_id, reallocation)

                break  # One reallocation per donor

        summary = {
            'account_id': account_id,
            'dry_run': dry_run,
            'reallocations': reallocations,
            'total_campaigns_analyzed': len(campaigns),
            'high_performers': len(high_performers),
            'overperformers': len(overperformers),
            'poor_performers': len(poor_performers)
        }

        logger.info(f"[BUDGET_REALLOCATION] Account {account_id}: {len(reallocations)} reallocations {'recommended' if dry_run else 'applied'}")
        return summary

    except Exception as e:
        logger.exception(f"Error reallocating budgets: {e}")
        return {'error': str(e), 'reallocations': []}


def _get_campaign_performance_for_reallocation(account_id: int) -> List[Dict]:
    """Get campaign performance data for budget reallocation."""
    try:
        query = text("""
            SELECT
                c.id,
                c.name,
                c.daily_budget_cents / 100.0 as daily_budget,
                SUM(cr.cost) as total_cost,
                SUM(cr.conversions) as total_conversions,
                SUM(cr.clicks) as total_clicks,
                SUM(cr.cost) / NULLIF(SUM(cr.conversions), 0) as cpa,
                SUM(cr.conversions) / NULLIF(SUM(cr.clicks), 0) as cvr,
                SUM(cr.cost) / (c.daily_budget_cents / 100.0 * 7) as budget_utilization
            FROM ads_campaigns c
            LEFT JOIN campaign_reports cr ON c.id = cr.campaign_id
            WHERE c.account_id = :account_id
            AND c.status = 'enabled'
            AND cr.date >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)
            GROUP BY c.id, c.name, c.daily_budget_cents
            HAVING total_cost > 0 AND total_conversions > 0
        """)

        results = db.session.execute(query, {'account_id': account_id}).fetchall()

        campaigns = []
        for row in results:
            campaigns.append({
                'id': row[0],
                'name': row[1],
                'daily_budget': float(row[2]),
                'total_cost': float(row[3]),
                'total_conversions': row[4],
                'total_clicks': row[5],
                'cpa': float(row[6]) if row[6] else 999.99,
                'cvr': float(row[7]) if row[7] else 0.0,
                'budget_utilization': float(row[8]) if row[8] else 0.0
            })

        return campaigns

    except Exception as e:
        logger.error(f"Error getting campaign performance: {e}")
        return []


def _execute_budget_reallocation(account_id: int, reallocation: Dict):
    """Execute a budget reallocation."""
    try:
        # Update donor budget (decrease)
        new_donor_budget = reallocation['from_previous_budget'] - reallocation['amount_reallocated']
        query = text("UPDATE ads_campaigns SET daily_budget_cents = :new_budget * 100 WHERE id = :campaign_id")
        db.session.execute(query, {
            'new_budget': new_donor_budget,
            'campaign_id': reallocation['from_campaign_id']
        })

        # Update recipient budget (increase)
        new_recipient_budget = reallocation['to_previous_budget'] + reallocation['amount_reallocated']
        db.session.execute(query, {
            'new_budget': new_recipient_budget,
            'campaign_id': reallocation['to_campaign_id']
        })

        # Log the reallocation
        log_query = text("""
            INSERT INTO ads_budget_reallocation_history (
                account_id, date, from_campaign_id, from_campaign_name, from_previous_budget,
                to_campaign_id, to_campaign_name, to_previous_budget,
                amount_reallocated, reallocation_reason, performance_metrics
            ) VALUES (
                :account_id, CURDATE(), :from_id, :from_name, :from_budget,
                :to_id, :to_name, :to_budget,
                :amount, :reason, :metrics
            )
        """)

        db.session.execute(log_query, {
            'account_id': account_id,
            'from_id': reallocation['from_campaign_id'],
            'from_name': reallocation['from_campaign_name'],
            'from_budget': reallocation['from_previous_budget'],
            'to_id': reallocation['to_campaign_id'],
            'to_name': reallocation['to_campaign_name'],
            'to_budget': reallocation['to_previous_budget'],
            'amount': reallocation['amount_reallocated'],
            'reason': reallocation['reason'],
            'metrics': json.dumps(reallocation['performance_metrics'])
        })

        db.session.commit()

        logger.info(f"[BUDGET_REALLOCATION] Moved ${reallocation['amount_reallocated']:.2f} from '{reallocation['from_campaign_name']}' to '{reallocation['to_campaign_name']}'")

    except Exception as e:
        logger.error(f"Error executing budget reallocation: {e}")
        db.session.rollback()
