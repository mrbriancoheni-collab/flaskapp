# app/admin/agent_config_routes.py
"""
Admin routes for AI Agent configuration.

Allows admins to configure:
- Enable/disable agents per account
- Adjust auto-execute thresholds
- Add custom business context to agent prompts
- Override risk levels per decision type
- Define business rules for decision making
"""
from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, g
from sqlalchemy import text
import json

from app import db
from app.auth.decorators import require_admin_cloaked as require_admin
from app.auth.session_helpers import login_required

agent_config_bp = Blueprint("agent_config_bp", __name__, url_prefix="/admin/agents")


# ============================================================================
# Agent Configuration Management
# ============================================================================

@agent_config_bp.route("/configure")
@login_required
@require_admin
def configure_list():
    """List all agent configurations."""
    from app.models import Account

    # Get all accounts
    accounts = Account.query.order_by(Account.name).all()

    # Get global configurations
    global_configs_query = text("""
        SELECT * FROM agent_configurations
        WHERE account_id IS NULL
        ORDER BY agent_id
    """)

    with db.engine.connect() as conn:
        global_configs = [dict(row._mapping) for row in conn.execute(global_configs_query)]

    return render_template(
        "admin/agent_configure_list.html",
        global_configs=global_configs,
        accounts=accounts
    )


@agent_config_bp.route("/configure/global/<agent_id>", methods=["GET", "POST"])
@login_required
@require_admin
def configure_global(agent_id: str):
    """Configure global defaults for an agent."""

    if request.method == "POST":
        # Update configuration
        enabled = request.form.get("enabled") == "on"
        auto_execute_threshold = float(request.form.get("auto_execute_threshold", 0.95))
        custom_prompt = request.form.get("custom_prompt", "").strip() or None

        # Parse risk overrides
        risk_overrides = {}
        for key, value in request.form.items():
            if key.startswith("risk_"):
                decision_type = key.replace("risk_", "")
                risk_overrides[decision_type] = value

        # Parse business rules
        business_rules = []
        rule_count = int(request.form.get("rule_count", 0))
        for i in range(rule_count):
            condition = request.form.get(f"rule_{i}_condition", "").strip()
            action = request.form.get(f"rule_{i}_action", "").strip()
            if condition and action:
                business_rules.append({"if": condition, "then": action})

        # Upsert configuration
        upsert_query = text("""
            INSERT INTO agent_configurations
            (account_id, agent_id, agent_type, enabled, auto_execute_threshold, custom_prompt, risk_overrides, business_rules, updated_at)
            VALUES (NULL, :agent_id, :agent_type, :enabled, :threshold, :prompt, :risk_json, :rules_json, NOW())
            ON DUPLICATE KEY UPDATE
                enabled = :enabled,
                auto_execute_threshold = :threshold,
                custom_prompt = :prompt,
                risk_overrides = :risk_json,
                business_rules = :rules_json,
                updated_at = NOW()
        """)

        with db.engine.begin() as conn:
            conn.execute(upsert_query, {
                "agent_id": agent_id,
                "agent_type": request.form.get("agent_type", agent_id),
                "enabled": enabled,
                "threshold": auto_execute_threshold,
                "prompt": custom_prompt,
                "risk_json": json.dumps(risk_overrides) if risk_overrides else None,
                "rules_json": json.dumps(business_rules) if business_rules else None
            })

        flash(f"Global configuration for {agent_id} updated successfully!", "success")
        return redirect(url_for("agent_config_bp.configure_list"))

    # GET request - fetch current configuration
    config_query = text("""
        SELECT * FROM agent_configurations
        WHERE account_id IS NULL AND agent_id = :agent_id
    """)

    with db.engine.connect() as conn:
        result = conn.execute(config_query, {"agent_id": agent_id})
        row = result.first()
        config = dict(row._mapping) if row else None

    # Get agent metadata
    from app.agents import (
        StrategicDirectorAgent, CampaignManagerAgent, BudgetGuardianAgent,
        QualityScoreAgent, KeywordOptimizerAgent, NegativeKeywordAgent, AdCopyAgent
    )

    agent_metadata = {
        "strategic_director": {
            "class": StrategicDirectorAgent,
            "name": "Strategic Director",
            "description": "Your CMO for Google Ads - budget allocation, campaign scaling, and strategic pausing",
            "decision_types": ["reallocate_budget", "scale_campaign", "pause_campaign"]
        },
        "campaign_manager": {
            "class": CampaignManagerAgent,
            "name": "Campaign Manager",
            "description": "24/7 monitoring for CPL spikes, conversion drops, and performance anomalies",
            "decision_types": ["adjust_campaign_bids", "emergency_notification"]
        },
        "budget_guardian": {
            "class": BudgetGuardianAgent,
            "name": "Budget Guardian",
            "description": "Protects against runaway spend and budget overruns",
            "decision_types": ["adjust_daily_budget", "emergency_pause"]
        },
        "quality_score_agent": {
            "class": QualityScoreAgent,
            "name": "Quality Score Doctor",
            "description": "Diagnoses and fixes low Quality Scores to reduce CPCs",
            "decision_types": ["improve_quality_score"]
        },
        "keyword_optimizer": {
            "class": KeywordOptimizerAgent,
            "name": "Keyword Optimizer",
            "description": "Optimizes keyword bids and pauses wasteful keywords",
            "decision_types": ["pause_keyword", "adjust_keyword_bid", "add_keyword"]
        },
        "negative_keyword_agent": {
            "class": NegativeKeywordAgent,
            "name": "Negative Keyword Agent",
            "description": "Automatically blocks wasteful search terms",
            "decision_types": ["add_negative_keyword"]
        },
        "ad_copy_agent": {
            "class": AdCopyAgent,
            "name": "Ad Copy Scientist",
            "description": "A/B tests ad variations and pauses underperformers",
            "decision_types": ["create_ad_variations", "pause_ad"]
        }
    }

    metadata = agent_metadata.get(agent_id, {
        "name": agent_id,
        "description": "Agent configuration",
        "decision_types": []
    })

    return render_template(
        "admin/agent_configure_form.html",
        config=config,
        agent_id=agent_id,
        metadata=metadata,
        is_global=True,
        account=None
    )


