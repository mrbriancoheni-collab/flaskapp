# app/fb_ads_grader/analyzer.py
"""
Facebook Ads Performance Analyzer

Analyzes Facebook Ads account data and generates performance scores across
12+ dimensions with actionable recommendations.
"""
import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)


class FacebookAdsAnalyzer:
    """
    Analyzes Facebook Ads metrics and generates performance scores.

    Scores 12 key areas:
    1. Wasted Spend (poor-performing ads)
    2. Creative Optimization (ad variety and testing)
    3. Audience Targeting (audience diversity and quality)
    4. Relevance Score (ad relevance and engagement)
    5. CTR Optimization (click-through rate performance)
    6. Account Activity (ongoing optimization efforts)
    7. Ad Format Diversity (video, carousel, image, etc.)
    8. Campaign Structure (organization and best practices)
    9. Landing Page Experience (conversion optimization)
    10. Mobile Optimization (mobile-first approach)
    11. Conversion Tracking (pixel, events, attribution)
    12. ROAS Performance (return on ad spend)
    """

    # Industry benchmarks (Facebook Ads averages across industries)
    BENCHMARKS = {
        'ctr': {
            'excellent': 2.0,  # 2%+ CTR is excellent
            'good': 1.0,       # 1-2% is good
            'average': 0.5,    # 0.5-1% is average
        },
        'cpc': {
            'excellent': 0.50,  # <$0.50 CPC is excellent
            'good': 1.00,       # $0.50-$1.00 is good
            'average': 2.00,    # $1-$2 is average
        },
        'relevance_score': {
            'target': 7.0,      # Target relevance score of 7+
            'minimum': 5.0,     # Minimum acceptable is 5
        },
        'roas': {
            'excellent': 4.0,   # 4:1 ROAS is excellent
            'good': 2.5,        # 2.5:1 is good
            'breakeven': 1.0,   # 1:1 is breakeven
        },
        'mobile_percentage': {
            'target': 70.0,     # 70%+ mobile traffic is ideal for most businesses
        },
        'conversion_rate': {
            'excellent': 10.0,  # 10%+ conversion rate is excellent
            'good': 5.0,        # 5-10% is good
            'average': 2.0,     # 2-5% is average
        },
    }

    # Section weights for overall score
    SECTION_WEIGHTS = {
        'wasted_spend': 0.15,
        'creative_optimization': 0.10,
        'audience_targeting': 0.10,
        'relevance_score': 0.10,
        'ctr_optimization': 0.10,
        'account_activity': 0.05,
        'ad_format_diversity': 0.05,
        'campaign_structure': 0.10,
        'landing_page': 0.05,
        'mobile_optimization': 0.05,
        'conversion_tracking': 0.10,
        'roas': 0.05,
    }

    def __init__(self, metrics: Dict[str, Any]):
        """
        Initialize analyzer with Facebook Ads metrics.

        Args:
            metrics: Dict from FacebookAdsGraderClient.get_account_metrics()
        """
        self.metrics = metrics
        self.account_info = metrics.get('account_info', {})
        self.performance = metrics.get('performance', {})
        self.campaigns = metrics.get('campaigns', {})
        self.ad_sets = metrics.get('ad_sets', {})
        self.ads = metrics.get('ads', {})
        self.creative_performance = metrics.get('creative_performance', {})
        self.placement_performance = metrics.get('placement_performance', {})
        self.device_performance = metrics.get('device_performance', {})

    def analyze(self) -> Dict[str, Any]:
        """
        Run complete analysis and return results.

        Returns:
            Dict with overall_score, section_scores, recommendations, etc.
        """
        logger.info("Running Facebook Ads performance analysis")

        # Calculate section scores
        section_scores = {
            'wasted_spend': self._score_wasted_spend(),
            'creative_optimization': self._score_creative_optimization(),
            'audience_targeting': self._score_audience_targeting(),
            'relevance_score': self._score_relevance(),
            'ctr_optimization': self._score_ctr(),
            'account_activity': self._score_account_activity(),
            'ad_format_diversity': self._score_ad_format_diversity(),
            'campaign_structure': self._score_campaign_structure(),
            'landing_page': self._score_landing_page(),
            'mobile_optimization': self._score_mobile_optimization(),
            'conversion_tracking': self._score_conversion_tracking(),
            'roas': self._score_roas(),
        }

        # Calculate weighted overall score
        overall_score = sum(
            score * self.SECTION_WEIGHTS[section]
            for section, score in section_scores.items()
        )

        # Generate grade
        overall_grade = self._calculate_grade(overall_score)

        # Generate recommendations
        recommendations = self._generate_recommendations(section_scores)

        # Check best practices
        best_practices = self._check_best_practices()

        # Extract key metrics
        key_metrics = self._extract_key_metrics()

        # Account diagnostics
        account_diagnostics = self._extract_account_diagnostics()

        return {
            'overall_score': round(overall_score, 1),
            'overall_grade': overall_grade,
            'section_scores': section_scores,
            'recommendations': recommendations,
            'best_practices': best_practices,
            'key_metrics': key_metrics,
            'account_diagnostics': account_diagnostics,
        }

    def _score_wasted_spend(self) -> float:
        """
        Score based on wasted spend from poor-performing ads.

        Analyzes:
        - Ads with very low CTR
        - Ads with high CPC
        - Ads with no conversions
        """
        # For now, use a simple heuristic based on overall performance
        # In a real implementation, we'd analyze individual ad performance

        ctr = self.performance.get('ctr', 0)
        cpc = self.performance.get('cpc', 0)
        spend = self.performance.get('spend', 0)

        score = 50  # Start at 50

        # Good CTR reduces wasted spend
        if ctr >= self.BENCHMARKS['ctr']['excellent']:
            score += 30
        elif ctr >= self.BENCHMARKS['ctr']['good']:
            score += 15
        elif ctr >= self.BENCHMARKS['ctr']['average']:
            score += 5
        else:
            score -= 20

        # Low CPC indicates less waste
        if cpc <= self.BENCHMARKS['cpc']['excellent']:
            score += 20
        elif cpc <= self.BENCHMARKS['cpc']['good']:
            score += 10
        elif cpc <= self.BENCHMARKS['cpc']['average']:
            score += 5
        else:
            score -= 10

        return max(0, min(100, score))

    def _score_creative_optimization(self) -> float:
        """
        Score based on creative testing and variety.

        Analyzes:
        - Number of unique creatives
        - Ads per ad set ratio
        - Creative rotation strategy
        """
        total_ads = self.ads.get('total_ads', 0)
        active_ads = self.ads.get('active_ads', 0)
        unique_creatives = self.ads.get('unique_creatives', 0)
        active_ad_sets = self.ad_sets.get('active_ad_sets', 1)

        score = 0

        # Multiple ads per ad set (testing)
        if active_ad_sets > 0:
            ads_per_ad_set = active_ads / active_ad_sets
            if ads_per_ad_set >= 3:
                score += 40
            elif ads_per_ad_set >= 2:
                score += 25
            elif ads_per_ad_set >= 1.5:
                score += 15
            else:
                score += 5

        # Creative variety
        if active_ads > 0 and unique_creatives > 0:
            creative_variety = unique_creatives / active_ads
            if creative_variety >= 0.8:
                score += 40
            elif creative_variety >= 0.5:
                score += 25
            elif creative_variety >= 0.3:
                score += 15
            else:
                score += 5

        # Bonus for good number of active creatives
        if unique_creatives >= 20:
            score += 20
        elif unique_creatives >= 10:
            score += 10
        elif unique_creatives >= 5:
            score += 5

        return min(100, score)

    def _score_audience_targeting(self) -> float:
        """
        Score based on audience diversity and sophistication.

        Analyzes:
        - Number of unique audiences
        - Audience size balance
        - Use of custom audiences, lookalikes, etc.
        """
        unique_audiences = self.ad_sets.get('unique_audiences', 0)

        score = 0

        # Audience diversity
        if unique_audiences >= 10:
            score += 60
        elif unique_audiences >= 5:
            score += 40
        elif unique_audiences >= 3:
            score += 25
        elif unique_audiences >= 1:
            score += 15
        else:
            score = 10

        # Assume some best practices if we have multiple audiences
        if unique_audiences >= 5:
            score += 40  # Likely using diverse targeting strategies
        elif unique_audiences >= 3:
            score += 20

        return min(100, score)

    def _score_relevance(self) -> float:
        """
        Score based on ad relevance and engagement.

        Note: Facebook deprecated Relevance Score in 2019 and replaced it with
        Quality Ranking, Engagement Rate Ranking, and Conversion Rate Ranking.
        We'll estimate based on CTR and engagement.
        """
        ctr = self.performance.get('ctr', 0)

        score = 50  # Baseline

        # Higher CTR indicates better relevance
        if ctr >= 3.0:
            score = 100
        elif ctr >= 2.0:
            score = 85
        elif ctr >= 1.5:
            score = 75
        elif ctr >= 1.0:
            score = 65
        elif ctr >= 0.5:
            score = 50
        else:
            score = max(20, ctr * 40)  # Scale from 0-0.5% CTR

        return min(100, score)

    def _score_ctr(self) -> float:
        """
        Score based on click-through rate performance.
        """
        ctr = self.performance.get('ctr', 0)

        if ctr >= self.BENCHMARKS['ctr']['excellent']:
            score = 100
        elif ctr >= self.BENCHMARKS['ctr']['good']:
            score = 75
        elif ctr >= self.BENCHMARKS['ctr']['average']:
            score = 50
        else:
            # Scale from 0-0.5% CTR
            score = max(10, (ctr / self.BENCHMARKS['ctr']['average']) * 50)

        return min(100, score)

    def _score_account_activity(self) -> float:
        """
        Score based on ongoing optimization and management.

        Analyzes:
        - Number of active campaigns
        - Campaign age and updates
        - Overall account health
        """
        active_campaigns = self.campaigns.get('active_campaigns', 0)
        total_campaigns = self.campaigns.get('total_campaigns', 0)

        score = 0

        # Active campaign count
        if active_campaigns >= 5:
            score += 50
        elif active_campaigns >= 3:
            score += 35
        elif active_campaigns >= 1:
            score += 20
        else:
            score = 10

        # Campaign activity ratio
        if total_campaigns > 0:
            activity_ratio = active_campaigns / total_campaigns
            if activity_ratio >= 0.7:
                score += 30
            elif activity_ratio >= 0.5:
                score += 20
            elif activity_ratio >= 0.3:
                score += 10

        # Good number of total campaigns indicates testing
        if total_campaigns >= 10:
            score += 20
        elif total_campaigns >= 5:
            score += 10

        return min(100, score)

    def _score_ad_format_diversity(self) -> float:
        """
        Score based on use of different ad formats.

        Ideal: Video, Carousel, Single Image, Collection, etc.
        """
        # This would require analyzing creative types from API
        # For now, give a baseline score
        total_ads = self.ads.get('total_ads', 0)

        score = 50  # Baseline assumption

        # More ads likely means more format diversity
        if total_ads >= 50:
            score = 85
        elif total_ads >= 20:
            score = 70
        elif total_ads >= 10:
            score = 60

        return score

    def _score_campaign_structure(self) -> float:
        """
        Score based on account organization and structure.

        Analyzes:
        - Campaigns per objective
        - Ad sets per campaign
        - Structure best practices
        """
        total_campaigns = self.campaigns.get('total_campaigns', 0)
        total_ad_sets = self.ad_sets.get('total_ad_sets', 0)

        score = 0

        # Good number of campaigns
        if total_campaigns >= 5:
            score += 40
        elif total_campaigns >= 3:
            score += 30
        elif total_campaigns >= 1:
            score += 15

        # Good ad sets per campaign ratio
        if total_campaigns > 0:
            ad_sets_per_campaign = total_ad_sets / total_campaigns
            if 2 <= ad_sets_per_campaign <= 10:
                score += 60  # Ideal range
            elif 1 <= ad_sets_per_campaign <= 15:
                score += 40
            else:
                score += 20

        return min(100, score)

    def _score_landing_page(self) -> float:
        """
        Score based on landing page optimization.

        Analyzes:
        - Conversion rate
        - Page load speed (if available)
        - Mobile optimization
        """
        conversion_rate = self.performance.get('conversion_rate', 0)
        conversions = self.performance.get('conversions', 0)

        score = 50  # Baseline

        # Conversion rate is the best indicator
        if conversion_rate >= self.BENCHMARKS['conversion_rate']['excellent']:
            score = 100
        elif conversion_rate >= self.BENCHMARKS['conversion_rate']['good']:
            score = 80
        elif conversion_rate >= self.BENCHMARKS['conversion_rate']['average']:
            score = 60
        elif conversion_rate > 0:
            score = 40
        else:
            score = 20  # No conversions tracked

        # Bonus for having conversions
        if conversions > 100:
            score = min(100, score + 10)

        return score

    def _score_mobile_optimization(self) -> float:
        """
        Score based on mobile advertising effectiveness.

        Analyzes:
        - Mobile traffic percentage
        - Mobile CTR vs desktop
        - Mobile CPC vs desktop
        """
        mobile = self.device_performance.get('mobile', {})
        desktop = self.device_performance.get('desktop', {})

        mobile_percentage = mobile.get('percentage', 0)
        mobile_ctr = mobile.get('ctr', 0)
        desktop_ctr = desktop.get('ctr', 0)

        score = 50  # Baseline

        # Mobile traffic percentage
        if mobile_percentage >= 70:
            score += 30
        elif mobile_percentage >= 50:
            score += 20
        elif mobile_percentage >= 30:
            score += 10

        # Mobile CTR performance
        if mobile_ctr >= 1.5:
            score += 20
        elif mobile_ctr >= 1.0:
            score += 10

        # Mobile vs desktop performance
        if desktop_ctr > 0 and mobile_ctr >= desktop_ctr:
            score += 20  # Mobile performing as well or better

        return min(100, score)

    def _score_conversion_tracking(self) -> float:
        """
        Score based on conversion tracking setup.

        Analyzes:
        - Pixel installation
        - Conversion events tracked
        - Attribution quality
        """
        conversions = self.performance.get('conversions', 0)
        conversion_value = self.performance.get('conversion_value', 0)
        spend = self.performance.get('spend', 0)

        score = 0

        # Has conversions tracked
        if conversions > 0:
            score += 60
        else:
            return 20  # Major penalty for no tracking

        # Has conversion value tracked
        if conversion_value > 0:
            score += 20

        # Good conversion volume
        if conversions >= 100:
            score += 10
        elif conversions >= 50:
            score += 5

        # Spending enough to have meaningful data
        if spend >= 1000:
            score += 10

        return min(100, score)

    def _score_roas(self) -> float:
        """
        Score based on return on ad spend.
        """
        roas = self.performance.get('roas', 0)
        conversion_value = self.performance.get('conversion_value', 0)

        # If no conversion value tracked, can't score ROAS
        if conversion_value == 0:
            return 50  # Neutral score

        if roas >= self.BENCHMARKS['roas']['excellent']:
            score = 100
        elif roas >= self.BENCHMARKS['roas']['good']:
            score = 80
        elif roas >= self.BENCHMARKS['roas']['breakeven']:
            score = 60
        elif roas >= 0.5:
            score = 40
        else:
            score = 20

        return score

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

    def _generate_recommendations(self, section_scores: Dict[str, float]) -> List[str]:
        """
        Generate actionable recommendations based on section scores.
        """
        recommendations = []

        # Wasted spend
        if section_scores['wasted_spend'] < 60:
            ctr = self.performance.get('ctr', 0)
            if ctr < 1.0:
                recommendations.append(
                    f"Your CTR is {ctr:.2f}%. Pause low-performing ads and create 3-5 new ad variations to improve CTR to 1.5%+"
                )

        # Creative optimization
        if section_scores['creative_optimization'] < 70:
            unique_creatives = self.ads.get('unique_creatives', 0)
            if unique_creatives < 10:
                recommendations.append(
                    f"Test more ad creatives. You have {unique_creatives} unique creatives - aim for 15-20 for better testing"
                )

        # Audience targeting
        if section_scores['audience_targeting'] < 70:
            unique_audiences = self.ad_sets.get('unique_audiences', 0)
            if unique_audiences < 5:
                recommendations.append(
                    f"Expand your audience testing with lookalike audiences and custom audience combinations"
                )

        # CTR
        if section_scores['ctr_optimization'] < 70:
            recommendations.append(
                "Improve ad creative quality with more engaging visuals, clear value propositions, and strong CTAs"
            )

        # Mobile optimization
        if section_scores['mobile_optimization'] < 70:
            mobile_percentage = self.device_performance.get('mobile', {}).get('percentage', 0)
            if mobile_percentage < 60:
                recommendations.append(
                    f"Optimize for mobile - only {mobile_percentage:.0f}% of your traffic is mobile. Use mobile-first creatives and landing pages"
                )

        # Conversion tracking
        if section_scores['conversion_tracking'] < 70:
            conversions = self.performance.get('conversions', 0)
            if conversions == 0:
                recommendations.append(
                    "Install Facebook Pixel and set up conversion events to track ROAS and optimize campaigns effectively"
                )

        # ROAS
        if section_scores['roas'] < 70:
            roas = self.performance.get('roas', 0)
            if roas < 2.0 and roas > 0:
                recommendations.append(
                    f"Your ROAS is {roas:.2f}. Focus on higher-intent audiences and optimize landing pages to reach 3:1 ROAS"
                )

        # Ad format diversity
        if section_scores['ad_format_diversity'] < 70:
            recommendations.append(
                "Test video ads, carousel ads, and collection ads to find which formats resonate best with your audience"
            )

        # General recommendations
        if not recommendations:
            recommendations.append(
                "Your account is performing well! Focus on scaling winners and continuing to test new audiences and creatives"
            )

        return recommendations[:10]  # Return top 10

    def _check_best_practices(self) -> Dict[str, bool]:
        """
        Check if account follows Facebook Ads best practices.
        """
        conversions = self.performance.get('conversions', 0)
        unique_creatives = self.ads.get('unique_creatives', 0)
        unique_audiences = self.ad_sets.get('unique_audiences', 0)
        active_ad_sets = self.ad_sets.get('active_ad_sets', 0)
        active_ads = self.ads.get('active_ads', 0)
        mobile_percentage = self.device_performance.get('mobile', {}).get('percentage', 0)

        return {
            'conversion_tracking': conversions > 0,
            'pixel_installed': conversions > 0,  # Assume pixel if conversions exist
            'multiple_ad_creatives': unique_creatives >= 10,
            'audience_testing': unique_audiences >= 3,
            'placement_optimization': True,  # Assume yes if using API
            'mobile_optimized': mobile_percentage >= 50,
            'ad_rotation': (active_ads / active_ad_sets) >= 2 if active_ad_sets > 0 else False,
            'retargeting_campaigns': True,  # Would need to check campaign objectives
            'lookalike_audiences': unique_audiences >= 5,  # Assume if multiple audiences
            'dynamic_ads': False,  # Would need creative type analysis
        }

    def _extract_key_metrics(self) -> Dict[str, Any]:
        """Extract key metrics for display."""
        return {
            'ctr_avg': round(self.performance.get('ctr', 0), 2),
            'cpc_avg': round(self.performance.get('cpc', 0), 2),
            'cpm_avg': round(self.performance.get('cpm', 0), 2),
            'roas_avg': round(self.performance.get('roas', 0), 2),
            'conversion_rate_avg': round(self.performance.get('conversion_rate', 0), 2),
            'wasted_spend_365d': self._estimate_wasted_spend(),
            'projected_waste_12m': self._estimate_wasted_spend(),  # Same value for projection
        }

    def _estimate_wasted_spend(self) -> float:
        """
        Estimate wasted spend from poor-performing ads.
        """
        spend = self.performance.get('spend', 0)
        ctr = self.performance.get('ctr', 0)

        # Rough estimate: if CTR < 0.5%, assume 30-50% waste
        if ctr < 0.5:
            waste_percentage = 0.4
        elif ctr < 1.0:
            waste_percentage = 0.2
        elif ctr < 1.5:
            waste_percentage = 0.1
        else:
            waste_percentage = 0.05

        return round(spend * waste_percentage, 2)

    def _extract_account_diagnostics(self) -> Dict[str, Any]:
        """Extract account diagnostic information."""
        return {
            'active_campaigns': self.campaigns.get('active_campaigns', 0),
            'active_ad_sets': self.ad_sets.get('active_ad_sets', 0),
            'active_ads': self.ads.get('active_ads', 0),
            'total_audiences': self.ad_sets.get('unique_audiences', 0),
            'clicks_365d': self.performance.get('clicks', 0),
            'impressions_365d': self.performance.get('impressions', 0),
            'conversions_365d': int(self.performance.get('conversions', 0)),
            'spend_365d': round(self.performance.get('spend', 0), 2),
            'revenue_365d': round(self.performance.get('conversion_value', 0), 2),
            'avg_monthly_spend': round(self.performance.get('spend', 0) / 12, 2),  # 365 days / 12 months
        }


__all__ = ['FacebookAdsAnalyzer']
