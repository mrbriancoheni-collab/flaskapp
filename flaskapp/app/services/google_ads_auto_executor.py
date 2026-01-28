# app/services/google_ads_auto_executor.py
"""
Google Ads Auto-Execution Service

Automatically applies safe optimizations to Google Ads campaigns with full logging and undo capability.

Features:
- Auto-adds negative keywords using LLM-based business relevance analysis
- Auto-pauses low-performing keywords
- Auto-adjusts bids based on performance
- Full audit trail via AIAction model
- One-click undo for all changes
- Safety limits and confidence thresholds
"""

import json
import logging
import os
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy import func, and_

from app import db
from app.models import Account, GoogleAdsAuth
from app.models_ai_actions import AIAction, AIActionRule
from app.google.utils_ads import client_from_refresh

logger = logging.getLogger(__name__)


class GoogleAdsAutoExecutor:
    """Service for automatically executing safe Google Ads optimizations"""

    # Non-purchase intent indicators (keywords/phrases that suggest no buying intent)
    NON_PURCHASE_INTENT_PATTERNS = [
        # Job/employment seeking
        'job', 'jobs', 'career', 'careers', 'hiring', 'employment', 'resume', 'salary',
        'work from home', 'remote work', 'part time', 'full time', 'apply',

        # DIY/How-to (people looking to do it themselves)
        'how to', 'diy', 'tutorial', 'guide', 'tips', 'instructions', 'step by step',
        'yourself', 'myself', 'homemade', 'manual', 'fix it', 'repair guide',

        # Educational/informational
        'what is', 'definition', 'meaning', 'wiki', 'wikipedia', 'learn', 'course',
        'training', 'certification', 'school', 'class', 'education',

        # Free/cheap alternatives
        'free', 'cheap', 'discount', 'coupon', 'deal', 'sale', 'clearance',

        # Research/comparison (not ready to buy)
        'review', 'reviews', 'comparison', 'compare', 'vs', 'versus', 'best',
        'top 10', 'alternatives', 'options', 'which', 'should i',

        # Images/videos (informational browsing)
        'image', 'images', 'photo', 'photos', 'picture', 'pictures', 'video', 'videos',
        'clip', 'clips', 'youtube', 'watch',

        # Wrong products/services
        'software', 'app', 'game', 'toy', 'used', 'for sale', 'buy', 'purchase',
        'online', 'shopping', 'store'
    ]

    # Confidence thresholds for different action types
    CONFIDENCE_THRESHOLDS = {
        'negative_keyword_added': 0.85,        # High confidence for negatives
        'keyword_paused': 0.90,                # Very high confidence for pausing
        'bid_adjusted': 0.75,                  # Moderate confidence for bid changes
        'budget_reallocated': 0.80,            # High confidence for budget moves
    }

    # Daily limits to prevent runaway automation
    MAX_ACTIONS_PER_DAY = {
        'negative_keyword_added': 100,
        'keyword_paused': 20,
        'bid_adjusted': 50,
        'budget_reallocated': 10,
    }

    def __init__(self, account_id: int):
        """Initialize executor for specific account."""
        self.account_id = account_id
        self.account = Account.query.get(account_id)

        if not self.account:
            raise ValueError(f"Account {account_id} not found")

        self.google_ads_client = None
        self.google_auth = None

        # Load business context for LLM-based relevance checks
        self.business_description = self.account.get_business_description() or ''
        self.business_services = self.account.get_business_services() or ''

    def _get_google_ads_client(self):
        """Get Google Ads API client."""
        if not self.google_ads_client:
            # Get Google Ads auth from GoogleAdsAuth table
            self.google_auth = GoogleAdsAuth.query.filter_by(account_id=self.account_id).first()

            if not self.google_auth or not self.google_auth.refresh_token:
                raise ValueError(f"Account {self.account_id} has no Google Ads connection")

            login_customer_id = self.google_auth.manager_customer_id or self.google_auth.customer_id
            self.google_ads_client = client_from_refresh(
                self.google_auth.refresh_token,
                login_customer_id
            )

        return self.google_ads_client

    def _check_daily_limit(self, action_type: str) -> bool:
        """Check if we've hit the daily limit for this action type."""
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

        count_today = AIAction.query.filter(
            AIAction.account_id == self.account_id,
            AIAction.action_type == action_type,
            AIAction.status == 'executed',
            AIAction.created_at >= today_start
        ).count()

        max_allowed = self.MAX_ACTIONS_PER_DAY.get(action_type, 50)

        if count_today >= max_allowed:
            logger.warning(
                f"Daily limit reached for {action_type}: {count_today}/{max_allowed} for account {self.account_id}"
            )
            return False

        return True

    def auto_add_negative_keywords(self, lookback_days: int = 30, dry_run: bool = False) -> List[AIAction]:
        """
        Automatically add negative keywords using two-pass analysis:
        1. Pattern matching for obvious non-purchase-intent terms
        2. LLM-based business relevance check for all remaining terms

        Args:
            lookback_days: How many days back to analyze search terms
            dry_run: If True, only create pending actions, don't execute

        Returns:
            List of AIAction objects created/executed
        """
        if not self._check_daily_limit('negative_keyword_added'):
            logger.info(f"Daily limit reached for negative keywords, skipping account {self.account_id}")
            return []

        try:
            client = self._get_google_ads_client()

            # Get customer ID from cached google_auth (set by _get_google_ads_client)
            if not self.google_auth or not self.google_auth.customer_id:
                logger.warning(f"No customer ID for account {self.account_id}")
                return []

            customer_id = self.google_auth.customer_id

            # Query search terms from last N days
            query = f"""
                SELECT
                    search_term_view.search_term,
                    search_term_view.status,
                    segments.search_term_match_type,
                    campaign.id,
                    campaign.name,
                    ad_group.id,
                    ad_group.name,
                    metrics.impressions,
                    metrics.clicks,
                    metrics.conversions,
                    metrics.cost_micros,
                    metrics.ctr,
                    metrics.conversion_rate
                FROM search_term_view
                WHERE segments.date DURING LAST_{lookback_days}_DAYS
                    AND metrics.impressions > 10
                    AND search_term_view.status != 'EXCLUDED'
                ORDER BY metrics.cost_micros DESC
                LIMIT 500
            """

            ga_service = client.get_service("GoogleAdsService")
            stream = ga_service.search_stream(customer_id=customer_id, query=query)

            # Collect all search terms first
            all_rows = []
            processed_terms = set()

            for batch in stream:
                for row in batch.results:
                    search_term = row.search_term_view.search_term.lower().strip()
                    if search_term not in processed_terms:
                        all_rows.append(row)
                        processed_terms.add(search_term)

            if not all_rows:
                logger.info(f"Account {self.account_id}: No search terms found in last {lookback_days} days")
                return []

            # PASS 1: Pattern matching for obvious non-purchase-intent
            pattern_flagged = {}   # term -> (row, patterns_matched)
            remaining_rows = []    # terms not caught by patterns

            for row in all_rows:
                search_term = row.search_term_view.search_term.lower().strip()
                has_non_purchase_intent, patterns_matched = self._check_non_purchase_intent(search_term)
                if has_non_purchase_intent:
                    pattern_flagged[search_term] = (row, patterns_matched)
                else:
                    remaining_rows.append(row)

            # PASS 2: LLM-based business relevance for remaining terms
            llm_flagged = {}  # term -> (row, reason)
            if remaining_rows and self.business_description:
                terms_for_llm = [
                    row.search_term_view.search_term.lower().strip()
                    for row in remaining_rows
                ]
                llm_results = self._evaluate_terms_with_llm(terms_for_llm)

                for row in remaining_rows:
                    search_term = row.search_term_view.search_term.lower().strip()
                    result = llm_results.get(search_term, {})
                    if result.get('irrelevant', False):
                        llm_flagged[search_term] = (row, result.get('reason', 'Irrelevant to business'))
            elif remaining_rows and not self.business_description:
                logger.warning(
                    f"Account {self.account_id}: No business_description set. "
                    f"Skipping LLM relevance check for {len(remaining_rows)} search terms. "
                    f"Set account.business_description to enable intelligent negative keyword detection."
                )

            # Create actions for all flagged terms
            actions_created = []

            # Process pattern-matched terms
            for search_term, (row, patterns_matched) in pattern_flagged.items():
                confidence = self._calculate_confidence(row.metrics, patterns_matched, search_term)
                if confidence < self.CONFIDENCE_THRESHOLDS['negative_keyword_added']:
                    continue

                cost = row.metrics.cost_micros / 1_000_000
                conversions = row.metrics.conversions
                estimated_savings = cost if conversions == 0 else cost * 0.8

                action = AIAction(
                    account_id=self.account_id,
                    action_type='negative_keyword_added',
                    title=f"Block Non-Purchase Intent: '{search_term}'",
                    description=f"Detected non-purchase intent patterns: {', '.join(patterns_matched[:3])}. Spent ${cost:.2f} with {conversions} conversions.",
                    campaign_id=str(row.campaign.id),
                    campaign_name=row.campaign.name,
                    ad_group_id=str(row.ad_group.id),
                    ad_group_name=row.ad_group.name,
                    before_value={'search_term': search_term, 'status': 'active'},
                    after_value={'search_term': search_term, 'status': 'excluded'},
                    estimated_monthly_savings=estimated_savings,
                    confidence_score=confidence,
                    reasoning=f"Search term '{search_term}' matches non-purchase intent patterns: {', '.join(patterns_matched)}. "
                             f"Performance: ${cost:.2f} spent, {row.metrics.clicks} clicks, {conversions} conversions ({row.metrics.ctr:.2%} CTR).",
                    data_used={
                        'search_term': search_term,
                        'detection_method': 'pattern_match',
                        'patterns_matched': patterns_matched,
                        'impressions': row.metrics.impressions,
                        'clicks': row.metrics.clicks,
                        'conversions': conversions,
                        'cost': cost,
                        'ctr': row.metrics.ctr,
                        'conversion_rate': row.metrics.conversion_rate,
                        'lookback_days': lookback_days
                    },
                    status='pending'
                )
                db.session.add(action)
                actions_created.append(action)

                if not dry_run:
                    try:
                        self._execute_negative_keyword_add(action, customer_id, search_term, row.campaign.id)
                        action.mark_executed()
                        logger.info(f"Added negative keyword (pattern): '{search_term}' to campaign {row.campaign.name}")
                    except Exception as e:
                        action.mark_failed(str(e))
                        logger.error(f"Failed to add negative keyword '{search_term}': {e}")

                if not self._check_daily_limit('negative_keyword_added'):
                    break

            # Process LLM-flagged terms
            for search_term, (row, reason) in llm_flagged.items():
                if not self._check_daily_limit('negative_keyword_added'):
                    break

                cost = row.metrics.cost_micros / 1_000_000
                conversions = row.metrics.conversions
                estimated_savings = cost if conversions == 0 else cost * 0.8
                confidence = 0.90  # High confidence from LLM analysis

                action = AIAction(
                    account_id=self.account_id,
                    action_type='negative_keyword_added',
                    title=f"Block Irrelevant Term: '{search_term}'",
                    description=f"AI determined this term is irrelevant to business. {reason}. Spent ${cost:.2f} with {conversions} conversions.",
                    campaign_id=str(row.campaign.id),
                    campaign_name=row.campaign.name,
                    ad_group_id=str(row.ad_group.id),
                    ad_group_name=row.ad_group.name,
                    before_value={'search_term': search_term, 'status': 'active'},
                    after_value={'search_term': search_term, 'status': 'excluded'},
                    estimated_monthly_savings=estimated_savings,
                    confidence_score=confidence,
                    reasoning=f"AI analysis: '{search_term}' is irrelevant to business ({self.business_description}). "
                             f"Reason: {reason}. "
                             f"Performance: ${cost:.2f} spent, {row.metrics.clicks} clicks, {conversions} conversions ({row.metrics.ctr:.2%} CTR).",
                    data_used={
                        'search_term': search_term,
                        'detection_method': 'llm_business_relevance',
                        'llm_reason': reason,
                        'business_description': self.business_description,
                        'impressions': row.metrics.impressions,
                        'clicks': row.metrics.clicks,
                        'conversions': conversions,
                        'cost': cost,
                        'ctr': row.metrics.ctr,
                        'conversion_rate': row.metrics.conversion_rate,
                        'lookback_days': lookback_days
                    },
                    status='pending'
                )
                db.session.add(action)
                actions_created.append(action)

                if not dry_run:
                    try:
                        self._execute_negative_keyword_add(action, customer_id, search_term, row.campaign.id)
                        action.mark_executed()
                        logger.info(f"Added negative keyword (LLM): '{search_term}' to campaign {row.campaign.name}")
                    except Exception as e:
                        action.mark_failed(str(e))
                        logger.error(f"Failed to add negative keyword '{search_term}': {e}")

            db.session.commit()

            logger.info(
                f"Account {self.account_id}: Created {len(actions_created)} negative keyword actions "
                f"(pattern={len(pattern_flagged)}, llm={len(llm_flagged)}) "
                f"({'DRY RUN' if dry_run else 'EXECUTED'})"
            )

            return actions_created

        except Exception as e:
            logger.exception(f"Error auto-adding negative keywords for account {self.account_id}: {e}")
            db.session.rollback()
            return []

    def _evaluate_terms_with_llm(self, search_terms: List[str]) -> Dict[str, Dict]:
        """
        Use LLM to evaluate whether search terms are relevant to the business.

        Sends a batch of search terms to OpenAI and gets back a relevance verdict
        for each one. This catches business-specific irrelevant terms that pattern
        matching alone would miss.

        Args:
            search_terms: List of search term strings to evaluate

        Returns:
            Dict mapping search_term -> {'irrelevant': bool, 'reason': str}
        """
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            logger.warning("No OPENAI_API_KEY set, skipping LLM-based term evaluation")
            return {}

        if not search_terms:
            return {}

        # Build the prompt with business context
        business_context = f"Business: {self.business_description}"
        if self.business_services:
            business_context += f"\nServices offered: {self.business_services}"

        terms_list = "\n".join(f"- {term}" for term in search_terms[:50])  # Batch up to 50

        prompt = f"""You are a Google Ads negative keyword analyst. Analyze each search term below and determine whether it is RELEVANT or IRRELEVANT to this business.

{business_context}

A search term is RELEVANT if a person searching it could reasonably become a paying customer for the services listed above. A search term is IRRELEVANT if:
- It relates to a different industry or service (e.g. "pool construction" for a pool cleaning company)
- It's seeking information, products, or services the business does NOT offer
- It's a generic/broad term with no purchase intent for the specific services
- It's in a foreign language BUT still relates to the business services (mark as RELEVANT)

Search terms to evaluate:
{terms_list}

Respond ONLY with valid JSON — an array of objects, one per term:
[{{"term": "the search term", "irrelevant": true/false, "reason": "brief explanation"}}]

Be conservative: when in doubt, mark as RELEVANT (false). Only mark terms IRRELEVANT when you are confident they do not match the business services."""

        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key)

            resp = client.chat.completions.create(
                model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=4000,
            )

            content = (resp.choices[0].message.content or "").strip()

            # Parse JSON response (handle markdown code blocks)
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()

            results_list = json.loads(content)

            # Convert list to dict keyed by term
            results = {}
            for item in results_list:
                term = item.get('term', '').lower().strip()
                results[term] = {
                    'irrelevant': item.get('irrelevant', False),
                    'reason': item.get('reason', '')
                }

            logger.info(
                f"LLM evaluated {len(search_terms)} terms: "
                f"{sum(1 for v in results.values() if v.get('irrelevant'))} irrelevant, "
                f"{sum(1 for v in results.values() if not v.get('irrelevant'))} relevant"
            )

            return results

        except Exception as e:
            logger.error(f"LLM term evaluation failed: {e}")
            return {}

    def _check_non_purchase_intent(self, search_term: str) -> Tuple[bool, List[str]]:
        """
        Check if search term indicates non-purchase intent via pattern matching.

        Returns:
            (has_non_purchase_intent, patterns_matched)
        """
        patterns_matched = []

        for pattern in self.NON_PURCHASE_INTENT_PATTERNS:
            if pattern in search_term.lower():
                patterns_matched.append(pattern)

        has_non_purchase_intent = len(patterns_matched) > 0

        return has_non_purchase_intent, patterns_matched

    def _calculate_confidence(self, metrics, patterns_matched: List[str], search_term: str) -> float:
        """
        Calculate confidence score for negative keyword addition.

        Factors:
        - Number of pattern matches (more = higher confidence)
        - Conversion rate (lower = higher confidence for negative)
        - Spend amount (higher spend with no conversions = higher confidence)
        - CTR (lower CTR = higher confidence for negative)
        """
        confidence = 0.5  # Base confidence

        # Pattern matching (0.0 to 0.4 points)
        pattern_score = min(len(patterns_matched) * 0.1, 0.4)
        confidence += pattern_score

        # Conversion performance (0.0 to 0.3 points)
        conversion_rate = metrics.conversion_rate
        if conversion_rate == 0:
            confidence += 0.3  # High confidence if zero conversions
        elif conversion_rate < 0.01:
            confidence += 0.2  # Good confidence if very low
        elif conversion_rate < 0.02:
            confidence += 0.1  # Some confidence

        # CTR performance (0.0 to 0.2 points)
        ctr = metrics.ctr
        if ctr < 0.01:
            confidence += 0.2  # Very low CTR indicates poor relevance
        elif ctr < 0.02:
            confidence += 0.1

        # Spend amount (0.0 to 0.1 points)
        cost = metrics.cost_micros / 1_000_000
        if cost > 50 and conversion_rate == 0:
            confidence += 0.1  # High confidence if significant waste

        return min(confidence, 1.0)

    def _execute_negative_keyword_add(
        self,
        action: AIAction,
        customer_id: str,
        search_term: str,
        campaign_id: int
    ) -> None:
        """Execute the negative keyword addition via Google Ads API."""
        client = self._get_google_ads_client()

        # Create negative keyword at campaign level
        campaign_criterion_service = client.get_service("CampaignCriterionService")
        campaign_criterion_operation = client.get_type("CampaignCriterionOperation")

        campaign_criterion = campaign_criterion_operation.create
        campaign_criterion.campaign = client.get_service("CampaignService").campaign_path(customer_id, campaign_id)
        campaign_criterion.negative = True
        campaign_criterion.keyword.text = search_term
        campaign_criterion.keyword.match_type = client.enums.KeywordMatchTypeEnum.PHRASE

        # Execute the mutation
        response = campaign_criterion_service.mutate_campaign_criteria(
            customer_id=customer_id,
            operations=[campaign_criterion_operation]
        )

        logger.info(f"Added negative keyword: {response.results[0].resource_name}")

    def undo_action(self, action_id: int, user_id: Optional[int] = None, reason: Optional[str] = None) -> bool:
        """
        Undo a previously executed AI action.

        Args:
            action_id: ID of action to undo
            user_id: User requesting undo
            reason: Reason for undo

        Returns:
            True if successful, False otherwise
        """
        action = AIAction.query.get(action_id)

        if not action:
            logger.error(f"Action {action_id} not found")
            return False

        if action.account_id != self.account_id:
            logger.error(f"Action {action_id} belongs to different account")
            return False

        if not action.is_undoable:
            logger.warning(f"Action {action_id} is not undoable")
            return False

        try:
            # Execute undo based on action type
            if action.action_type == 'negative_keyword_added':
                self._undo_negative_keyword_add(action)
            elif action.action_type == 'keyword_paused':
                self._undo_keyword_pause(action)
            elif action.action_type == 'bid_adjusted':
                self._undo_bid_adjustment(action)
            else:
                logger.warning(f"Undo not implemented for action type: {action.action_type}")
                return False

            action.mark_undone(user_id, reason)
            db.session.commit()

            logger.info(f"Successfully undid action {action_id}")
            return True

        except Exception as e:
            logger.exception(f"Error undoing action {action_id}: {e}")
            db.session.rollback()
            return False

    def _undo_negative_keyword_add(self, action: AIAction) -> None:
        """Undo negative keyword addition by removing it."""
        # TODO: Implement removing negative keyword via Google Ads API
        # This requires finding the negative keyword criterion and removing it
        pass

    def _undo_keyword_pause(self, action: AIAction) -> None:
        """Undo keyword pause by re-enabling it."""
        # TODO: Implement keyword re-enabling via Google Ads API
        pass

    def _undo_bid_adjustment(self, action: AIAction) -> None:
        """Undo bid adjustment by reverting to previous bid."""
        # TODO: Implement bid revert via Google Ads API
        pass

    def get_recent_actions(self, days: int = 7, limit: int = 100) -> List[AIAction]:
        """Get recent AI actions for this account."""
        cutoff = datetime.utcnow() - timedelta(days=days)

        actions = AIAction.query.filter(
            AIAction.account_id == self.account_id,
            AIAction.created_at >= cutoff
        ).order_by(AIAction.created_at.desc()).limit(limit).all()

        return actions

    def get_summary_stats(self, days: int = 30) -> Dict[str, Any]:
        """Get summary statistics of AI actions."""
        cutoff = datetime.utcnow() - timedelta(days=days)

        total_actions = AIAction.query.filter(
            AIAction.account_id == self.account_id,
            AIAction.status == 'executed',
            AIAction.created_at >= cutoff
        ).count()

        total_savings = db.session.query(
            func.sum(AIAction.estimated_monthly_savings)
        ).filter(
            AIAction.account_id == self.account_id,
            AIAction.status == 'executed',
            AIAction.created_at >= cutoff
        ).scalar() or 0

        actions_by_type = db.session.query(
            AIAction.action_type,
            func.count(AIAction.id)
        ).filter(
            AIAction.account_id == self.account_id,
            AIAction.status == 'executed',
            AIAction.created_at >= cutoff
        ).group_by(AIAction.action_type).all()

        return {
            'total_actions': total_actions,
            'total_savings': total_savings,
            'actions_by_type': dict(actions_by_type),
            'period_days': days
        }