@agent_config_bp.route("/configure/account/<int:account_id>/<agent_id>", methods=["GET", "POST"])
@login_required
@require_admin
def configure_account(account_id: int, agent_id: str):
    """Configure agent for a specific account (overrides global defaults)."""
    from app.models import Account

    account = Account.query.get_or_404(account_id)

    if request.method == "POST":
        # Update configuration (same logic as global but with account_id)
        enabled = request.form.get("enabled") == "on"
        auto_execute_threshold = float(request.form.get("auto_execute_threshold", 0.95))
        custom_prompt = request.form.get("custom_prompt", "").strip() or None

        # Parse risk overrides
        risk_overrides = {}
        for key, value in request.form.items():
            if key.startswith("risk_"):
                decision_type = key.replace("risk_", "")
                risk_overrides[decision_type] = value

        # Parse business rules
        business_rules = []
        rule_count = int(request.form.get("rule_count", 0))
        for i in range(rule_count):
            condition = request.form.get(f"rule_{i}_condition", "").strip()
            action = request.form.get(f"rule_{i}_action", "").strip()
            if condition and action:
                business_rules.append({"if": condition, "then": action})

        # Upsert configuration
        upsert_query = text("""
            INSERT INTO agent_configurations
            (account_id, agent_id, agent_type, enabled, auto_execute_threshold, custom_prompt, risk_overrides, business_rules, updated_at, created_by)
            VALUES (:account_id, :agent_id, :agent_type, :enabled, :threshold, :prompt, :risk_json, :rules_json, NOW(), :user_id)
            ON DUPLICATE KEY UPDATE
                enabled = :enabled,
                auto_execute_threshold = :threshold,
                custom_prompt = :prompt,
                risk_overrides = :risk_json,
                business_rules = :rules_json,
                updated_at = NOW()
        """)

        with db.engine.begin() as conn:
            conn.execute(upsert_query, {
                "account_id": account_id,
                "agent_id": agent_id,
                "agent_type": request.form.get("agent_type", agent_id),
                "enabled": enabled,
                "threshold": auto_execute_threshold,
                "prompt": custom_prompt,
                "risk_json": json.dumps(risk_overrides) if risk_overrides else None,
                "rules_json": json.dumps(business_rules) if business_rules else None,
                "user_id": g.user.id if hasattr(g, "user") else None
            })

        flash(f"Configuration for {agent_id} in account '{account.name}' updated successfully!", "success")
        return redirect(url_for("agent_config_bp.configure_list"))

    # GET request - fetch current configuration
    config_query = text("""
        SELECT * FROM agent_configurations
        WHERE account_id = :account_id AND agent_id = :agent_id
    """)

    with db.engine.connect() as conn:
        result = conn.execute(config_query, {"account_id": account_id, "agent_id": agent_id})
        row = result.first()
        config = dict(row._mapping) if row else None

    # If no account-specific config, get global defaults
    if not config:
        global_query = text("""
            SELECT * FROM agent_configurations
            WHERE account_id IS NULL AND agent_id = :agent_id
        """)

        with db.engine.connect() as conn:
            result = conn.execute(global_query, {"agent_id": agent_id})
            row = result.first()
            config = dict(row._mapping) if row else None

    return render_template(
        "admin/agent_configure_form.html",
        config=config,
        agent_id=agent_id,
        metadata={"name": agent_id, "description": "Agent configuration", "decision_types": []},
        is_global=False,
        account=account
    )


