"""
Google Ads Grader Analyzer

Scoring algorithms and recommendations engine for the Google Ads Quality Checker.
"""
import logging
from typing import Dict, List, Any, Tuple
from datetime import datetime
from app.services.roi_calculator import ROICalculator

logger = logging.getLogger(__name__)


# Industry benchmarks
BENCHMARKS = {
    "quality_score_target": 7.0,
    "negative_keywords_avg": 135,
    "ctr_by_position": {
        1: 7.94,
        2: 4.95,
        3: 3.51,
        4: 2.57,
        5: 2.04,
    },
    "long_tail_target": 0.50,  # 50%+ should be 3+ words
}


class GoogleAdsAnalyzer:
    """
    Analyzes Google Ads account data and generates grading scores.
    """

    def __init__(self, account_metrics: Dict[str, Any]):
        """
        Initialize analyzer with account metrics from API client.

        Args:
            account_metrics: Dictionary of metrics from GoogleAdsGraderClient
        """
        self.metrics = account_metrics
        self.scores = {}
        self.recommendations = []

    def analyze(self) -> Dict[str, Any]:
        """
        Run complete analysis and return all scores and recommendations.

        Returns:
            Dictionary containing:
                - overall_score: 0-100
                - overall_grade: Letter grade
                - section_scores: Individual section scores
                - recommendations: List of actionable recommendations
                - detailed_metrics: Raw metrics for display
        """
        # Calculate each section score
        self.scores["wasted_spend"] = self._score_wasted_spend()
        self.scores["expanded_text_ads"] = self._score_expanded_text_ads()
        self.scores["text_ad_optimization"] = self._score_text_ad_optimization()
        self.scores["quality_score"] = self._score_quality_score()
        self.scores["ctr_optimization"] = self._score_ctr_optimization()
        self.scores["account_activity"] = self._score_account_activity()
        self.scores["long_tail_keywords"] = self._score_long_tail_keywords()
        self.scores["impression_share"] = self._score_impression_share()
        self.scores["landing_pages"] = self._score_landing_pages()
        self.scores["mobile_advertising"] = self._score_mobile_advertising()

        # Calculate overall score (weighted average)
        overall_score = self._calculate_overall_score()
        overall_grade = self._calculate_grade(overall_score)

        # Generate recommendations based on scores
        self._generate_recommendations()

        # Calculate key metrics
        quality_score_avg = self.metrics.get("quality_scores", {}).get("average", 0)
        ctr_avg = self.metrics.get("performance", {}).get("ctr", 0)

        # Waste percentage from score: score=100→0% waste, score=0→40% waste
        # Inverse: waste_pct = (100 - score) / 2.5
        waste_percentage = (100 - self.scores["wasted_spend"]) / 2.5

        # Dollar estimates from actual search term spend when available
        search_terms = self.metrics.get("search_terms", {})
        st_waste_spend = search_terms.get("waste_spend", 0)
        st_total_spend = search_terms.get("total_spend", 0)

        if st_total_spend > 0 and st_waste_spend > 0:
            # Annualise the search term window (365 days / days sampled ≈ 1)
            wasted_spend_90d = st_waste_spend / 4      # ~90-day slice
            projected_waste_12m = st_waste_spend
        else:
            wasted_spend_90d, projected_waste_12m = self._calculate_wasted_spend_dollars(waste_percentage)

        return {
            "overall_score": overall_score,
            "overall_grade": overall_grade,
            "section_scores": self.scores,
            "recommendations": self.recommendations,
            "key_metrics": {
                "quality_score_avg": quality_score_avg,
                "ctr_avg": ctr_avg,
                "wasted_spend_90d": wasted_spend_90d,
                "projected_waste_12m": projected_waste_12m,
                "waste_percentage": waste_percentage,
                "waste_term_count": search_terms.get("waste_term_count", 0),
                "top_waste_terms": sorted(
                    search_terms.get("waste_terms", []),
                    key=lambda x: x.get("cost", 0),
                    reverse=True
                )[:5],
            },
            "account_diagnostics": self._get_account_diagnostics(),
            "best_practices": self._check_best_practices(),
            "chart_data": self._prepare_chart_data(),
        }

    def _score_wasted_spend(self) -> float:
        """
        Score based on actual waste signals:
          1. Search terms matching DIY/job-seeker/informational patterns (primary)
          2. Keywords with significant spend and zero conversions (secondary, if tracking on)
        Falls back to negative keyword count ratio when no search term data exists.
        """
        search_terms = self.metrics.get("search_terms", {})
        total_st_spend = search_terms.get("total_spend", 0)
        waste_spend = search_terms.get("waste_spend", 0)

        if total_st_spend > 0:
            waste_pct = (waste_spend / total_st_spend) * 100

            # Secondary signal: non-converting keywords
            performance = self.metrics.get("performance", {})
            has_conversion_tracking = performance.get("conversions", 0) > 0
            if has_conversion_tracking:
                avg_cpa = performance.get("avg_cpa", 0)
                threshold = max(30.0, avg_cpa * 2.0) if avg_cpa > 0 else 50.0
                kw_list = self.metrics.get("keywords", {}).get("keywords", [])
                nc_spend = sum(
                    kw["cost"] for kw in kw_list
                    if kw.get("cost", 0) > threshold and kw.get("conversions", 0) == 0
                )
                total_kw_spend = sum(kw["cost"] for kw in kw_list) or 1
                nc_pct = (nc_spend / total_kw_spend) * 100
                # Blend: 70% search term signal, 30% non-converting keyword signal
                waste_pct = waste_pct * 0.70 + nc_pct * 0.30

        else:
            # No search term data — fall back to negative keyword coverage proxy
            negative_keywords = self.metrics.get("negative_keywords", 0)
            benchmark = BENCHMARKS["negative_keywords_avg"]
            coverage = min(1.0, negative_keywords / benchmark)
            # Assume 0% coverage = ~25% waste, 100% coverage = ~5% waste
            waste_pct = 25 * (1 - coverage) + 5

        # score = 100 - 2.5 * waste_pct  → 0% waste=100, 10%=75, 20%=50, 40%=0
        score = max(0.0, 100.0 - waste_pct * 2.5)
        return round(score, 1)

    def _score_expanded_text_ads(self) -> float:
        """
        Score based on percentage of expanded text ads vs old formats.
        """
        ads = self.metrics.get("ads", {})
        ad_type_counts = ads.get("ad_type_counts", {})

        total_ads = sum(ad_type_counts.values())
        if total_ads == 0:
            return 50.0

        # Modern ad types (Expanded Text Ads, Responsive Search Ads)
        modern_ads = ad_type_counts.get("EXPANDED_TEXT_AD", 0) + ad_type_counts.get("RESPONSIVE_SEARCH_AD", 0)

        percentage = (modern_ads / total_ads) * 100
        return min(100, percentage)

    def _score_text_ad_optimization(self) -> float:
        """
        Score based on RSA ad strength distribution (Google's own creative quality signal)
        combined with overall CTR performance.
        """
        ads = self.metrics.get("ads", {})
        strength_dist = ads.get("ad_strength_distribution", {})
        avg_ctr = ads.get("avg_ctr", 0)

        # RSA ad strength score (60% of total)
        strength_total = sum(strength_dist.values())
        if strength_total > 0:
            strength_score = (
                strength_dist.get("EXCELLENT", 0) * 100 +
                strength_dist.get("GOOD", 0) * 78 +
                strength_dist.get("AVERAGE", 0) * 55 +
                strength_dist.get("POOR", 0) * 20 +
                strength_dist.get("OTHER", 0) * 50
            ) / strength_total
        else:
            # Fall back to CTR variance as a weaker signal
            best_ad = ads.get("best_ad") or {}
            worst_ad = ads.get("worst_ad") or {}
            best_ctr = best_ad.get("ctr", 0)
            worst_ctr = worst_ad.get("ctr", 0)
            if best_ctr > 0:
                variance = (best_ctr - worst_ctr) / best_ctr
                strength_score = (1 - variance) * 100
            else:
                strength_score = 50.0

        # Overall CTR component (40% of total) — 4%+ is strong for home services
        ctr_score = min(100.0, (avg_ctr / 4.0) * 100)

        return round(strength_score * 0.60 + ctr_score * 0.40, 1)

    def _score_quality_score(self) -> float:
        """
        Score based on average Quality Score vs benchmark of 7.0.
        """
        qs_data = self.metrics.get("quality_scores", {})
        avg_qs = qs_data.get("average", 0)
        target = BENCHMARKS["quality_score_target"]

        if avg_qs == 0:
            return 0.0

        # Score scales from 0-100, with 7.0 being 70%, 10.0 being 100%
        score = (avg_qs / 10.0) * 100

        return min(100, max(0, score))

    def _score_ctr_optimization(self) -> float:
        """
        Score based on CTR by device and overall CTR performance.
        """
        device_performance = self.metrics.get("device_performance", {})
        overall_ctr = self.metrics.get("performance", {}).get("ctr", 0)

        # Industry average CTR is ~3-5% for search
        if overall_ctr >= 5.0:
            base_score = 100
        elif overall_ctr >= 3.0:
            base_score = 70
        elif overall_ctr >= 2.0:
            base_score = 50
        elif overall_ctr >= 1.0:
            base_score = 30
        else:
            base_score = 10

        # Bonus for consistent performance across devices
        device_ctrs = [device.get("ctr", 0) for device in device_performance.values()]
        if device_ctrs:
            avg_device_ctr = sum(device_ctrs) / len(device_ctrs)
            if avg_device_ctr > 0:
                variance = max(device_ctrs) - min(device_ctrs)
                consistency_bonus = max(0, 10 - (variance * 2))
                base_score += consistency_bonus

        return min(100, base_score)

    def _score_account_activity(self) -> float:
        """
        Score based on signals of active, quality management:
          - Ads per ad group (Google recommends ≥3 RSAs)
          - Keywords per ad group (tight grouping = better relevance)
          - Active extensions / assets
          - Conversion tracking in place
        Size of account (campaign count, keyword count) is NOT scored —
        a lean, focused account is just as valid as a large one.
        """
        ads = self.metrics.get("ads", {})
        keywords = self.metrics.get("keywords", {})
        structure = self.metrics.get("campaigns", {})
        extensions = self.metrics.get("extensions", {})
        performance = self.metrics.get("performance", {})

        ad_count = ads.get("total_ads", 0)
        ad_group_count = structure.get("ad_group_count", 0)
        keyword_count = keywords.get("total_keywords", 0)

        score = 0

        # Ads per ad group — most actionable signal of creative testing
        avg_ads_per_group = (ad_count / ad_group_count) if ad_group_count > 0 else 0
        if avg_ads_per_group >= 3:
            score += 35
        elif avg_ads_per_group >= 2:
            score += 22
        elif avg_ads_per_group >= 1:
            score += 10

        # Keywords per ad group — tighter groups = better ad/keyword relevance
        avg_kw_per_group = (keyword_count / ad_group_count) if ad_group_count > 0 else 0
        if 5 <= avg_kw_per_group <= 20:
            score += 30   # Ideal: focused themes
        elif 1 <= avg_kw_per_group < 5:
            score += 20   # Tight but might be missing coverage
        elif 21 <= avg_kw_per_group <= 50:
            score += 15   # Getting broad
        elif avg_kw_per_group > 50:
            score += 5    # Very broad grouping, relevance at risk
        elif avg_kw_per_group > 0:
            score += 10

        # Ad extensions / assets in use
        if any(extensions.values()):
            score += 20

        # Conversion tracking
        if performance.get("conversions", 0) > 0:
            score += 15

        return min(100, score)

    def _score_long_tail_keywords(self) -> float:
        """
        Score based on percentage of long-tail (3+ word) keywords.
        """
        keywords = self.metrics.get("keywords", {})
        distribution = keywords.get("word_count_distribution", {})

        total = sum(distribution.values())
        if total == 0:
            return 50.0

        long_tail_count = distribution.get("3+-word", 0)
        long_tail_percentage = long_tail_count / total

        # Target is 50%+ long-tail
        score = (long_tail_percentage / BENCHMARKS["long_tail_target"]) * 100

        return min(100, max(0, score))

    def _score_impression_share(self) -> float:
        """
        Score only on impression share LOST TO RANK (a quality/bid problem you can fix).
        Budget-lost share is reported separately as an informational metric — losing to
        budget is often a business decision and shouldn't penalise the score.
        """
        imp_share_data = self.metrics.get("impression_share", {})
        rank_lost = imp_share_data.get("rank_lost_share", 0)  # decimal, e.g. 0.25 = 25%

        # No data at all
        if rank_lost == 0 and imp_share_data.get("impression_share", 0) == 0:
            return 50.0

        rank_lost_pct = rank_lost * 100

        if rank_lost_pct < 5:
            return 95.0
        elif rank_lost_pct < 10:
            return 80.0
        elif rank_lost_pct < 20:
            return 62.0
        elif rank_lost_pct < 30:
            return 45.0
        elif rank_lost_pct < 40:
            return 28.0
        else:
            return 10.0

    def _score_landing_pages(self) -> float:
        """
        Score based on Google's own landing page experience signal (post_click_quality_score),
        which already incorporates keyword/ad/landing page relevance and page speed.
        """
        qs_data = self.metrics.get("quality_scores", {})
        dist = qs_data.get("post_click_distribution", {})

        total = sum(dist.values())
        if total == 0:
            return 50.0

        # Weight each bucket
        score = (
            dist.get("ABOVE_AVERAGE", 0) * 100 +
            dist.get("AVERAGE", 0) * 65 +
            dist.get("BELOW_AVERAGE", 0) * 20 +
            dist.get("UNKNOWN", 0) * 50
        ) / total

        return round(score, 1)

    def _score_mobile_advertising(self) -> float:
        """
        Score based on:
          - Whether device bid adjustments are actually set (not hardcoded assumed)
          - Whether the adjustment direction aligns with relative mobile performance
          - Mobile traffic share (home service users skew 55-70% mobile)
        """
        device_performance = self.metrics.get("device_performance", {})
        bid_adj = self.metrics.get("device_bid_adjustments", {})

        mobile = device_performance.get("mobile", {})
        desktop = device_performance.get("desktop", {})

        mobile_ctr = mobile.get("ctr", 0)
        desktop_ctr = desktop.get("ctr", 0)
        mobile_clicks = mobile.get("clicks", 0)
        desktop_clicks = desktop.get("clicks", 0)
        total_clicks = mobile_clicks + desktop_clicks

        score = 35.0  # Base

        # Mobile traffic share — home service searches are majority mobile
        if total_clicks > 0:
            mobile_share = mobile_clicks / total_clicks
            if mobile_share >= 0.45:
                score += 20
            elif mobile_share >= 0.25:
                score += 12
            elif mobile_share > 0:
                score += 5

        # Bid adjustments exist (shows device-level awareness)
        has_adj = bid_adj.get("has_adjustments", False)
        mobile_modifier = bid_adj.get("mobile", 1.0)

        if has_adj:
            score += 25
            # Bonus: modifier direction matches CTR performance
            if mobile_ctr > 0 and desktop_ctr > 0:
                if mobile_ctr >= desktop_ctr * 0.9 and mobile_modifier >= 1.0:
                    score += 20  # Mobile performs well AND bid is up
                elif mobile_ctr < desktop_ctr * 0.8 and mobile_modifier < 1.0:
                    score += 20  # Mobile underperforms AND bid is appropriately lower
                else:
                    score += 8   # Adjustments set but direction is inconsistent
        else:
            # No bid adjustments — minor bonus if performance is close enough
            if mobile_ctr > 0 and desktop_ctr > 0:
                ctr_ratio = mobile_ctr / desktop_ctr
                if 0.85 <= ctr_ratio <= 1.15:
                    score += 10  # Close enough that missing adjustment is low urgency

        return min(100.0, score)

    def _calculate_overall_score(self) -> float:
        """
        Calculate weighted average of all section scores.
        Applies additional penalty for high wasted spend since that's a critical issue.
        """
        weights = {
            "wasted_spend": 0.25,        # Search term waste + non-converting keywords
            "quality_score": 0.15,       # Overall QS avg
            "landing_pages": 0.10,       # Landing page experience via QS post_click_quality_score
            "ctr_optimization": 0.12,    # CTR by device
            "text_ad_optimization": 0.10, # RSA ad strength + CTR
            "account_activity": 0.10,    # Ads/group, KW tightness, extensions, conversion tracking
            "long_tail_keywords": 0.08,  # Long-tail keyword coverage
            "impression_share": 0.05,    # Rank-lost share only
            "mobile_advertising": 0.05,  # Bid adjustments + mobile traffic share
            "expanded_text_ads": 0.00,   # Informational only — ETAs sunset by Google Jun 2022
        }

        weighted_sum = sum(
            self.scores.get(section, 0) * weight
            for section, weight in weights.items()
        )

        # Apply penalty for high wasted spend (waste > 10%)
        # Derive actual waste % from score: score = 100 - 2.5 * waste_pct → waste_pct = (100 - score) / 2.5
        waste_percentage = (100 - self.scores.get("wasted_spend", 100)) / 2.5
        if waste_percentage > 10:
            # Harsh penalty: -2 points for each % over 10%
            # Example: 19% waste = (19-10) * 2 = -18 points
            waste_penalty = (waste_percentage - 10) * 2.0
            weighted_sum = max(0, weighted_sum - waste_penalty)

        return round(weighted_sum, 1)

    def _calculate_grade(self, score: float) -> str:
        """Convert numerical score to letter grade."""
        if score >= 90: return "A+"
        elif score >= 85: return "A"
        elif score >= 80: return "A-"
        elif score >= 75: return "B+"
        elif score >= 70: return "B"
        elif score >= 65: return "B-"
        elif score >= 60: return "C+"
        elif score >= 55: return "C"
        elif score >= 50: return "C-"
        elif score >= 45: return "D+"
        elif score >= 40: return "D"
        else: return "F"

    def _calculate_wasted_spend_dollars(self, waste_percentage: float) -> Tuple[float, float]:
        """
        Calculate estimated wasted spend in dollars based on waste percentage.

        The waste percentage comes from the efficiency score:
        - 81% efficiency (negative keyword coverage) = 19% waste
        - 19% of spend is being wasted on irrelevant searches

        Args:
            waste_percentage: Waste percentage (0-100)

        Returns:
            Tuple of (90-day wasted spend, 12-month projected waste)
        """
        performance = self.metrics.get("performance", {})
        # Note: performance.cost is for the full data range (typically 365 days)
        total_cost = performance.get("cost", 0)

        # Convert waste percentage to decimal (19% -> 0.19)
        waste_decimal = waste_percentage / 100.0

        # Apply waste percentage to total cost
        # For 12-month projection, we use the full year's cost
        projected_waste_12m = total_cost * waste_decimal

        # For 90-day estimate, calculate proportionally
        wasted_spend_90d = projected_waste_12m / 4  # 90 days ≈ 1/4 of year

        return round(wasted_spend_90d, 2), round(projected_waste_12m, 2)

    def _get_account_diagnostics(self) -> Dict[str, Any]:
        """
        Compile key account statistics for display.
        """
        structure = self.metrics.get("campaigns", {})
        keywords = self.metrics.get("keywords", {})
        ads = self.metrics.get("ads", {})
        performance = self.metrics.get("performance", {})

        return {
            "active_campaigns": structure.get("campaign_count", 0),
            "active_ad_groups": structure.get("ad_group_count", 0),
            "active_keywords": keywords.get("total_keywords", 0),
            "active_text_ads": ads.get("total_ads", 0),
            "clicks_90d": performance.get("clicks", 0),
            "conversions_90d": int(performance.get("conversions", 0)),
            "avg_cpa_90d": round(performance.get("avg_cpa", 0), 2),
            "avg_monthly_spend": round(performance.get("cost", 0) / 12, 2),  # 365 days / 12 months
        }

    def _prepare_chart_data(self) -> Dict[str, Any]:
        """
        Prepare data formatted for charts in the report template.
        Returns chart-ready data for quality score distribution, CTR by device, and keyword length.
        """
        chart_data = {}

        # Quality Score Distribution Chart
        qs_data = self.metrics.get("quality_scores", {})
        if qs_data:
            # Try to get distribution from metrics, or create a simple one
            qs_distribution = qs_data.get("distribution", {})
            if not qs_distribution:
                # If no distribution, estimate based on average
                avg_qs = qs_data.get("average", 5.0)
                if avg_qs < 4:
                    qs_distribution = {"1-3": 60, "4-6": 30, "7-8": 8, "9-10": 2}
                elif avg_qs < 6:
                    qs_distribution = {"1-3": 20, "4-6": 50, "7-8": 25, "9-10": 5}
                elif avg_qs < 8:
                    qs_distribution = {"1-3": 10, "4-6": 30, "7-8": 45, "9-10": 15}
                else:
                    qs_distribution = {"1-3": 5, "4-6": 15, "7-8": 40, "9-10": 40}
            chart_data["quality_score_distribution"] = qs_distribution

        # CTR by Device Chart
        device_performance = self.metrics.get("device_performance", {})
        if device_performance:
            ctr_by_device = {}
            for device, data in device_performance.items():
                ctr_by_device[device] = data.get("ctr", 0)
            chart_data["ctr_by_device"] = ctr_by_device

        # Keyword Length Distribution Chart
        keywords = self.metrics.get("keywords", {})
        keyword_distribution = keywords.get("word_count_distribution", {})
        if keyword_distribution:
            chart_data["keywords"] = {"word_count_distribution": keyword_distribution}

        return chart_data

    def _check_best_practices(self) -> Dict[str, bool]:
        """
        Check if account follows Google Ads best practices.
        """
        ads = self.metrics.get("ads", {})
        keywords = self.metrics.get("keywords", {})
        structure = self.metrics.get("campaigns", {})
        extensions = self.metrics.get("extensions", {})

        ad_count = ads.get("total_ads", 0)
        ad_group_count = structure.get("ad_group_count", 0)
        avg_ads_per_group = (ad_count / ad_group_count) if ad_group_count > 0 else 0

        keyword_list = keywords.get("keywords", [])
        has_broad_match = any(kw.get("match_type") == "BROAD" for kw in keyword_list)

        bid_adj = self.metrics.get("device_bid_adjustments", {})
        return {
            "multiple_ads_per_group": avg_ads_per_group >= 2,
            "modified_broad_match": has_broad_match,
            "ad_extensions": any(extensions.values()),
            "conversion_tracking": self.metrics.get("performance", {}).get("conversions", 0) > 0,
            "negative_keywords": self.metrics.get("negative_keywords", 0) > 0,
            "mobile_bid_adjustments": bid_adj.get("has_adjustments", False),
            "legacy_eta_ads": bool(
                self.metrics.get("ads", {})
                .get("ad_type_counts", {})
                .get("EXPANDED_TEXT_AD", 0)
            ),
        }

    def _generate_recommendations(self) -> None:
        """
        Generate actionable recommendations with ROI estimates based on analysis.
        """
        recommendations = []

        # Get performance data for ROI calculations
        performance = self.metrics.get("performance", {})
        current_spend = performance.get("cost", 0)  # 90 days
        current_conversions = performance.get("conversions", 0)

        # Determine severity based on score (lower score = higher severity)
        def get_severity(score: float) -> int:
            if score < 40:
                return 1  # Critical
            elif score < 60:
                return 2  # High impact
            elif score < 75:
                return 3  # Medium
            else:
                return 4  # Low

        # Wasted spend recommendations
        if self.scores["wasted_spend"] < 70:
            search_terms_data = self.metrics.get("search_terms", {})
            waste_terms = search_terms_data.get("waste_terms", [])
            waste_term_count = search_terms_data.get("waste_term_count", 0)
            top_waste = sorted(waste_terms, key=lambda x: x.get("cost", 0), reverse=True)[:3]

            severity = get_severity(self.scores["wasted_spend"])
            roi = ROICalculator.calculate_spend_savings(
                current_spend,
                'negative_keywords',
                timeframe_days=90,
                severity=severity
            )
            effort = ROICalculator.estimate_implementation_effort('negative_keywords', severity)

            if waste_term_count > 0:
                title = f"Block {waste_term_count} Irrelevant Search Terms Draining Your Budget"
                description = (
                    f"We found {waste_term_count} search terms with DIY, job-seeking, or "
                    f"informational intent that are costing you money with no intent to hire."
                )
                examples = ", ".join(f'"{t["term"]}"' for t in top_waste) if top_waste else ""
                layman_summary = (
                    f"People are finding your ad by searching things like {examples} — "
                    f"they're not looking to hire you. Adding these as negative keywords stops "
                    f"your ad from showing for these searches, saving real money immediately."
                )
                action_steps = [
                    "1. Go to Keywords → Search Terms in Google Ads",
                    f"2. Find and select the {waste_term_count} irrelevant queries we identified",
                    "3. Click 'Add as negative keyword' at the campaign or account level",
                    "4. Review the Search Terms report weekly to catch new waste"
                ]
            else:
                negative_keywords = self.metrics.get("negative_keywords", 0)
                gap = max(0, BENCHMARKS["negative_keywords_avg"] - negative_keywords)
                title = f"Add Negative Keywords to Prevent Ad Spend Waste"
                description = "Your negative keyword list is thin. Gaps allow irrelevant searches to trigger your ads and consume budget."
                layman_summary = (
                    "Negative keywords are a block list — they stop your ad from showing when "
                    "someone searches for something you don't do (like DIY tutorials, job listings, "
                    "or unrelated services). More negatives = less wasted money."
                )
                action_steps = [
                    "1. Open your Google Ads Search Terms report",
                    "2. Look for searches with 'how to', 'diy', 'jobs', or unrelated services",
                    f"3. Add {min(gap, 50)} negative keywords this week",
                    "4. Repeat weekly — it's an ongoing process"
                ]

            recommendations.append({
                'title': title,
                'description': description,
                'layman_summary': layman_summary,
                'category': 'wasted_spend',
                'severity': severity,
                'roi': {
                    'monthly_savings': roi['monthly_savings'],
                    'annual_savings': roi['annual_savings'],
                    'percentage': roi['percentage_reduction']
                },
                'effort': effort,
                'action_steps': action_steps,
                'summary': f"💰 Save ${roi['monthly_savings']:,.0f}/month • {effort['time_estimate']} • {effort['difficulty']}"
            })

        # Quality Score recommendations
        if self.scores["quality_score"] < 70:
            qs_avg = self.metrics.get("quality_scores", {}).get("average", 0)
            target = BENCHMARKS["quality_score_target"]

            severity = get_severity(self.scores["quality_score"])
            qs_roi = ROICalculator.calculate_quality_score_impact(
                qs_avg, target, current_spend, timeframe_days=90
            )
            effort = ROICalculator.estimate_implementation_effort('quality_score', severity)

            recommendations.append({
                'title': f"Improve Ad Quality from {qs_avg:.1f} to {target}+ Stars",
                'description': f"Your ads score {qs_avg:.1f} out of 10. Better ads cost less money! Google charges you less when your ads are high quality.",
                'layman_summary': f"Google grades your ads like a report card (1-10 stars). Higher grades = you pay LESS per click. It's like getting a discount for writing better ads. Right now you're at {qs_avg:.1f}/10, so there's money being left on the table.",
                'category': 'quality_score',
                'severity': severity,
                'roi': {
                    'monthly_savings': qs_roi['monthly_savings'],
                    'annual_savings': qs_roi['annual_savings'],
                    'percentage': qs_roi['cpc_reduction_percent']
                },
                'effort': effort,
                'action_steps': [
                    "1. Find your low-quality ads (score below 6)",
                    "2. Rewrite them to match what people are searching for",
                    "3. Use the exact keywords from your ad group in your ad text",
                    "4. Add a clear call-to-action like 'Call Now' or 'Get Quote'"
                ],
                'summary': f"💰 Save ${qs_roi['monthly_savings']:,.0f}/month • {effort['time_estimate']} • {effort['difficulty']}"
            })

        # CTR recommendations
        if self.scores["ctr_optimization"] < 60:
            severity = get_severity(self.scores["ctr_optimization"])
            roi = ROICalculator.calculate_combined_roi(
                current_spend,
                current_conversions,
                None,  # No customer value yet
                'ctr',
                timeframe_days=90,
                severity=severity
            )
            effort = ROICalculator.estimate_implementation_effort('ctr', severity)

            leads_info = roi['leads']
            recommendations.append({
                'title': "Get More Clicks by Testing New Ad Variations",
                'description': f"Not enough people are clicking your ads. Test new ad copy to get {leads_info['monthly_new_leads']:.0f} more leads per month.",
                'layman_summary': "CTR (Click-Through Rate) is how often people click your ad when they see it. Low CTR means your ads aren't interesting enough. Better headlines and descriptions = more clicks = more customers calling you.",
                'category': 'ctr',
                'severity': severity,
                'roi': {
                    'monthly_leads': leads_info['monthly_new_leads'],
                    'annual_leads': leads_info['annual_new_leads'],
                    'percentage': leads_info['percentage_increase']
                },
                'effort': effort,
                'action_steps': [
                    "1. Pick your 3 top-performing ad groups",
                    "2. Write 2-3 new ads for each group",
                    "3. Try different headlines: use questions, numbers, or urgency",
                    "4. Let them run for 2 weeks, then keep the winners"
                ],
                'summary': f"📈 +{leads_info['monthly_new_leads']:.0f} leads/month • {effort['time_estimate']} • {effort['difficulty']}"
            })

        # Long-tail keyword recommendations
        if self.scores["long_tail_keywords"] < 50:
            severity = get_severity(self.scores["long_tail_keywords"])
            roi = ROICalculator.calculate_combined_roi(
                current_spend,
                current_conversions,
                None,
                'long_tail',
                timeframe_days=90,
                severity=severity
            )
            effort = ROICalculator.estimate_implementation_effort('keywords', severity)

            recommendations.append({
                'title': "Add More Specific Keyword Phrases (3+ Words)",
                'description': "Long phrases like 'emergency plumber dallas 75201' cost less and convert better than short keywords like 'plumber'.",
                'layman_summary': "Longer, more specific keyword phrases (called 'long-tail keywords') attract customers who know exactly what they want. They cost less per click AND convert better because these people are ready to buy. It's like fishing with a spear instead of a net.",
                'category': 'long_tail_keywords',
                'severity': severity,
                'roi': {
                    'monthly_savings': roi['savings']['monthly_savings'],
                    'monthly_leads': roi['leads']['monthly_new_leads'],
                    'total_value': roi['total_monthly_value']
                },
                'effort': effort,
                'action_steps': [
                    "1. Think about specific services you offer",
                    "2. Add your city/neighborhood to each keyword",
                    "3. Include urgency words like 'emergency' or 'same day'",
                    "4. Add 20-30 new long-tail keywords this week"
                ],
                'summary': f"💰 ${roi['total_monthly_value']:,.0f}/month value • {effort['time_estimate']} • {effort['difficulty']}"
            })

        # Mobile recommendations
        if self.scores["mobile_advertising"] < 60:
            device_performance = self.metrics.get("device_performance", {})
            mobile = device_performance.get("mobile", {})
            desktop = device_performance.get("desktop", {})

            severity = get_severity(self.scores["mobile_advertising"])
            roi = ROICalculator.calculate_combined_roi(
                current_spend,
                current_conversions,
                None,
                'mobile',
                timeframe_days=90,
                severity=severity
            )
            effort = ROICalculator.estimate_implementation_effort('mobile', severity)

            if mobile.get("ctr", 0) > desktop.get("ctr", 0):
                title = "Increase Mobile Bids to Get More Phone Calls"
                description = "Your mobile ads are performing well! Increase bids by 15-20% to get more mobile traffic."
                steps = [
                    "1. Go to your campaign settings",
                    "2. Click 'Devices'",
                    "3. Increase mobile bid adjustment to +20%",
                    "4. Watch for more calls and form fills"
                ]
            else:
                title = "Fix Your Mobile Ads to Get More Phone Calls"
                description = "People on phones aren't clicking your ads as much. Make your mobile ads shorter and add click-to-call buttons."
                steps = [
                    "1. Shorten your mobile ad headlines (under 30 characters)",
                    "2. Add 'Call Now' in your description",
                    "3. Enable call extensions (click-to-call)",
                    "4. Make sure your mobile landing page loads fast"
                ]

            # Add layman summary based on scenario
            if mobile.get("ctr", 0) > desktop.get("ctr", 0):
                layman_summary = "Most people search on their phones now. Your mobile ads are working well, so increasing your mobile bids means you'll show up more often when people are ready to call. More visibility = more phone calls."
            else:
                layman_summary = "Mobile users are different - they want to call NOW, not fill out forms. Your mobile ads need to be optimized for quick calls with click-to-call buttons and fast-loading pages. Think 'tap to call' not 'browse and think about it'."

            recommendations.append({
                'title': title,
                'description': description,
                'layman_summary': layman_summary,
                'category': 'mobile',
                'severity': severity,
                'roi': {
                    'monthly_leads': roi['leads']['monthly_new_leads'],
                    'annual_leads': roi['leads']['annual_new_leads'],
                    'percentage': roi['leads']['percentage_increase']
                },
                'effort': effort,
                'action_steps': steps,
                'summary': f"📱 +{roi['leads']['monthly_new_leads']:.0f} leads/month • {effort['time_estimate']} • {effort['difficulty']}"
            })

        # Landing page experience recommendations (based on QS post_click_quality_score)
        if self.scores["landing_pages"] < 70:
            qs_data = self.metrics.get("quality_scores", {})
            post_click_dist = qs_data.get("post_click_distribution", {})
            below_avg = post_click_dist.get("BELOW_AVERAGE", 0)
            total_kw = sum(post_click_dist.values()) or 1
            below_avg_pct = round(below_avg / total_kw * 100)

            severity = get_severity(self.scores["landing_pages"])
            roi = ROICalculator.calculate_combined_roi(
                current_spend,
                current_conversions,
                None,
                'landing_pages',
                timeframe_days=90,
                severity=severity
            )
            effort = ROICalculator.estimate_implementation_effort('landing_pages', severity)

            if below_avg_pct > 20:
                title = f"Fix Landing Pages — Google Rates {below_avg_pct}% as Below Average"
                description = (
                    f"Google's own Landing Page Experience score shows {below_avg_pct}% of your keywords "
                    f"point to pages that don't match what people searched for."
                )
            else:
                title = "Improve Landing Page Relevance to Lower Your Cost Per Lead"
                description = "Your landing page experience score has room to improve. Better-matched pages reduce your cost-per-click and improve conversions."

            recommendations.append({
                'title': title,
                'description': description,
                'layman_summary': (
                    "Google scores how relevant your landing page is to each keyword (1 of 3 factors in Quality Score). "
                    "A 'Below Average' rating means your page content doesn't closely match the ad and keyword. "
                    "Fixing this lowers your cost per click AND gets you more conversions — double benefit."
                ),
                'category': 'landing_pages',
                'severity': severity,
                'roi': {
                    'monthly_leads': roi['leads']['monthly_new_leads'],
                    'annual_leads': roi['leads']['annual_new_leads'],
                    'percentage': roi['leads']['percentage_increase']
                },
                'effort': effort,
                'action_steps': [
                    "1. In Google Ads, open Keywords and add the 'Landing page exp.' column",
                    "2. Find keywords marked 'Below average'",
                    "3. Check: does the page headline match what the keyword promises?",
                    "4. Match page headline, H1, and copy to the specific service in the ad"
                ],
                'summary': f"📈 +{roi['leads']['monthly_new_leads']:.0f} leads/month • {effort['time_estimate']} • {effort['difficulty']}"
            })

        # Impression share — only recommend when rank-lost is significant (quality/bid problem)
        if self.scores["impression_share"] < 60:
            imp_share_data = self.metrics.get("impression_share", {})
            rank_lost = imp_share_data.get("rank_lost_share", 0)
            budget_lost = imp_share_data.get("budget_lost_share", 0)
            rank_lost_pct = round(rank_lost * 100)

            severity = get_severity(self.scores["impression_share"])
            roi = ROICalculator.calculate_combined_roi(
                current_spend,
                current_conversions,
                None,
                'impression_share',
                timeframe_days=90,
                severity=severity
            )
            effort = ROICalculator.estimate_implementation_effort('impression_share', severity)

            recommendations.append({
                'title': f"Win More Auctions — You're Losing {rank_lost_pct}% of Searches to Competitors",
                'description': (
                    f"Your ads aren't showing for {rank_lost_pct}% of eligible searches because "
                    f"competitors have higher Quality Scores or bids. This is a fixable problem."
                ),
                'layman_summary': (
                    "Every time someone in your area searches for your service, Google runs an instant auction. "
                    f"You're losing {rank_lost_pct}% of those auctions — not because of budget, but because of ad quality or bid. "
                    "Improving Quality Score is the best lever: it lowers what you pay AND wins more auctions."
                ),
                'category': 'impression_share',
                'severity': severity,
                'roi': {
                    'monthly_leads': roi['leads']['monthly_new_leads'],
                    'annual_leads': roi['leads']['annual_new_leads'],
                    'percentage': roi['leads']['percentage_increase']
                },
                'effort': effort,
                'action_steps': [
                    "1. Focus first on improving Quality Score (see that recommendation)",
                    "2. Check Auction Insights to see which competitors are beating you",
                    "3. Increase bids on your top 5 highest-converting keywords by 10-15%",
                    "4. Review Ad Rank after 2 weeks — rank-lost share should decrease"
                ],
                'summary': f"📈 +{roi['leads']['monthly_new_leads']:.0f} leads/month • {effort['time_estimate']} • {effort['difficulty']}"
            })

        # Ad extension recommendations
        extensions = self.metrics.get("extensions", {})
        if not any(extensions.values()):
            recommendations.append({
                'title': "Add Ad Extensions to Make Your Ads Bigger",
                'description': "Ad extensions make your ads take up more space and give people more ways to contact you. They're free and boost clicks by 10-15%.",
                'layman_summary': "Extensions are FREE add-ons that make your ad physically bigger on the page and add extra info like your phone number, address, or links to specific services. Bigger ads = more clicks. It's like upgrading from a business card to a brochure at no extra cost.",
                'category': 'extensions',
                'severity': 3,  # Medium priority
                'roi': {
                    'monthly_leads': current_conversions / 3 * 0.12,  # 12% boost estimate
                    'percentage': 12
                },
                'effort': {
                    'time_estimate': '20-30 min',
                    'difficulty': 'Easy',
                    'priority': 'Medium'
                },
                'action_steps': [
                    "1. Add Sitelink Extensions (links to your services)",
                    "2. Add Call Extension (your phone number)",
                    "3. Add Callout Extensions ('24/7 Service', 'Licensed & Insured')",
                    "4. Add Location Extension (your address)"
                ],
                'summary': "📞 More clicks & calls • 20-30 min • Easy"
            })

        # Account structure recommendations
        if self.scores["account_activity"] < 60:
            recommendations.append({
                'title': "Reorganize Your Account Structure",
                'description': "Your campaigns and ad groups are messy. Better organization makes it easier to optimize and track performance.",
                'layman_summary': "Think of your Google Ads account like a filing cabinet. Right now everything's jumbled together. Organizing by service type (plumbing, HVAC, electrical) makes it WAY easier to see what's working, what's not, and make changes quickly. Better organization = better results over time.",
                'category': 'account_structure',
                'severity': 4,  # Lower priority
                'roi': {
                    'efficiency_gain': 15,
                    'description': "15% easier to manage"
                },
                'effort': {
                    'time_estimate': '2-3 hours',
                    'difficulty': 'Medium',
                    'priority': 'Low'
                },
                'action_steps': [
                    "1. Group similar services into separate campaigns",
                    "2. Create tight ad groups with 5-15 related keywords",
                    "3. Write specific ads for each ad group",
                    "4. Use clear naming conventions"
                ],
                'summary': "🗂️ Better organization • 2-3 hours • Medium difficulty"
            })

        # Sort by severity and limit to top 10
        recommendations.sort(key=lambda x: x.get('severity', 5))
        self.recommendations = recommendations[:10]
