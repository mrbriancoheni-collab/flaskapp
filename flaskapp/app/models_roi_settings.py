"""
ROI Settings Model

Stores configurable parameters for ROI calculations and pricing.
"""
from app import db
from datetime import datetime
from sqlalchemy import text


class ROISettings(db.Model):
    """
    Settings for ROI calculations and service pricing.
    Allows admin to adjust improvement percentages and pricing formulas.
    """
    __tablename__ = 'roi_settings'

    id = db.Column(db.Integer, primary_key=True)
    setting_key = db.Column(db.String(64), unique=True, nullable=False, index=True)
    setting_name = db.Column(db.String(128), nullable=False)
    setting_value = db.Column(db.Text, nullable=False)
    setting_type = db.Column(db.String(32), nullable=False)  # 'percentage', 'multiplier', 'formula', 'text'
    description = db.Column(db.Text)
    category = db.Column(db.String(64))  # 'improvement_rates', 'pricing', 'effort'
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = db.Column(db.Integer, db.ForeignKey('users.id'))

    def __repr__(self):
        return f'<ROISettings {self.setting_key}: {self.setting_value}>'

    @staticmethod
    def get_value(key, default=None):
        """Get a setting value by key."""
        setting = ROISettings.query.filter_by(setting_key=key).first()
        if not setting:
            return default

        # Convert based on type
        if setting.setting_type == 'percentage':
            return float(setting.setting_value) / 100.0
        elif setting.setting_type == 'multiplier':
            return float(setting.setting_value)
        elif setting.setting_type == 'formula':
            return setting.setting_value
        else:
            return setting.setting_value

    @staticmethod
    def set_value(key, value, user_id=None):
        """Set a setting value by key."""
        setting = ROISettings.query.filter_by(setting_key=key).first()
        if setting:
            setting.setting_value = str(value)
            setting.updated_by = user_id
            setting.updated_at = datetime.utcnow()
        else:
            setting = ROISettings(
                setting_key=key,
                setting_value=str(value),
                updated_by=user_id
            )
            db.session.add(setting)
        db.session.commit()

    @staticmethod
    def get_all_by_category(category):
        """Get all settings in a category."""
        return ROISettings.query.filter_by(category=category).order_by(ROISettings.setting_name).all()


class ServicePricing(db.Model):
    """
    Service pricing tiers based on account size/spend.
    """
    __tablename__ = 'service_pricing'

    id = db.Column(db.Integer, primary_key=True)
    tier_name = db.Column(db.String(64), nullable=False)
    min_monthly_spend = db.Column(db.Integer, nullable=False)  # Minimum ad spend
    max_monthly_spend = db.Column(db.Integer)  # Maximum ad spend (null = unlimited)
    base_price = db.Column(db.Integer, nullable=False)  # Base monthly price in cents
    percentage_of_savings = db.Column(db.Float)  # % of savings to charge
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<ServicePricing {self.tier_name}: ${self.base_price/100}/mo>'

    @staticmethod
    def get_pricing_for_spend(monthly_spend):
        """Get appropriate pricing tier for a monthly spend amount."""
        return ServicePricing.query.filter(
            ServicePricing.is_active == True,
            ServicePricing.min_monthly_spend <= monthly_spend,
            db.or_(
                ServicePricing.max_monthly_spend >= monthly_spend,
                ServicePricing.max_monthly_spend.is_(None)
            )
        ).order_by(ServicePricing.min_monthly_spend.desc()).first()

    def calculate_price(self, estimated_savings):
        """
        Calculate service price based on savings.

        Args:
            estimated_savings: Monthly savings estimate

        Returns:
            Recommended monthly price
        """
        if self.percentage_of_savings:
            calculated_price = estimated_savings * self.percentage_of_savings
            # Use higher of base price or calculated price
            return max(self.base_price / 100, calculated_price)
        return self.base_price / 100


