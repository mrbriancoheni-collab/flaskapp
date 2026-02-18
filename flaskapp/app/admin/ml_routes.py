# app/admin/ml_routes.py
"""
ML System Monitoring Admin Routes

Provides visibility into:
- Model training status across all accounts
- Model performance metrics
- Recent predictions
- Training history
"""
from __future__ import annotations
from datetime import datetime, timedelta
import os
import logging

from flask import Blueprint, render_template, request, flash, redirect, url_for, current_app
from sqlalchemy import text, desc

from app.extensions import db
from app.auth.session_helpers import login_required
from app.auth.decorators import require_admin_cloaked as require_admin

logger = logging.getLogger(__name__)

ml_admin_bp = Blueprint("ml_admin_bp", __name__, url_prefix="/admin/ml")


@ml_admin_bp.route("/")
@login_required
@require_admin
def dashboard():
    """ML System Dashboard - Overview of all models and training status."""

    # Ensure ML tables exist
    try:
        from app.ml import ensure_tables
        ensure_tables()
    except Exception as e:
        logger.warning(f"Could not ensure ML tables: {e}")

    # Get all trained models from ml_models table
    models_data = []
    try:
        rows = db.session.execute(text("""
            SELECT
                m.id,
                m.account_id,
                m.model_name,
                m.model_type,
                m.target_metric,
                m.training_date,
                m.accuracy_score,
                m.mae,
                m.rmse,
                m.r2_score,
                m.is_active,
                m.feature_count,
                m.training_samples,
                a.name as account_name
            FROM ml_models m
            LEFT JOIN accounts a ON m.account_id = a.id
            ORDER BY m.training_date DESC
            LIMIT 100
        """)).fetchall()

        for row in rows:
            models_data.append({
                'id': row[0],
                'account_id': row[1],
                'model_name': row[2],
                'model_type': row[3],
                'target_metric': row[4],
                'training_date': row[5],
                'accuracy_score': row[6],
                'mae': row[7],
                'rmse': row[8],
                'r2_score': row[9],
                'is_active': row[10],
                'feature_count': row[11],
                'training_samples': row[12],
                'account_name': row[13] or f"Account #{row[1]}",
            })
    except Exception as e:
        logger.warning(f"Could not fetch ml_models: {e}")

    # Get model counts by type
    model_counts = {}
    for model in models_data:
        name = model['model_name']
        if name not in model_counts:
            model_counts[name] = {'count': 0, 'accounts': set()}
        model_counts[name]['count'] += 1
        model_counts[name]['accounts'].add(model['account_id'])

    # Get recent predictions from ml_predictions table
    predictions = []
    try:
        rows = db.session.execute(text("""
            SELECT
                p.id,
                p.account_id,
                p.model_name,
                p.prediction_type,
                p.input_data,
                p.prediction_result,
                p.confidence_score,
                p.created_at,
                a.name as account_name
            FROM ml_predictions p
            LEFT JOIN accounts a ON p.account_id = a.id
            ORDER BY p.created_at DESC
            LIMIT 50
        """)).fetchall()

        for row in rows:
            predictions.append({
                'id': row[0],
                'account_id': row[1],
                'model_name': row[2],
                'prediction_type': row[3],
                'input_data': row[4],
                'prediction_result': row[5],
                'confidence_score': row[6],
                'created_at': row[7],
                'account_name': row[8] or f"Account #{row[1]}",
            })
    except Exception as e:
        logger.warning(f"Could not fetch ml_predictions: {e}")

    # Get accounts with Google Ads connections for training eligibility
    eligible_accounts = []
    try:
        rows = db.session.execute(text("""
            SELECT DISTINCT
                a.id,
                a.name,
                a.google_ads_customer_id,
                (SELECT COUNT(*) FROM ml_models WHERE account_id = a.id) as model_count,
                (SELECT MAX(training_date) FROM ml_models WHERE account_id = a.id) as last_trained
            FROM accounts a
            JOIN google_oauth_tokens got ON a.id = got.account_id
            WHERE got.product = 'ads'
              AND got.refresh_token IS NOT NULL
              AND a.google_ads_customer_id IS NOT NULL
            ORDER BY a.name
        """)).fetchall()

        for row in rows:
            eligible_accounts.append({
                'id': row[0],
                'name': row[1] or f"Account #{row[0]}",
                'customer_id': row[2],
                'model_count': row[3] or 0,
                'last_trained': row[4],
            })
    except Exception as e:
        logger.warning(f"Could not fetch eligible accounts: {e}")

    # Check for trained model files on disk
    model_files = {}
    models_dir = os.path.join(current_app.root_path, 'ml', 'trained_models')
    if os.path.exists(models_dir):
        for filename in os.listdir(models_dir):
            if filename.endswith('.pkl'):
                filepath = os.path.join(models_dir, filename)
                model_files[filename] = {
                    'size': os.path.getsize(filepath),
                    'modified': datetime.fromtimestamp(os.path.getmtime(filepath)),
                }

    # Model type descriptions
    model_descriptions = {
        'budget_roi': {
            'name': 'Budget ROI Predictor',
            'agent': 'Strategic Director',
            'description': 'Predicts ROAS at different budget levels',
            'metric': 'R² Score',
        },
        'anomaly_detector': {
            'name': 'Anomaly Detector',
            'agent': 'Campaign Manager',
            'description': 'Detects performance anomalies using Isolation Forest',
            'metric': 'Training Samples',
        },
        'spend_forecast': {
            'name': 'Spend Forecaster',
            'agent': 'Budget Guardian',
            'description': 'Forecasts daily spend and budget pacing',
            'metric': 'MAE',
        },
        'quality_score': {
            'name': 'Quality Score Predictor',
            'agent': 'Quality Score Agent',
            'description': 'Predicts QS components for optimization',
            'metric': 'Accuracy',
        },
        'cpa_predictor': {
            'name': 'CPA Predictor',
            'agent': 'Keyword Optimizer',
            'description': 'Predicts CPA at different bid levels',
            'metric': 'MAE',
        },
        'waste_classifier': {
            'name': 'Waste Classifier',
            'agent': 'Negative Keyword Agent',
            'description': 'Classifies search terms as wasteful or valuable',
            'metric': 'F1 Score',
        },
        'ctr_predictor': {
            'name': 'CTR Predictor',
            'agent': 'Ad Copy Agent',
            'description': 'Predicts expected CTR for ad variations',
            'metric': 'R² Score',
        },
    }

    # Calculate summary stats
    total_models = len(models_data)
    unique_accounts = len(set(m['account_id'] for m in models_data))
    recent_training = sum(1 for m in models_data
                         if m['training_date'] and
                         m['training_date'] > datetime.utcnow() - timedelta(days=7))

    return render_template(
        "admin/ml/dashboard.html",
        models_data=models_data,
        model_counts=model_counts,
        predictions=predictions,
        eligible_accounts=eligible_accounts,
        model_files=model_files,
        model_descriptions=model_descriptions,
        total_models=total_models,
        unique_accounts=unique_accounts,
        recent_training=recent_training,
    )


