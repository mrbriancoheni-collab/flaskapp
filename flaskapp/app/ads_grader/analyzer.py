"""
Google Ads Grader Analyzer

Scoring algorithms and recommendations engine for the Google Ads Quality Checker.
"""
import logging
from typing import Dict, List, Any, Tuple
from datetime import datetime
from app.services.roi_calculator import ROICalculator

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

        # Calculate waste percentage (inverse of efficiency score)
        # If efficiency is 81%, waste is 19%
        waste_percentage = 100 - self.scores["wasted_spend"]

        # Calculate wasted spend in dollars using the waste percentage
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
            },
            "account_diagnostics": self._get_account_diagnostics(),
            "best_practices": self._check_best_practices(),
            "chart_data": self._prepare_chart_data(),
        }

    def _score_wasted_spend(self) -> float:
        """
        Score based on negative keywords usage.
        More negative keywords = less wasted spend = higher score.

        NOTE: This returns an EFFICIENCY score (higher = better).
        The waste percentage is calculated separately in _calculate_wasted_spend().
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
        Applies additional penalty for high wasted spend since that's a critical issue.
        """
        weights = {
            "wasted_spend": 0.25,  # Increased from 15% - wasted spend is critical
            "quality_score": 0.15,
            "ctr_optimization": 0.12,
            "text_ad_optimization": 0.10,
            "account_activity": 0.08,
            "long_tail_keywords": 0.08,
            "impression_share": 0.08,
            "landing_pages": 0.07,
            "mobile_advertising": 0.05,
            "expanded_text_ads": 0.02,
        }

        weighted_sum = sum(
            self.scores.get(section, 0) * weight
            for section, weight in weights.items()
        )

        # Apply penalty for high wasted spend (waste > 10%)
        # Wasting money is a critical issue that should heavily impact overall score
        waste_percentage = 100 - self.scores.get("wasted_spend", 100)
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
            negative_keywords = self.metrics.get("negative_keywords", 0)
            benchmark = BENCHMARKS["negative_keywords_avg"]
            gap = max(0, benchmark - negative_keywords)

            severity = get_severity(self.scores["wasted_spend"])
            roi = ROICalculator.calculate_spend_savings(
                current_spend,
                'negative_keywords',
                timeframe_days=90,
                severity=severity
            )
            effort = ROICalculator.estimate_implementation_effort('negative_keywords', severity)

            recommendations.append({
                'title': f"Add {gap} Negative Keywords to Stop Wasting Money",
                'description': f"You're spending money on wrong searches. Adding negative keywords will block irrelevant clicks and save you money every month.",
                'layman_summary': f"Think of negative keywords as a 'block list' for your ads. When someone searches for something you DON'T do, negative keywords prevent your ad from showing up. This stops you from paying for clicks that never turn into customers.",
                'category': 'wasted_spend',
                'severity': severity,
                'roi': {
                    'monthly_savings': roi['monthly_savings'],
                    'annual_savings': roi['annual_savings'],
                    'percentage': roi['percentage_reduction']
                },
                'effort': effort,
                'action_steps': [
                    "1. Open your Google Ads Search Terms report",
                    "2. Find searches that aren't relevant to your business",
                    f"3. Add {min(gap, 50)} negative keywords this week",
                    "4. Check back next week to add more"
                ],
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

        # Landing page recommendations
        if self.scores["landing_pages"] < 70:
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

            recommendations.append({
                'title': "Create Better Landing Pages to Convert More Visitors",
                'description': f"Your landing pages aren't converting well. Better pages could get you {roi['leads']['monthly_new_leads']:.0f} more customers per month.",
                'layman_summary': "A landing page is where people go after clicking your ad. Think of it as your digital storefront. If it's confusing or slow, people leave without calling. A good landing page makes it dead simple to contact you - big phone number, clear offer, trust signals (reviews), and fast loading.",
                'category': 'landing_pages',
                'severity': severity,
                'roi': {
                    'monthly_leads': roi['leads']['monthly_new_leads'],
                    'annual_leads': roi['leads']['annual_new_leads'],
                    'percentage': roi['leads']['percentage_increase']
                },
                'effort': effort,
                'action_steps': [
                    "1. Create one landing page per main service",
                    "2. Match your page headline to your ad headline",
                    "3. Add a big phone number and contact form at the top",
                    "4. Include customer reviews and photos of your work"
                ],
                'summary': f"📈 +{roi['leads']['monthly_new_leads']:.0f} leads/month • {effort['time_estimate']} • {effort['difficulty']}"
            })

        # Impression share recommendations
        if self.scores["impression_share"] < 60:
            imp_share_data = self.metrics.get("impression_share", {})
            budget_lost = imp_share_data.get("budget_lost_share", 0)
            rank_lost = imp_share_data.get("rank_lost_share", 0)

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

            if budget_lost > rank_lost:
                title = "Increase Your Daily Budget to Show Ads More Often"
                description = "Your ads stop showing because you run out of money each day. Increase budget to capture more customers."
                steps = [
                    "1. Check what time your budget runs out each day",
                    "2. Increase daily budget by $20-50",
                    "3. Monitor performance for 1 week",
                    "4. Adjust based on results"
                ]
            else:
                title = "Improve Your Ad Quality to Show Up More Often"
                description = "Your competitors' ads show up instead of yours. Improve quality and bids to win more auctions."
                steps = [
                    "1. Improve Quality Score (see recommendation above)",
                    "2. Review your bids vs. competitors",
                    "3. Increase bids by 10-15% on top keywords",
                    "4. Watch your impression share improve"
                ]

            # Add layman summary based on scenario
            if budget_lost > rank_lost:
                layman_summary = "Impression share is how often your ads show up when people search. Low impression share means you're missing out on potential customers. If you're running out of budget, you're literally turning away customers because your ads stop showing mid-day."
            else:
                layman_summary = "Your ads aren't showing up enough because competitors are outbidding you or have better Quality Scores. Think of it like a crowded marketplace - you need to speak louder (higher bids) or be more interesting (better quality) to get attention."

            recommendations.append({
                'title': title,
                'description': description,
                'layman_summary': layman_summary,
                'category': 'impression_share',
                'severity': severity,
                'roi': {
                    'monthly_leads': roi['leads']['monthly_new_leads'],
                    'annual_leads': roi['leads']['annual_new_leads'],
                    'percentage': roi['leads']['percentage_increase']
                },
                'effort': effort,
                'action_steps': steps,
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