@agent_config_bp.route("/configure/<int:config_id>/delete", methods=["POST"])
@login_required
@require_admin
def configure_delete(config_id: int):
    """Delete an agent configuration (revert to global defaults)."""

    delete_query = text("""
        DELETE FROM agent_configurations
        WHERE id = :config_id
    """)

    with db.engine.begin() as conn:
        conn.execute(delete_query, {"config_id": config_id})

    flash("Configuration deleted. Using global defaults.", "success")
    return redirect(url_for("agent_config_bp.configure_list"))


# ============================================================================
# Business Rules Engine Helpers
# ============================================================================

def evaluate_business_rule(rule: dict, context: dict) -> bool:
    """
    Evaluate a business rule against a context.

    Rule format: {"if": "campaign_spend > 1000 AND roas < 2.0", "then": "require_approval"}
    Context: {"campaign_spend": 1500, "roas": 1.8, ...}

    Returns: True if rule condition matches
    """
    condition = rule.get("if", "")

    if not condition:
        return False

    try:
        # Simple expression evaluation (DANGER: eval is unsafe in production!)
        # TODO: Replace with safe expression evaluator (e.g., simpleeval library)
        # For now, using restrictive whitelist

        # Allow only safe variable names and operators
        import re
        allowed_pattern = r'^[\w\s\.\(\)<>=!&|+\-*/]+$'

        if not re.match(allowed_pattern, condition):
            return False

        # Replace context variables
        for key, value in context.items():
            condition = condition.replace(key, str(value))

        # Evaluate (UNSAFE - replace with safe evaluator)
        result = eval(condition)
        return bool(result)

    except Exception:
        # If evaluation fails, rule doesn't match
        return False


def get_agent_configuration(agent_id: str, account_id: int = None) -> dict:
    """
    Get agent configuration with account override fallback to global.

    Returns dict with: enabled, auto_execute_threshold, custom_prompt, risk_overrides, business_rules
    """
    # Try account-specific first
    if account_id:
        query = text("""
            SELECT * FROM agent_configurations
            WHERE account_id = :account_id AND agent_id = :agent_id
        """)

        with db.engine.connect() as conn:
            result = conn.execute(query, {"account_id": account_id, "agent_id": agent_id})
            row = result.first()

            if row:
                config = dict(row._mapping)
                # Parse JSON fields
                if config.get('risk_overrides'):
                    config['risk_overrides'] = json.loads(config['risk_overrides']) if isinstance(config['risk_overrides'], str) else config['risk_overrides']
                if config.get('business_rules'):
                    config['business_rules'] = json.loads(config['business_rules']) if isinstance(config['business_rules'], str) else config['business_rules']

                return config

    # Fallback to global
    query = text("""
        SELECT * FROM agent_configurations
        WHERE account_id IS NULL AND agent_id = :agent_id
    """)

    with db.engine.connect() as conn:
        result = conn.execute(query, {"agent_id": agent_id})
        row = result.first()

        if row:
            config = dict(row._mapping)
            # Parse JSON fields
            if config.get('risk_overrides'):
                config['risk_overrides'] = json.loads(config['risk_overrides']) if isinstance(config['risk_overrides'], str) else config['risk_overrides']
            if config.get('business_rules'):
                config['business_rules'] = json.loads(config['business_rules']) if isinstance(config['business_rules'], str) else config['business_rules']

            return config

    # No configuration found - return defaults
    return {
        "enabled": True,
        "auto_execute_threshold": 0.80,
        "custom_prompt": None,
        "risk_overrides": {},
        "business_rules": []
    }