@ml_admin_bp.route("/train", methods=["POST"])
@login_required
@require_admin
def train_models():
    """Trigger ML model training for a specific account or all accounts."""
    account_id = request.form.get('account_id')
    model_type = request.form.get('model_type')

    try:
        from app.ml.trainer import MLTrainer, train_all_accounts

        if account_id:
            account_id = int(account_id)
            trainer = MLTrainer(account_id)

            if model_type and model_type != 'all':
                # Train specific model
                method_name = f"train_{model_type}"
                if hasattr(trainer, method_name):
                    result = getattr(trainer, method_name)()
                    if result:
                        flash(f"Successfully trained {model_type} model for account {account_id}", "success")
                    else:
                        flash(f"Training {model_type} failed - insufficient data", "warning")
                else:
                    flash(f"Unknown model type: {model_type}", "error")
            else:
                # Train all models for account
                results = trainer.train_all()
                flash(f"Trained {results['trained']} models for account {account_id} ({results['skipped']} skipped, {results['failed']} failed)", "success")
        else:
            # Train all accounts
            results = train_all_accounts()
            flash(f"Training complete: {results['accounts_processed']} accounts, {results['models_trained']} models trained", "success")

    except ImportError as e:
        flash(f"ML module not available: {e}", "error")
    except Exception as e:
        logger.exception(f"ML training error: {e}")
        flash(f"Training error: {e}", "error")

    return redirect(url_for('ml_admin_bp.dashboard'))


