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
from sqlalchemy import func, and_, text

from app import db
from app.models import Account, GoogleAdsAuth
from app.models_ai_actions import AIAction, AIActionRule
from app.google.utils_ads import client_from_refresh

logger = logging.getLogger(__name__)


def _is_sandbox_mode(account_id: int) -> bool:
    """Return True if AI Sandbox mode is active for this account."""
    try:
        with db.engine.connect() as conn:
            row = conn.execute(
                text("SELECT setting_value FROM account_settings "
                     "WHERE account_id = :aid AND setting_key = 'ai_sandbox_mode' LIMIT 1"),
                {"aid": account_id},
            ).first()
            return bool(row and row[0] == "1")
    except Exception:
        return False


class GoogleAdsAutoExecutor:
    """Service for automatically executing safe Google Ads optimizations"""

    # Non-purchase intent indicators (keywords/phrases that suggest no buying intent)
    # Named intent groups — each can be enabled/disabled per account and extended
    # with account-specific custom patterns.
    INTENT_GROUPS = {
        'diy': {
            'name': 'DIY / Do It Yourself',
            'description': 'People looking to do it themselves rather than hire a professional',
            'patterns': [
                'how to', 'diy', 'tutorial', 'guide', 'tips', 'instructions',
                'step by step', 'yourself', 'myself', 'homemade', 'manual',
            ],
            'enabled_by_default': True,
        },
        'free': {
            'name': 'Free / Cheap Alternatives',
            'description': 'People seeking free or heavily discounted options',
            'patterns': [
                'free', 'cheap', 'discount', 'coupon', 'deal', 'sale', 'clearance',
            ],
            'enabled_by_default': True,
        },
        'informational': {
            'name': 'Informational / Research',
            'description': 'Early-stage researchers not yet ready to buy or hire',
            'patterns': [
                'what is', 'definition', 'meaning', 'wiki', 'wikipedia', 'learn',
                'course', 'training', 'certification', 'school', 'class', 'education',
                'review', 'reviews', 'comparison', 'compare', 'vs', 'versus',
                'alternatives', 'which', 'should i', 'top 10',
            ],
            'enabled_by_default': True,
        },
        'job_seeking': {
            'name': 'Job Seeking / Employment',
            'description': 'People looking for jobs, not services',
            'patterns': [
                'job', 'jobs', 'career', 'careers', 'hiring', 'employment', 'resume',
                'salary', 'work from home', 'remote work', 'part time', 'full time', 'apply',
            ],
            'enabled_by_default': True,
        },
        'media': {
            'name': 'Images / Videos',
            'description': 'Browsing images or videos — informational, not buying',
            'patterns': [
                'image', 'images', 'photo', 'photos', 'picture', 'pictures',
                'video', 'videos', 'clip', 'clips', 'youtube', 'watch',
            ],
            'enabled_by_default': True,
        },
        'wrong_product': {
            'name': 'Wrong Product / Unrelated Category',
            'description': 'Searching for products or categories you do not offer',
            'patterns': [
                'software', 'app', 'game', 'toy', 'used',
            ],
            'enabled_by_default': False,
        },
    }

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
        self.negative_keyword_examples = self.account.get_negative_keyword_examples() or ''

        # Build the active pattern list from enabled intent groups + account customisations
        self._active_patterns, self._active_groups_meta = self._load_active_patterns()

    def _load_active_patterns(self) -> Tuple[List[str], dict]:
        """
        Build the active pattern list by merging global INTENT_GROUPS with
        account-level customisations stored in account_settings (key:
        'intent_group_settings', JSON value).

        Returns:
            (flat_patterns, groups_meta)
            flat_patterns — deduplicated list of all active patterns
            groups_meta   — dict mapping group_key -> {name, enabled, patterns, custom}
        """
        import json

        # Load account-level overrides from account_settings table
        account_overrides: dict = {}
        try:
            with db.engine.connect() as conn:
                row = conn.execute(
                    text("""
                        SELECT setting_value FROM account_settings
                        WHERE account_id = :aid AND setting_key = 'intent_group_settings'
                        LIMIT 1
                    """),
                    {"aid": self.account_id}
                ).first()
            if row and row[0]:
                account_overrides = json.loads(row[0])
        except Exception:
            pass  # Table may not exist yet — use defaults

        groups_meta: dict = {}
        flat_patterns: List[str] = []

        for group_key, group_def in self.INTENT_GROUPS.items():
            override = account_overrides.get(group_key, {})
            enabled = override.get('enabled', group_def['enabled_by_default'])
            extra_patterns = override.get('extra_patterns', [])
            active_patterns = group_def['patterns'] + [p for p in extra_patterns if p]

            groups_meta[group_key] = {
                'name': group_def['name'],
                'description': group_def['description'],
                'enabled': enabled,
                'patterns': group_def['patterns'],
                'extra_patterns': extra_patterns,
            }

            if enabled:
                flat_patterns.extend(active_patterns)

        # Account-level custom groups (arbitrary groups not in INTENT_GROUPS)
        custom_groups = account_overrides.get('custom_groups', [])
        for cg in custom_groups:
            if cg.get('enabled', True) and cg.get('patterns'):
                flat_patterns.extend(cg['patterns'])
                groups_meta[f"custom_{cg.get('name', 'group')}"] = {
                    'name': cg.get('name', 'Custom Group'),
                    'description': cg.get('description', ''),
                    'enabled': True,
                    'patterns': cg['patterns'],
                    'extra_patterns': [],
                }

        # Deduplicate while preserving order
        seen: set = set()
        deduped: List[str] = []
        for p in flat_patterns:
            if p not in seen:
                seen.add(p)
                deduped.append(p)

        return deduped, groups_meta

    # ── Fix 1: Persist search terms so ML trainer has data ───────────────────

    def _persist_search_terms(self, all_rows: list) -> None:
        """
        Upsert search terms from a Google Ads API result set into the
        search_terms DB table so the WasteClassifier has data to train on.
        Uses INSERT … ON DUPLICATE KEY UPDATE keyed on (search_term).
        Silently skips if the table schema is incompatible.
        """
        if not all_rows:
            return
        try:
            today = datetime.utcnow().date().isoformat()
            with db.engine.begin() as conn:
                for row in all_rows:
                    term = row.search_term_view.search_term.lower().strip()
                    conn.execute(text("""
                        INSERT INTO search_terms
                            (search_term, clicks, impressions, cost_micros, conversions,
                             added_as_keyword, added_as_negative)
                        VALUES
                            (:term, :clicks, :impressions, :cost_micros, :conv, FALSE, FALSE)
                        ON DUPLICATE KEY UPDATE
                            clicks        = clicks + VALUES(clicks),
                            impressions   = impressions + VALUES(impressions),
                            cost_micros   = cost_micros + VALUES(cost_micros),
                            conversions   = conversions + VALUES(conversions)
                    """), {
                        "term":        term,
                        "clicks":      row.metrics.clicks,
                        "impressions": row.metrics.impressions,
                        "cost_micros": row.metrics.cost_micros,
                        "conv":        row.metrics.conversions,
                    })
            logger.info(f"Account {self.account_id}: persisted {len(all_rows)} search terms to DB")
        except Exception as e:
            logger.debug(f"Search term persistence skipped (schema mismatch?): {e}")

    # ── Fix 2: ML WasteClassifier as a third-pass signal ─────────────────────

    def _ml_classify_terms(self, rows: list) -> dict:
        """
        Run the trained WasteClassifierModel against a list of search term rows.
        Returns: {search_term: (row, waste_probability)} for terms above threshold.
        Falls back gracefully if no model is trained yet.
        """
        ml_flagged: dict = {}
        try:
            from app.ml.predictor import MLPredictor
            predictor = MLPredictor(self.account_id)
            for row in rows:
                term = row.search_term_view.search_term.lower().strip()
                cost = row.metrics.cost_micros / 1_000_000
                result = predictor.classify_search_term(
                    search_term=term,
                    cost=cost,
                    clicks=row.metrics.clicks,
                    impressions=row.metrics.impressions,
                    conversions=row.metrics.conversions,
                    ctr=row.metrics.ctr,
                )
                prob = result.get('waste_probability', 0.0)
                if prob >= 0.55:  # Confident enough to flag
                    ml_flagged[term] = (row, prob)
        except Exception as e:
            logger.debug(f"WasteClassifier pass skipped (model not trained?): {e}")
        return ml_flagged

    # ── Fix 3: Cross-system dedup ─────────────────────────────────────────────

    def _is_already_negated(self, search_term: str, campaign_id_str: str) -> bool:
        """
        Return True if this term was already added as a negative keyword
        for this account+campaign in the last 60 days, by either the
        auto-executor (ai_actions) or the agent framework (negative_keywords).
        Prevents both systems from duplicating work.
        """
        try:
            cutoff = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            cutoff = cutoff.replace(day=cutoff.day - 60) if cutoff.day > 60 else cutoff  # safe 60-day lookback

            # Check ai_actions table
            existing = AIAction.query.filter(
                AIAction.account_id == self.account_id,
                AIAction.action_type == 'negative_keyword_added',
                AIAction.status.in_(['executed', 'pending']),
                AIAction.campaign_id == campaign_id_str,
                AIAction.created_at >= datetime.utcnow().replace(
                    hour=0, minute=0, second=0, microsecond=0
                ).replace(year=datetime.utcnow().year,
                          month=datetime.utcnow().month,
                          day=max(1, datetime.utcnow().day - 60))
            ).filter(
                AIAction.title.contains(f"'{search_term}'")
            ).first()
            if existing:
                return True

            # Check negative_keywords table (agent framework)
            row = db.session.execute(text("""
                SELECT id FROM negative_keywords
                WHERE account_id = :aid AND keyword_text = :term AND campaign_id = :cid
                LIMIT 1
            """), {"aid": self.account_id, "term": search_term, "cid": campaign_id_str}).first()
            if row:
                return True

        except Exception as e:
            logger.debug(f"Dedup check failed, allowing term: {e}")

        return False

    # ── Fix 4: Feedback loop — mark term as negated in DB ────────────────────

    def _smart_match_type(self, search_term: str) -> str:
        """
        Choose the safest match type for a negative keyword.

        Short terms (1-2 words) get EXACT match — broad enough to catch the term,
        narrow enough not to accidentally block related valuable searches.
        Long-tail terms (3+ words) get PHRASE match — more targeted blocking.

        Examples:
          "pool" → EXACT  (avoid blocking "swimming pool service" if we only want to block generic "pool")
          "pool party" → EXACT
          "above ground pool" → PHRASE  (block any query containing this phrase)
          "above ground pool installation" → PHRASE
        """
        words = search_term.strip().split()
        return 'EXACT' if len(words) <= 2 else 'PHRASE'

    def _mark_search_term_negated(self, search_term: str) -> None:
        """
        Mark search_term.added_as_negative = TRUE after execution.
        This feeds back into the WasteClassifier training labels so the
        model learns from confirmed bad terms over time.
        """
        try:
            with db.engine.begin() as conn:
                conn.execute(text("""
                    UPDATE search_terms SET added_as_negative = TRUE
                    WHERE search_term = :term
                """), {"term": search_term})
        except Exception as e:
            logger.debug(f"Feedback loop update skipped: {e}")

    def _get_google_ads_client(self):
        """Get Google Ads API client."""
        if not self.google_ads_client:
            customer_id = None
            manager_id = None
            refresh_token = None

            # 1. Get customer_id from accounts table (primary source)
            with db.engine.connect() as conn:
                row = conn.execute(
                    text("SELECT google_ads_customer_id, google_ads_manager_id FROM accounts WHERE id = :aid"),
                    {"aid": self.account_id}
                ).first()
                if row:
                    customer_id = row[0]
                    manager_id = row[1]

            # 2. Get refresh_token from google_oauth_tokens (where Flask stores OAuth)
            with db.engine.connect() as conn:
                row = conn.execute(
                    text("SELECT credentials_json FROM google_oauth_tokens WHERE account_id = :aid AND product = 'ads' LIMIT 1"),
                    {"aid": self.account_id}
                ).first()
                if row and row[0]:
                    creds = row[0]
                    if isinstance(creds, str):
                        creds = json.loads(creds)
                    refresh_token = creds.get('refresh_token') if isinstance(creds, dict) else None

            # 3. Fallback to GoogleAdsAuth table if needed
            if not customer_id or not refresh_token:
                ads_auth = GoogleAdsAuth.query.filter_by(account_id=self.account_id).first()
                if ads_auth:
                    if not customer_id:
                        customer_id = ads_auth.customer_id
                    if not manager_id:
                        manager_id = ads_auth.manager_customer_id
                    if not refresh_token:
                        refresh_token = ads_auth.refresh_token

            if not customer_id:
                raise ValueError(f"Account {self.account_id} has no Google Ads customer ID")

            if not refresh_token:
                raise ValueError(f"Account {self.account_id} has no refresh token")

            # Get manager ID if available
            login_customer_id = manager_id or customer_id

            # Store for later use
            self._refresh_token = refresh_token
            self._customer_id = customer_id

            self.google_ads_client = client_from_refresh(
                refresh_token,
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

            # Get customer ID (set by _get_google_ads_client)
            customer_id = self._customer_id

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
                    metrics.ctr
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

            # Fix 1: Persist raw search terms to DB for ML training
            self._persist_search_terms(all_rows)

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

            # PASS 2: ML WasteClassifier for terms not caught by patterns
            ml_flagged = {}   # term -> (row, waste_probability)
            if remaining_rows:
                ml_flagged = self._ml_classify_terms(remaining_rows)
                remaining_rows = [
                    r for r in remaining_rows
                    if r.search_term_view.search_term.lower().strip() not in ml_flagged
                ]
                if ml_flagged:
                    logger.info(f"Account {self.account_id}: ML WasteClassifier flagged {len(ml_flagged)} terms")

            # PASS 3: LLM-based business relevance for remaining terms
            has_llm_context = bool(self.business_description or self.negative_keyword_examples)
            llm_flagged = {}  # term -> (row, reason)
            if remaining_rows and has_llm_context:
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
            elif remaining_rows and not has_llm_context:
                logger.warning(
                    f"Account {self.account_id}: No business_description or negative_keyword_examples set. "
                    f"Skipping LLM relevance check for {len(remaining_rows)} search terms. "
                    f"Set account.business_description or account.negative_keyword_examples to enable intelligent negative keyword detection."
                )

            # Create actions for all flagged terms
            actions_created = []
            review_queued = 0   # Terms with conversions — held for human review

            # Process pattern-matched terms (Pass 1)
            for search_term, (row, patterns_matched) in pattern_flagged.items():
                if not self._check_daily_limit('negative_keyword_added'):
                    break
                # Fix 3: cross-system dedup
                if self._is_already_negated(search_term, str(row.campaign.id)):
                    logger.debug(f"Skipping already-negated term: '{search_term}'")
                    continue

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
                        'conversion_rate': conversions / row.metrics.clicks if row.metrics.clicks > 0 else 0,
                        'lookback_days': lookback_days
                    },
                    status='pending_review' if _is_sandbox_mode(self.account_id) else 'pending'
                )
                db.session.add(action)
                actions_created.append(action)

                if not dry_run:
                    if conversions >= 1.0:
                        # Conversion Guard: term had conversions → queue for human review
                        review_queued += 1
                        logger.info(
                            f"Queued for review (pattern): '{search_term}' "
                            f"had {conversions:.0f} conversion(s) — not auto-executing"
                        )
                    else:
                        try:
                            match_type = self._smart_match_type(search_term)
                            resource_name = self._execute_negative_keyword_add(
                                action, customer_id, search_term, row.campaign.id, match_type
                            )
                            action.mark_executed()
                            if resource_name and action.after_value:
                                action.after_value = {
                                    **action.after_value,
                                    'resource_name': resource_name,
                                    'match_type': match_type,
                                }
                            self._mark_search_term_negated(search_term)
                            logger.info(
                                f"Added negative keyword (pattern/{match_type}): "
                                f"'{search_term}' to campaign {row.campaign.name}"
                            )
                        except Exception as e:
                            action.mark_failed(str(e))
                            logger.error(f"Failed to add negative keyword '{search_term}': {e}")

            # Process ML WasteClassifier terms (Pass 2)
            for search_term, (row, waste_prob) in ml_flagged.items():
                if not self._check_daily_limit('negative_keyword_added'):
                    break
                # Fix 3: cross-system dedup
                if self._is_already_negated(search_term, str(row.campaign.id)):
                    continue

                cost = row.metrics.cost_micros / 1_000_000
                conversions = row.metrics.conversions
                estimated_savings = cost if conversions == 0 else cost * 0.8
                confidence = min(0.88, 0.70 + waste_prob * 0.25)  # Scale 0.55-1.0 prob → 0.84-0.95

                action = AIAction(
                    account_id=self.account_id,
                    action_type='negative_keyword_added',
                    title=f"Block ML-Predicted Waste: '{search_term}'",
                    description=f"ML model predicted {waste_prob:.0%} waste probability. Spent ${cost:.2f} with {conversions} conversions.",
                    campaign_id=str(row.campaign.id),
                    campaign_name=row.campaign.name,
                    ad_group_id=str(row.ad_group.id),
                    ad_group_name=row.ad_group.name,
                    before_value={'search_term': search_term, 'status': 'active'},
                    after_value={'search_term': search_term, 'status': 'excluded'},
                    estimated_monthly_savings=estimated_savings,
                    confidence_score=confidence,
                    reasoning=f"WasteClassifier model predicted {waste_prob:.0%} probability of waste for '{search_term}'. "
                             f"Performance: ${cost:.2f} spent, {row.metrics.clicks} clicks, {conversions} conversions.",
                    data_used={
                        'search_term': search_term,
                        'detection_method': 'ml_waste_classifier',
                        'waste_probability': waste_prob,
                        'impressions': row.metrics.impressions,
                        'clicks': row.metrics.clicks,
                        'conversions': conversions,
                        'cost': cost,
                        'ctr': row.metrics.ctr,
                        'conversion_rate': conversions / row.metrics.clicks if row.metrics.clicks > 0 else 0,
                        'lookback_days': lookback_days
                    },
                    status='pending_review' if _is_sandbox_mode(self.account_id) else 'pending'
                )
                db.session.add(action)
                actions_created.append(action)

                if not dry_run:
                    if conversions >= 1.0:
                        # Conversion Guard: term had conversions → queue for human review
                        review_queued += 1
                        logger.info(
                            f"Queued for review (ML): '{search_term}' "
                            f"had {conversions:.0f} conversion(s) — not auto-executing"
                        )
                    else:
                        try:
                            match_type = self._smart_match_type(search_term)
                            resource_name = self._execute_negative_keyword_add(
                                action, customer_id, search_term, row.campaign.id, match_type
                            )
                            action.mark_executed()
                            if resource_name and action.after_value:
                                action.after_value = {
                                    **action.after_value,
                                    'resource_name': resource_name,
                                    'match_type': match_type,
                                }
                            self._mark_search_term_negated(search_term)
                            logger.info(
                                f"Added negative keyword (ML/{match_type}): "
                                f"'{search_term}' to campaign {row.campaign.name}"
                            )
                        except Exception as e:
                            action.mark_failed(str(e))
                            logger.error(f"Failed to add negative keyword (ML) '{search_term}': {e}")

            # Process LLM-flagged terms (Pass 3)
            for search_term, (row, reason) in llm_flagged.items():
                if not self._check_daily_limit('negative_keyword_added'):
                    break
                # Fix 3: cross-system dedup
                if self._is_already_negated(search_term, str(row.campaign.id)):
                    continue

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
                        'conversion_rate': conversions / row.metrics.clicks if row.metrics.clicks > 0 else 0,
                        'lookback_days': lookback_days
                    },
                    status='pending_review' if _is_sandbox_mode(self.account_id) else 'pending'
                )
                db.session.add(action)
                actions_created.append(action)

                if not dry_run:
                    if conversions >= 1.0:
                        # Conversion Guard: term had conversions → queue for human review
                        review_queued += 1
                        logger.info(
                            f"Queued for review (LLM): '{search_term}' "
                            f"had {conversions:.0f} conversion(s) — not auto-executing"
                        )
                    else:
                        try:
                            match_type = self._smart_match_type(search_term)
                            resource_name = self._execute_negative_keyword_add(
                                action, customer_id, search_term, row.campaign.id, match_type
                            )
                            action.mark_executed()
                            if resource_name and action.after_value:
                                action.after_value = {
                                    **action.after_value,
                                    'resource_name': resource_name,
                                    'match_type': match_type,
                                }
                            self._mark_search_term_negated(search_term)
                            logger.info(
                                f"Added negative keyword (LLM/{match_type}): "
                                f"'{search_term}' to campaign {row.campaign.name}"
                            )
                        except Exception as e:
                            action.mark_failed(str(e))
                            logger.error(f"Failed to add negative keyword '{search_term}': {e}")

            db.session.commit()

            executed_count = sum(1 for a in actions_created if a.status == 'executed')
            logger.info(
                f"Account {self.account_id}: {len(actions_created)} actions "
                f"[executed={executed_count}, review_queue={review_queued}] "
                f"(pattern={len(pattern_flagged)}, ml={len(ml_flagged)}, llm={len(llm_flagged)}) "
                f"{'DRY RUN' if dry_run else ''}"
            )
            if review_queued:
                logger.info(
                    f"Account {self.account_id}: {review_queued} term(s) held in pending review queue "
                    f"because they had ≥1 conversion — visit AI change log to approve or dismiss."
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
        business_context = f"Business: {self.business_description}" if self.business_description else ""
        if self.business_services:
            business_context += f"\nServices offered: {self.business_services}"
        if self.negative_keyword_examples:
            business_context += f"\n\nBusiness-specific keyword guidance:\n{self.negative_keyword_examples}"

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

        for pattern in self._active_patterns:
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
        # Calculate conversion rate manually (conversions / clicks)
        clicks = metrics.clicks
        conversions = metrics.conversions
        conversion_rate = conversions / clicks if clicks > 0 else 0

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
        campaign_id: int,
        match_type: str = 'PHRASE',
    ) -> str:
        """
        Execute the negative keyword addition via Google Ads API.

        Args:
            match_type: 'EXACT' for 1-2 word terms, 'PHRASE' for 3+ words.

        Returns:
            resource_name of the created criterion (used for undo).
        """
        client = self._get_google_ads_client()

        # Create negative keyword at campaign level
        campaign_criterion_service = client.get_service("CampaignCriterionService")
        campaign_criterion_operation = client.get_type("CampaignCriterionOperation")

        campaign_criterion = campaign_criterion_operation.create
        campaign_criterion.campaign = client.get_service("CampaignService").campaign_path(customer_id, campaign_id)
        campaign_criterion.negative = True
        campaign_criterion.keyword.text = search_term

        match_type_enum = (
            client.enums.KeywordMatchTypeEnum.EXACT
            if match_type == 'EXACT'
            else client.enums.KeywordMatchTypeEnum.PHRASE
        )
        campaign_criterion.keyword.match_type = match_type_enum

        # Execute the mutation
        response = campaign_criterion_service.mutate_campaign_criteria(
            customer_id=customer_id,
            operations=[campaign_criterion_operation]
        )

        resource_name = response.results[0].resource_name
        logger.info(f"Added negative keyword [{match_type}]: {resource_name}")
        return resource_name

    def _resolve_keyword_google_ids(self, keyword_local_id: int) -> Optional[dict]:
        """
        Look up the Google resource IDs needed to mutate a keyword:
        criterion_id, google ad_group_id, and keyword text/match_type.
        Returns None if the keyword was never synced from Google.
        """
        row = db.session.execute(text("""
            SELECT k.google_keyword_id, k.text, k.match_type, k.max_cpc_cents,
                   ag.google_ad_group_id
            FROM keywords k
            JOIN ad_groups ag ON ag.id = k.ad_group_id
            WHERE k.id = :kid
        """), {"kid": keyword_local_id}).mappings().first()
        if not row or not row["google_keyword_id"] or not row["google_ad_group_id"]:
            return None
        return dict(row)

    def execute_pause_keyword(self, keyword_local_id: int) -> str:
        """
        Pause a keyword in the real Google Ads account.
        Returns the mutated resource_name.
        """
        ids = self._resolve_keyword_google_ids(keyword_local_id)
        if not ids:
            raise ValueError(f"Keyword {keyword_local_id} has no Google IDs — sync first")

        client = self._get_google_ads_client()
        customer_id = self._customer_id

        svc = client.get_service("AdGroupCriterionService")
        op = client.get_type("AdGroupCriterionOperation")
        criterion = op.update
        criterion.resource_name = svc.ad_group_criterion_path(
            customer_id, ids["google_ad_group_id"], ids["google_keyword_id"]
        )
        criterion.status = client.enums.AdGroupCriterionStatusEnum.PAUSED
        op.update_mask.paths.append("status")

        response = svc.mutate_ad_group_criteria(customer_id=customer_id, operations=[op])
        resource_name = response.results[0].resource_name
        logger.info("Paused keyword in Google Ads: %s", resource_name)
        return resource_name

    def execute_change_match_type(self, keyword_local_id: int, to: str = "phrase") -> dict:
        """
        Google Ads does not allow changing a keyword's match type in place.
        The standard pattern: create a new keyword with the target match type,
        then pause the original.

        Returns {"created": resource_name, "paused": resource_name}.
        """
        ids = self._resolve_keyword_google_ids(keyword_local_id)
        if not ids:
            raise ValueError(f"Keyword {keyword_local_id} has no Google IDs — sync first")

        client = self._get_google_ads_client()
        customer_id = self._customer_id

        agc_service = client.get_service("AdGroupCriterionService")
        ag_service = client.get_service("AdGroupService")

        match_enum = {
            "exact": client.enums.KeywordMatchTypeEnum.EXACT,
            "phrase": client.enums.KeywordMatchTypeEnum.PHRASE,
            "broad": client.enums.KeywordMatchTypeEnum.BROAD,
        }.get((to or "phrase").lower(), client.enums.KeywordMatchTypeEnum.PHRASE)

        # 1. Create replacement keyword with the new match type
        create_op = client.get_type("AdGroupCriterionOperation")
        new_crit = create_op.create
        new_crit.ad_group = ag_service.ad_group_path(customer_id, ids["google_ad_group_id"])
        new_crit.status = client.enums.AdGroupCriterionStatusEnum.ENABLED
        new_crit.keyword.text = ids["text"]
        new_crit.keyword.match_type = match_enum
        if ids.get("max_cpc_cents"):
            new_crit.cpc_bid_micros = int(ids["max_cpc_cents"]) * 10000

        # 2. Pause the original broad keyword
        pause_op = client.get_type("AdGroupCriterionOperation")
        old_crit = pause_op.update
        old_crit.resource_name = agc_service.ad_group_criterion_path(
            customer_id, ids["google_ad_group_id"], ids["google_keyword_id"]
        )
        old_crit.status = client.enums.AdGroupCriterionStatusEnum.PAUSED
        pause_op.update_mask.paths.append("status")

        response = agc_service.mutate_ad_group_criteria(
            customer_id=customer_id, operations=[create_op, pause_op]
        )
        created = response.results[0].resource_name
        paused = response.results[1].resource_name
        logger.info("Match type change: created %s, paused %s", created, paused)
        return {"created": created, "paused": paused}

    def execute_update_budget(self, campaign_local_id: int, new_budget_micros: int) -> str:
        """
        Update a campaign's daily budget in the real Google Ads account.
        Looks up the campaign's budget resource via GAQL, then mutates it.
        Returns the mutated budget resource_name.
        """
        row = db.session.execute(text(
            "SELECT google_campaign_id FROM ads_campaigns WHERE id = :cid"
        ), {"cid": campaign_local_id}).first()
        if not row or not row[0]:
            raise ValueError(f"Campaign {campaign_local_id} has no Google ID — sync first")
        google_campaign_id = row[0]

        client = self._get_google_ads_client()
        customer_id = self._customer_id

        # Find the budget resource attached to this campaign
        ga_service = client.get_service("GoogleAdsService")
        query = (
            "SELECT campaign.id, campaign.campaign_budget, "
            "campaign_budget.explicitly_shared "
            f"FROM campaign WHERE campaign.id = {int(google_campaign_id)}"
        )
        budget_resource = None
        shared = False
        for batch in ga_service.search_stream(customer_id=customer_id, query=query):
            for r in batch.results:
                budget_resource = r.campaign.campaign_budget
                shared = bool(r.campaign_budget.explicitly_shared)
        if not budget_resource:
            raise ValueError(f"No budget found for campaign {google_campaign_id}")
        if shared:
            raise ValueError(
                "This campaign uses a shared budget — adjust it in Google Ads "
                "to avoid changing other campaigns unintentionally."
            )

        budget_service = client.get_service("CampaignBudgetService")
        op = client.get_type("CampaignBudgetOperation")
        budget = op.update
        budget.resource_name = budget_resource
        budget.amount_micros = int(new_budget_micros)
        op.update_mask.paths.append("amount_micros")

        response = budget_service.mutate_campaign_budgets(
            customer_id=customer_id, operations=[op]
        )
        resource_name = response.results[0].resource_name
        logger.info("Updated budget: %s -> %d micros", resource_name, new_budget_micros)
        return resource_name

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
        """
        Undo a negative keyword by removing the campaign criterion via Google Ads API.

        Requires the resource_name to have been stored in action.after_value at execution
        time (populated since the smart-match-type upgrade). Falls back to a GAQL lookup
        if the resource_name is missing (for negatives added before the upgrade).
        """
        client = self._get_google_ads_client()
        customer_id = self._customer_id

        # Prefer the stored resource_name (fast path)
        resource_name = None
        if action.after_value and isinstance(action.after_value, dict):
            resource_name = action.after_value.get('resource_name')

        # Fallback: query the API to find the criterion
        if not resource_name:
            if not action.campaign_id:
                raise ValueError(
                    f"Action {action.id} has no campaign_id and no resource_name — cannot undo."
                )
            search_term = action.after_value.get('search_term') if action.after_value else None
            if not search_term:
                raise ValueError(
                    f"Action {action.id} has no search_term in after_value — cannot undo."
                )
            ga_service = client.get_service("GoogleAdsService")
            campaign_path = client.get_service("CampaignService").campaign_path(
                customer_id, action.campaign_id
            )
            escaped_term = search_term.replace("'", "\\'")
            query = (
                f"SELECT campaign_criterion.resource_name"
                f" FROM campaign_criterion"
                f" WHERE campaign_criterion.campaign = '{campaign_path}'"
                f"   AND campaign_criterion.negative = TRUE"
                f"   AND campaign_criterion.keyword.text = '{escaped_term}'"
                f" LIMIT 1"
            )
            stream = ga_service.search_stream(customer_id=customer_id, query=query)
            for batch in stream:
                for row in batch.results:
                    resource_name = row.campaign_criterion.resource_name
                    break
                if resource_name:
                    break

        if not resource_name:
            raise ValueError(
                f"Could not find negative keyword criterion for action {action.id} to remove."
            )

        campaign_criterion_service = client.get_service("CampaignCriterionService")
        op = client.get_type("CampaignCriterionOperation")
        op.remove = resource_name
        campaign_criterion_service.mutate_campaign_criteria(
            customer_id=customer_id,
            operations=[op]
        )
        logger.info(f"Removed negative keyword criterion: {resource_name}")

    def _undo_keyword_pause(self, action: AIAction) -> None:
        """Undo keyword pause by re-enabling it via AdGroupCriterionService."""
        before = action.before_value or {}
        google_keyword_id = before.get("google_keyword_id") or action.keyword_id
        google_ad_group_id = before.get("google_ad_group_id") or action.ad_group_id

        if not google_keyword_id or not google_ad_group_id:
            raise ValueError(
                f"Action {action.id} missing google_keyword_id or google_ad_group_id in before_value"
            )

        client = self._get_google_ads_client()
        customer_id = self._customer_id

        svc = client.get_service("AdGroupCriterionService")
        op = client.get_type("AdGroupCriterionOperation")
        criterion = op.update
        criterion.resource_name = svc.ad_group_criterion_path(
            customer_id, str(google_ad_group_id), str(google_keyword_id)
        )
        criterion.status = client.enums.AdGroupCriterionStatusEnum.ENABLED
        op.update_mask.paths.append("status")

        response = svc.mutate_ad_group_criteria(customer_id=customer_id, operations=[op])
        resource_name = response.results[0].resource_name
        logger.info("Re-enabled keyword in Google Ads: %s", resource_name)

    def _undo_bid_adjustment(self, action: AIAction) -> None:
        """Undo bid adjustment by reverting to the previous bid stored in before_value."""
        before = action.before_value or {}
        previous_bid_micros = before.get("bid_micros") or before.get("previous_bid_micros")
        google_keyword_id = before.get("google_keyword_id") or action.keyword_id
        google_ad_group_id = before.get("google_ad_group_id") or action.ad_group_id

        if previous_bid_micros is None:
            raise ValueError(
                f"Action {action.id} has no previous bid in before_value — cannot undo"
            )
        if not google_keyword_id or not google_ad_group_id:
            raise ValueError(
                f"Action {action.id} missing google_keyword_id or google_ad_group_id in before_value"
            )

        client = self._get_google_ads_client()
        customer_id = self._customer_id

        svc = client.get_service("AdGroupCriterionService")
        op = client.get_type("AdGroupCriterionOperation")
        criterion = op.update
        criterion.resource_name = svc.ad_group_criterion_path(
            customer_id, str(google_ad_group_id), str(google_keyword_id)
        )
        criterion.effective_cpc_bid_micros = int(previous_bid_micros)
        op.update_mask.paths.append("effective_cpc_bid_micros")

        response = svc.mutate_ad_group_criteria(customer_id=customer_id, operations=[op])
        resource_name = response.results[0].resource_name
        logger.info("Reverted bid in Google Ads: %s -> %d micros", resource_name, int(previous_bid_micros))

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
