"""
Google Ads Grader Analyzer

Scoring algorithms and recommendations engine for the Google Ads Quality Checker.
"""
import logging
from typing import Dict, List, Any, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)


# Industry benchmarks (based on WordStream data)
BENCHMARKS = {
    "quality_score_target": 7.0,
    "negative_keywords_avg": 135,
    "landing_pages_avg": 15,
    "ctr_by_position": {
        1: 7.94,
        2: 4.95,
        3: 3.51,
        4: 2.57,
        5: 2.04,
    },
    "long_tail_target": 0.50,  # 50%+ should be 3+ words
    "impression_share_target": 0.70,  # 70%+
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
        wasted_spend_90d, projected_waste_12m = self._calculate_wasted_spend()

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
            },
            "account_diagnostics": self._get_account_diagnostics(),
            "best_practices": self._check_best_practices(),
        }

    def _score_wasted_spend(self) -> float:
        """
        Score based on negative keywords usage.
        More negative keywords = less wasted spend = higher score.
        """
        negative_keywords = self.metrics.get("negative_keywords", 0)
        benchmark = BENCHMARKS["negative_keywords_avg"]

        # Score: 100% if at or above benchmark, scale down if below
        if negative_keywords >= benchmark:
            score = 100.0
        else:
            score = (negative_keywords / benchmark) * 100

        return min(100, max(0, score))

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
        Score based on ad performance variance and CTR.
        """
        ads = self.metrics.get("ads", {})
        avg_ctr = ads.get("avg_ctr", 0)
        best_ad = ads.get("best_ad", {})
        worst_ad = ads.get("worst_ad", {})

        if not best_ad or not worst_ad:
            return 50.0

        # Check CTR variance
        best_ctr = best_ad.get("ctr", 0)
        worst_ctr = worst_ad.get("ctr", 0)

        # Lower variance = more consistent optimization = higher score
        if best_ctr > 0:
            variance = (best_ctr - worst_ctr) / best_ctr
            consistency_score = (1 - variance) * 50
        else:
            consistency_score = 25

        # CTR performance score (assume 3% is good)
        ctr_score = min(50, (avg_ctr / 3.0) * 50)

        return min(100, consistency_score + ctr_score)

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
        Score based on account structure and activity.
        Active management = higher score.
        """
        structure = self.metrics.get("campaigns", {})
        campaign_count = structure.get("campaign_count", 0)
        ad_group_count = structure.get("ad_group_count", 0)

        keywords = self.metrics.get("keywords", {})
        keyword_count = keywords.get("total_keywords", 0)

        ads = self.metrics.get("ads", {})
        ad_count = ads.get("total_ads", 0)

        # Score based on reasonable structure
        score = 0

        # Campaigns (3-10 is ideal)
        if 3 <= campaign_count <= 10:
            score += 25
        elif campaign_count > 0:
            score += 15

        # Ad groups (10-50 is ideal)
        if 10 <= ad_group_count <= 50:
            score += 25
        elif ad_group_count > 0:
            score += 15

        # Keywords (100-1000 is ideal)
        if 100 <= keyword_count <= 1000:
            score += 25
        elif keyword_count > 0:
            score += 15

        # Ads (2+ per ad group is ideal)
        avg_ads_per_group = (ad_count / ad_group_count) if ad_group_count > 0 else 0
        if avg_ads_per_group >= 2:
            score += 25
        elif avg_ads_per_group >= 1:
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
        Score based on search impression share.
        Higher impression share = better visibility = higher score.
        """
        imp_share_data = self.metrics.get("impression_share", {})
        impression_share = imp_share_data.get("impression_share", 0)

        target = BENCHMARKS["impression_share_target"]

        # Score scales with impression share
        score = (impression_share / target) * 100

        return min(100, max(0, score))

    def _score_landing_pages(self) -> float:
        """
        Score based on number of unique landing pages.
        More landing pages = better targeting = higher score.
        """
        landing_page_count = self.metrics.get("landing_pages", 0)
        benchmark = BENCHMARKS["landing_pages_avg"]

        if landing_page_count >= benchmark:
            score = 100.0
        else:
            score = (landing_page_count / benchmark) * 100

        return min(100, max(0, score))

    def _score_mobile_advertising(self) -> float:
        """
        Score based on mobile performance and optimization.
        """
        device_performance = self.metrics.get("device_performance", {})
        mobile = device_performance.get("mobile", {})
        desktop = device_performance.get("desktop", {})

        score = 50.0  # Base score

        # Check if mobile has reasonable traffic
        mobile_clicks = mobile.get("clicks", 0)
        desktop_clicks = desktop.get("clicks", 0)
        total_clicks = mobile_clicks + desktop_clicks

        if total_clicks > 0:
            mobile_percentage = mobile_clicks / total_clicks

            # Mobile should be 30-70% of traffic
            if 0.3 <= mobile_percentage <= 0.7:
                score += 25
            elif mobile_percentage > 0:
                score += 10

        # Compare mobile vs desktop CTR
        mobile_ctr = mobile.get("ctr", 0)
        desktop_ctr = desktop.get("ctr", 0)

        if mobile_ctr > 0 and desktop_ctr > 0:
            # If mobile CTR is within 20% of desktop, add points
            ctr_ratio = mobile_ctr / desktop_ctr
            if 0.8 <= ctr_ratio <= 1.2:
                score += 25
            elif ctr_ratio > 0.5:
                score += 10

        return min(100, score)

    def _calculate_overall_score(self) -> float:
        """
        Calculate weighted average of all section scores.
        """
        weights = {
            "wasted_spend": 0.15,
            "quality_score": 0.15,
            "ctr_optimization": 0.12,
            "text_ad_optimization": 0.10,
            "account_activity": 0.10,
            "long_tail_keywords": 0.10,
            "impression_share": 0.10,
            "landing_pages": 0.08,
            "mobile_advertising": 0.07,
            "expanded_text_ads": 0.03,
        }

        weighted_sum = sum(
            self.scores.get(section, 0) * weight
            for section, weight in weights.items()
        )

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

    def _calculate_wasted_spend(self) -> Tuple[float, float]:
        """
        Calculate estimated wasted spend based on negative keyword deficiency.
        """
        performance = self.metrics.get("performance", {})
        total_cost_90d = performance.get("cost", 0)

        negative_keywords = self.metrics.get("negative_keywords", 0)
        benchmark = BENCHMARKS["negative_keywords_avg"]

        if negative_keywords >= benchmark:
            # Well optimized, minimal waste
            waste_percentage = 0.05  # 5%
        else:
            # Calculate waste based on how far below benchmark
            deficiency = 1 - (negative_keywords / benchmark)
            waste_percentage = 0.05 + (deficiency * 0.15)  # 5-20%

        wasted_spend_90d = total_cost_90d * waste_percentage
        projected_waste_12m = wasted_spend_90d * 4  # Extrapolate to 12 months

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

        return {
            "multiple_ads_per_group": avg_ads_per_group >= 2,
            "modified_broad_match": has_broad_match,
            "ad_extensions": any(extensions.values()),
            "conversion_tracking": self.metrics.get("performance", {}).get("conversions", 0) > 0,
            "negative_keywords": self.metrics.get("negative_keywords", 0) > 0,
            "mobile_bid_adjustments": True,  # Assume true for now, requires more complex check
        }

    def _generate_recommendations(self) -> None:
        """
        Generate actionable recommendations based on analysis.
        """
        recommendations = []

        # Wasted spend recommendations
        if self.scores["wasted_spend"] < 70:
            negative_keywords = self.metrics.get("negative_keywords", 0)
            benchmark = BENCHMARKS["negative_keywords_avg"]
            gap = benchmark - negative_keywords
            _, projected_waste = self._calculate_wasted_spend()
            recommendations.append(
                f"Add {gap} negative keywords to reduce wasted spend by ${projected_waste:.0f}/year"
            )

        # Quality Score recommendations
        if self.scores["quality_score"] < 70:
            qs_avg = self.metrics.get("quality_scores", {}).get("average", 0)
            target = BENCHMARKS["quality_score_target"]
            recommendations.append(
                f"Improve Quality Score from {qs_avg:.1f} to {target}+ to reduce CPC by up to 30%"
            )

        # CTR recommendations
        if self.scores["ctr_optimization"] < 60:
            recommendations.append(
                "Test 3-5 new ad variations in your top-performing ad groups to improve CTR"
            )

        # Long-tail keyword recommendations
        if self.scores["long_tail_keywords"] < 50:
            recommendations.append(
                "Add more long-tail (3+ word) keywords to capture high-intent, low-cost traffic"
            )

        # Mobile recommendations
        if self.scores["mobile_advertising"] < 60:
            device_performance = self.metrics.get("device_performance", {})
            mobile = device_performance.get("mobile", {})
            desktop = device_performance.get("desktop", {})

            if mobile.get("ctr", 0) > desktop.get("ctr", 0):
                recommendations.append(
                    "Increase mobile bids by 15-20% based on strong mobile performance"
                )
            else:
                recommendations.append(
                    "Optimize mobile ads and landing pages to improve mobile CTR"
                )

        # Landing page recommendations
        if self.scores["landing_pages"] < 70:
            recommendations.append(
                "Create more targeted landing pages to improve Quality Scores and conversion rates"
            )

        # Impression share recommendations
        if self.scores["impression_share"] < 60:
            imp_share_data = self.metrics.get("impression_share", {})
            budget_lost = imp_share_data.get("budget_lost_share", 0)
            rank_lost = imp_share_data.get("rank_lost_share", 0)

            if budget_lost > rank_lost:
                recommendations.append(
                    "Increase daily budgets to capture more impression share and potential clicks"
                )
            else:
                recommendations.append(
                    "Improve ad rank through better Quality Scores and competitive bids"
                )

        # Ad extension recommendations
        extensions = self.metrics.get("extensions", {})
        if not any(extensions.values()):
            recommendations.append(
                "Add sitelink and callout extensions to improve CTR and ad visibility"
            )

        # Account structure recommendations
        if self.scores["account_activity"] < 60:
            recommendations.append(
                "Reorganize account structure for better campaign and ad group segmentation"
            )

        self.recommendations = recommendations[:10]  # Limit to top 10 recommendations
