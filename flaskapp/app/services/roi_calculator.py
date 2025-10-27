"""
ROI Calculator for Google Ads Optimization

Calculates estimated savings, lead increases, and ROI improvements
for recommendations in both the Inspector and AI Optimizer.
"""
from typing import Dict, Optional, Tuple
from decimal import Decimal


class ROICalculator:
    """Calculate ROI improvements for Google Ads optimizations."""

    # Conservative improvement ranges based on industry benchmarks
    IMPROVEMENT_RANGES = {
        'wasted_spend': {
            'min': 0.15,  # 15% reduction
            'max': 0.35,  # 35% reduction
            'typical': 0.25  # 25% reduction
        },
        'quality_score': {
            'cpc_reduction_per_point': 0.16,  # 16% CPC reduction per QS point
            'ctr_improvement': 0.20  # 20% CTR improvement
        },
        'ctr': {
            'min': 0.10,  # 10% improvement
            'max': 0.40,  # 40% improvement
            'typical': 0.25  # 25% improvement
        },
        'ad_optimization': {
            'ctr_boost': 0.20,  # 20% CTR boost
            'cvr_boost': 0.15  # 15% conversion rate boost
        },
        'negative_keywords': {
            'waste_reduction': 0.30,  # 30% waste reduction
            'ctr_improvement': 0.15  # 15% CTR improvement
        },
        'landing_pages': {
            'cvr_boost': 0.25,  # 25% conversion rate boost
            'bounce_reduction': 0.30  # 30% bounce reduction
        },
        'mobile': {
            'mobile_cvr_boost': 0.35,  # 35% mobile conversion boost
            'mobile_ctr_boost': 0.25  # 25% mobile CTR boost
        },
        'long_tail': {
            'cpa_reduction': 0.20,  # 20% CPA reduction
            'cvr_boost': 0.18  # 18% conversion rate boost
        },
        'impression_share': {
            'traffic_increase': 0.25,  # 25% traffic increase
            'conversion_increase': 0.20  # 20% conversion increase
        },
        'account_structure': {
            'efficiency_gain': 0.15,  # 15% efficiency gain
            'qr_improvement': 1.0  # 1 point QS improvement
        }
    }

    @staticmethod
    def calculate_spend_savings(
        current_spend: float,
        category: str,
        timeframe_days: int = 30,
        severity: int = 1
    ) -> Dict[str, float]:
        """
        Calculate estimated spend savings.

        Args:
            current_spend: Current spend amount
            category: Optimization category
            timeframe_days: Days in the current spend period
            severity: Recommendation severity (1=critical, 5=minor)

        Returns:
            Dict with monthly_savings, annual_savings, percentage_reduction
        """
        # Get improvement rate based on category
        if category in ['wasted_spend', 'negatives', 'negative_keywords']:
            base_reduction = ROICalculator.IMPROVEMENT_RANGES['wasted_spend']['typical']
        elif category in ['quality_score', 'ads', 'ad_optimization']:
            base_reduction = ROICalculator.IMPROVEMENT_RANGES['ad_optimization']['ctr_boost']
        elif category in ['keywords', 'long_tail', 'long_tail_keywords']:
            base_reduction = ROICalculator.IMPROVEMENT_RANGES['long_tail']['cpa_reduction']
        elif category in ['landing_pages', 'landing_page']:
            base_reduction = 0.15  # Conservative for landing pages
        elif category in ['mobile', 'mobile_advertising']:
            base_reduction = 0.18
        else:
            base_reduction = 0.15  # Default conservative estimate

        # Adjust based on severity (more severe = higher potential savings)
        severity_multiplier = {
            1: 1.3,  # Critical issues have highest savings potential
            2: 1.1,
            3: 1.0,
            4: 0.8,
            5: 0.6
        }.get(severity, 1.0)

        reduction_rate = base_reduction * severity_multiplier
        reduction_rate = min(reduction_rate, 0.45)  # Cap at 45% max

        # Calculate savings
        monthly_spend = (current_spend / timeframe_days) * 30
        monthly_savings = monthly_spend * reduction_rate
        annual_savings = monthly_savings * 12

        return {
            'monthly_savings': round(monthly_savings, 2),
            'annual_savings': round(annual_savings, 2),
            'percentage_reduction': round(reduction_rate * 100, 1),
            'daily_savings': round(monthly_savings / 30, 2)
        }

    @staticmethod
    def calculate_lead_increase(
        current_conversions: float,
        current_spend: float,
        category: str,
        timeframe_days: int = 30,
        severity: int = 1
    ) -> Dict[str, float]:
        """
        Calculate estimated lead/conversion increases.

        Args:
            current_conversions: Current conversion count
            current_spend: Current spend amount
            category: Optimization category
            timeframe_days: Days in the current period
            severity: Recommendation severity

        Returns:
            Dict with monthly_new_leads, annual_new_leads, percentage_increase
        """
        # Get improvement rate based on category
        if category in ['landing_pages', 'landing_page']:
            base_increase = ROICalculator.IMPROVEMENT_RANGES['landing_pages']['cvr_boost']
        elif category in ['ads', 'ad_optimization', 'text_ad']:
            base_increase = ROICalculator.IMPROVEMENT_RANGES['ad_optimization']['cvr_boost']
        elif category in ['ctr', 'ctr_optimization']:
            base_increase = ROICalculator.IMPROVEMENT_RANGES['ctr']['typical']
        elif category in ['mobile', 'mobile_advertising']:
            base_increase = ROICalculator.IMPROVEMENT_RANGES['mobile']['mobile_cvr_boost']
        elif category in ['long_tail', 'keywords', 'long_tail_keywords']:
            base_increase = ROICalculator.IMPROVEMENT_RANGES['long_tail']['cvr_boost']
        elif category in ['impression_share']:
            base_increase = ROICalculator.IMPROVEMENT_RANGES['impression_share']['conversion_increase']
        else:
            base_increase = 0.15  # Default conservative estimate

        # Adjust based on severity
        severity_multiplier = {
            1: 1.2,
            2: 1.1,
            3: 1.0,
            4: 0.85,
            5: 0.7
        }.get(severity, 1.0)

        increase_rate = base_increase * severity_multiplier
        increase_rate = min(increase_rate, 0.50)  # Cap at 50% max

        # Calculate lead increases
        monthly_conversions = (current_conversions / timeframe_days) * 30
        monthly_new_leads = monthly_conversions * increase_rate
        annual_new_leads = monthly_new_leads * 12

        # Calculate current CPA for context
        current_cpa = (current_spend / current_conversions) if current_conversions > 0 else 0

        return {
            'monthly_new_leads': round(monthly_new_leads, 1),
            'annual_new_leads': round(annual_new_leads, 1),
            'percentage_increase': round(increase_rate * 100, 1),
            'current_cpa': round(current_cpa, 2),
            'weekly_new_leads': round(monthly_new_leads / 4.3, 1)
        }

    @staticmethod
    def calculate_combined_roi(
        current_spend: float,
        current_conversions: float,
        avg_customer_value: Optional[float],
        category: str,
        timeframe_days: int = 30,
        severity: int = 1
    ) -> Dict[str, any]:
        """
        Calculate combined ROI including both savings and lead increases.

        Args:
            current_spend: Current spend amount
            current_conversions: Current conversion count
            avg_customer_value: Average value per customer (optional)
            category: Optimization category
            timeframe_days: Days in current period
            severity: Recommendation severity

        Returns:
            Comprehensive ROI analysis
        """
        savings = ROICalculator.calculate_spend_savings(
            current_spend, category, timeframe_days, severity
        )

        leads = ROICalculator.calculate_lead_increase(
            current_conversions, current_spend, category, timeframe_days, severity
        )

        # Calculate total value
        monthly_value = savings['monthly_savings']
        annual_value = savings['annual_savings']

        if avg_customer_value and avg_customer_value > 0:
            # Add value from new leads
            monthly_lead_value = leads['monthly_new_leads'] * avg_customer_value
            annual_lead_value = leads['annual_new_leads'] * avg_customer_value

            monthly_value += monthly_lead_value
            annual_value += annual_lead_value

        return {
            'savings': savings,
            'leads': leads,
            'total_monthly_value': round(monthly_value, 2),
            'total_annual_value': round(annual_value, 2),
            'has_customer_value': avg_customer_value is not None and avg_customer_value > 0,
            'roi_summary': ROICalculator._format_roi_summary(
                savings, leads, monthly_value, annual_value, avg_customer_value
            )
        }

    @staticmethod
    def _format_roi_summary(
        savings: Dict,
        leads: Dict,
        monthly_value: float,
        annual_value: float,
        avg_customer_value: Optional[float]
    ) -> str:
        """Format a human-readable ROI summary."""
        parts = []

        # Savings component
        if savings['monthly_savings'] > 0:
            parts.append(f"Save ${savings['monthly_savings']:,.0f}/month")

        # Leads component
        if leads['monthly_new_leads'] > 0:
            parts.append(f"+{leads['monthly_new_leads']:.0f} leads/month")

        # Total value
        if monthly_value > 0:
            if avg_customer_value:
                parts.append(f"Total value: ${monthly_value:,.0f}/month")
            else:
                parts.append(f"${monthly_value:,.0f}/month value")

        return " • ".join(parts) if parts else "Efficiency improvement"

    @staticmethod
    def calculate_quality_score_impact(
        current_qs: float,
        target_qs: float,
        current_spend: float,
        timeframe_days: int = 30
    ) -> Dict[str, float]:
        """
        Calculate impact of Quality Score improvement.

        Quality Score improvements reduce CPC by ~16% per point.
        """
        qs_improvement = target_qs - current_qs
        cpc_reduction = qs_improvement * 0.16  # 16% per point
        cpc_reduction = min(cpc_reduction, 0.50)  # Cap at 50%

        monthly_spend = (current_spend / timeframe_days) * 30
        monthly_savings = monthly_spend * cpc_reduction

        return {
            'qs_improvement': round(qs_improvement, 1),
            'cpc_reduction_percent': round(cpc_reduction * 100, 1),
            'monthly_savings': round(monthly_savings, 2),
            'annual_savings': round(monthly_savings * 12, 2),
            'summary': f"Improve QS from {current_qs:.1f} to {target_qs:.1f} → Save ${monthly_savings:,.0f}/month"
        }

    @staticmethod
    def estimate_implementation_effort(category: str, severity: int) -> Dict[str, str]:
        """
        Estimate effort required to implement recommendation.

        Returns:
            Dict with time_estimate, difficulty, priority
        """
        # Time estimates based on category
        time_by_category = {
            'negative_keywords': '15-30 min',
            'negatives': '15-30 min',
            'ads': '30-60 min',
            'ad_optimization': '30-60 min',
            'keywords': '20-45 min',
            'quality_score': '1-2 hours',
            'landing_pages': '2-4 hours',
            'landing_page': '2-4 hours',
            'mobile': '1-2 hours',
            'ctr': '30-60 min',
            'impression_share': '30 min',
            'bidding': '15-30 min',
            'budget': '10-20 min',
            'targeting': '20-40 min'
        }

        # Difficulty based on category
        difficulty_by_category = {
            'negative_keywords': 'Easy',
            'negatives': 'Easy',
            'budget': 'Easy',
            'bidding': 'Easy',
            'ads': 'Medium',
            'keywords': 'Medium',
            'targeting': 'Medium',
            'mobile': 'Medium',
            'quality_score': 'Medium',
            'landing_pages': 'Hard',
            'landing_page': 'Hard'
        }

        # Priority based on severity
        priority_map = {
            1: 'Critical',
            2: 'High',
            3: 'Medium',
            4: 'Low',
            5: 'Optional'
        }

        return {
            'time_estimate': time_by_category.get(category, '30-60 min'),
            'difficulty': difficulty_by_category.get(category, 'Medium'),
            'priority': priority_map.get(severity, 'Medium')
        }