@ml_admin_bp.route("/account/<int:account_id>")
@login_required
@require_admin
def account_detail(account_id):
    """Detailed ML status for a specific account."""

    # Get account info
    account = None
    try:
        row = db.session.execute(text("""
            SELECT id, name, google_ads_customer_id
            FROM accounts
            WHERE id = :aid
        """), {'aid': account_id}).fetchone()
        if row:
            account = {'id': row[0], 'name': row[1], 'customer_id': row[2]}
    except Exception as e:
        logger.warning(f"Could not fetch account: {e}")

    if not account:
        flash("Account not found", "error")
        return redirect(url_for('ml_admin_bp.dashboard'))

    # Get all models for this account
    models = []
    try:
        rows = db.session.execute(text("""
            SELECT
                id, model_name, model_type, target_metric,
                training_date, accuracy_score, mae, rmse, r2_score,
                is_active, feature_count, training_samples
            FROM ml_models
            WHERE account_id = :aid
            ORDER BY training_date DESC
        """), {'aid': account_id}).fetchall()

        for row in rows:
            models.append({
                'id': row[0],
                'model_name': row[1],
                'model_type': row[2],
                'target_metric': row[3],
                'training_date': row[4],
                'accuracy_score': row[5],
                'mae': row[6],
                'rmse': row[7],
                'r2_score': row[8],
                'is_active': row[9],
                'feature_count': row[10],
                'training_samples': row[11],
            })
    except Exception as e:
        logger.warning(f"Could not fetch models: {e}")

    # Get recent predictions for this account
    predictions = []
    try:
        rows = db.session.execute(text("""
            SELECT
                id, model_name, prediction_type, input_data,
                prediction_result, confidence_score, created_at
            FROM ml_predictions
            WHERE account_id = :aid
            ORDER BY created_at DESC
            LIMIT 100
        """), {'aid': account_id}).fetchall()

        for row in rows:
            predictions.append({
                'id': row[0],
                'model_name': row[1],
                'prediction_type': row[2],
                'input_data': row[3],
                'prediction_result': row[4],
                'confidence_score': row[5],
                'created_at': row[6],
            })
    except Exception as e:
        logger.warning(f"Could not fetch predictions: {e}")

    # Get data availability stats
    data_stats = {}
    try:
        # Campaign performance
        row = db.session.execute(text("""
            SELECT COUNT(*), MIN(date), MAX(date)
            FROM campaign_performance_history
            WHERE account_id = :aid
        """), {'aid': account_id}).fetchone()
        data_stats['campaign_performance'] = {
            'count': row[0] or 0,
            'start': row[1],
            'end': row[2],
        }

        # Daily stats
        row = db.session.execute(text("""
            SELECT COUNT(*), MIN(date), MAX(date)
            FROM gads_stats_daily
            WHERE account_id = :aid
        """), {'aid': account_id}).fetchone()
        data_stats['daily_stats'] = {
            'count': row[0] or 0,
            'start': row[1],
            'end': row[2],
        }

        # Search terms
        row = db.session.execute(text("""
            SELECT COUNT(*)
            FROM search_terms
            WHERE account_id = :aid
        """), {'aid': account_id}).fetchone()
        data_stats['search_terms'] = {'count': row[0] or 0}

    except Exception as e:
        logger.warning(f"Could not fetch data stats: {e}")

    return render_template(
        "admin/ml/account_detail.html",
        account=account,
        models=models,
        predictions=predictions,
        data_stats=data_stats,
    )