def initialize_roi_settings():
    """Initialize default ROI settings if they don't exist."""

    default_settings = [
        # Improvement Rates - Wasted Spend
        {
            'setting_key': 'wasted_spend_min',
            'setting_name': 'Wasted Spend - Minimum Reduction',
            'setting_value': '15',
            'setting_type': 'percentage',
            'category': 'improvement_rates',
            'description': 'Minimum % reduction in wasted spend from negative keywords'
        },
        {
            'setting_key': 'wasted_spend_max',
            'setting_name': 'Wasted Spend - Maximum Reduction',
            'setting_value': '35',
            'setting_type': 'percentage',
            'category': 'improvement_rates',
            'description': 'Maximum % reduction in wasted spend from negative keywords'
        },
        {
            'setting_key': 'wasted_spend_typical',
            'setting_name': 'Wasted Spend - Typical Reduction',
            'setting_value': '25',
            'setting_type': 'percentage',
            'category': 'improvement_rates',
            'description': 'Typical % reduction in wasted spend from negative keywords'
        },

        # Quality Score
        {
            'setting_key': 'qs_cpc_reduction_per_point',
            'setting_name': 'Quality Score - CPC Reduction Per Point',
            'setting_value': '16',
            'setting_type': 'percentage',
            'category': 'improvement_rates',
            'description': 'CPC reduction per Quality Score point improvement (industry standard: 16%)'
        },
        {
            'setting_key': 'qs_ctr_improvement',
            'setting_name': 'Quality Score - CTR Improvement',
            'setting_value': '20',
            'setting_type': 'percentage',
            'category': 'improvement_rates',
            'description': 'CTR improvement from Quality Score optimization'
        },

        # CTR Optimization
        {
            'setting_key': 'ctr_min_improvement',
            'setting_name': 'CTR - Minimum Improvement',
            'setting_value': '10',
            'setting_type': 'percentage',
            'category': 'improvement_rates',
            'description': 'Minimum CTR improvement from ad testing'
        },
        {
            'setting_key': 'ctr_max_improvement',
            'setting_name': 'CTR - Maximum Improvement',
            'setting_value': '40',
            'setting_type': 'percentage',
            'category': 'improvement_rates',
            'description': 'Maximum CTR improvement from ad testing'
        },
        {
            'setting_key': 'ctr_typical_improvement',
            'setting_name': 'CTR - Typical Improvement',
            'setting_value': '25',
            'setting_type': 'percentage',
            'category': 'improvement_rates',
            'description': 'Typical CTR improvement from ad testing'
        },

        # Landing Pages
        {
            'setting_key': 'landing_page_cvr_boost',
            'setting_name': 'Landing Page - Conversion Rate Boost',
            'setting_value': '25',
            'setting_type': 'percentage',
            'category': 'improvement_rates',
            'description': 'Conversion rate improvement from landing page optimization'
        },

        # Mobile
        {
            'setting_key': 'mobile_cvr_boost',
            'setting_name': 'Mobile - Conversion Rate Boost',
            'setting_value': '35',
            'setting_type': 'percentage',
            'category': 'improvement_rates',
            'description': 'Mobile conversion rate improvement'
        },

        # Pricing Settings
        {
            'setting_key': 'pricing_min_percentage',
            'setting_name': 'Pricing - Minimum % of Savings',
            'setting_value': '10',
            'setting_type': 'percentage',
            'category': 'pricing',
            'description': 'Minimum percentage of savings to charge (10% = client keeps 90%)'
        },
        {
            'setting_key': 'pricing_max_percentage',
            'setting_name': 'Pricing - Maximum % of Savings',
            'setting_value': '30',
            'setting_type': 'percentage',
            'category': 'pricing',
            'description': 'Maximum percentage of savings to charge (30% = client keeps 70%)'
        },
        {
            'setting_key': 'pricing_recommended_percentage',
            'setting_name': 'Pricing - Recommended % of Savings',
            'setting_value': '20',
            'setting_type': 'percentage',
            'category': 'pricing',
            'description': 'Recommended percentage of savings to charge (20% = client keeps 80%)'
        },
        {
            'setting_key': 'pricing_formula',
            'setting_name': 'Pricing Formula',
            'setting_value': 'max(base_price, total_savings * percentage)',
            'setting_type': 'formula',
            'category': 'pricing',
            'description': 'Formula to calculate monthly service price'
        },

        # Value Messaging
        {
            'setting_key': 'show_roi_multiplier',
            'setting_name': 'Show ROI Multiplier',
            'setting_value': 'true',
            'setting_type': 'text',
            'category': 'display',
            'description': 'Show "5x ROI" messaging (savings vs. cost)'
        },
        {
            'setting_key': 'roi_summary_format',
            'setting_name': 'ROI Summary Format',
            'setting_value': 'Save ${monthly_savings}/month for just ${service_cost}/month',
            'setting_type': 'text',
            'category': 'display',
            'description': 'Format for ROI summary message'
        }
    ]

    for setting in default_settings:
        existing = ROISettings.query.filter_by(setting_key=setting['setting_key']).first()
        if not existing:
            new_setting = ROISettings(**setting)
            db.session.add(new_setting)

    db.session.commit()


def initialize_pricing_tiers():
    """Initialize default pricing tiers if they don't exist."""

    default_tiers = [
        {
            'tier_name': 'Starter',
            'min_monthly_spend': 0,
            'max_monthly_spend': 2000,
            'base_price': 29900,  # $299/month
            'percentage_of_savings': 0.20,
            'description': 'Perfect for small businesses spending up to $2k/month on ads'
        },
        {
            'tier_name': 'Growth',
            'min_monthly_spend': 2001,
            'max_monthly_spend': 5000,
            'base_price': 49900,  # $499/month
            'percentage_of_savings': 0.20,
            'description': 'Ideal for growing businesses spending $2k-$5k/month'
        },
        {
            'tier_name': 'Professional',
            'min_monthly_spend': 5001,
            'max_monthly_spend': 10000,
            'base_price': 79900,  # $799/month
            'percentage_of_savings': 0.18,
            'description': 'For established businesses spending $5k-$10k/month'
        },
        {
            'tier_name': 'Enterprise',
            'min_monthly_spend': 10001,
            'max_monthly_spend': None,
            'base_price': 99900,  # $999/month
            'percentage_of_savings': 0.15,
            'description': 'Custom pricing for businesses spending $10k+/month'
        }
    ]

    for tier in default_tiers:
        existing = ServicePricing.query.filter_by(tier_name=tier['tier_name']).first()
        if not existing:
            new_tier = ServicePricing(**tier)
            db.session.add(new_tier)

    db.session.commit()
