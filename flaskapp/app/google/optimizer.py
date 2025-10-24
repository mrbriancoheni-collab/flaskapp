from flask import Blueprint, request, jsonify
from utils.db import SessionLocal
from models import OptimizerRecommendation, OptimizerAction
import json

optimizer_bp = Blueprint("optimizer", __name__)

@optimizer_bp.get("/optimizer")
def get_recommendations():
    # Placeholder: return sample recommendation list
    demo = [
        {
          "scope_type":"campaign","scope_id":1,
          "category":"wasted_spend",
          "title":"Add negatives for 'free' and 'jobs' terms",
          "details":"N-gram analysis suggests blocking 'free', 'job', 'DIY'",
          "expected_impact":"Save ~$425/mo",
          "severity":2,
          "suggested_action_json": {"negatives":[{"text":"free","match_type":"PHRASE"}]}
        }
    ]
    return jsonify(demo)

@optimizer_bp.post("/optimizer/apply")
def apply_optimizer_actions():
    payload = request.get_json(force=True)
    # Expect payload: {"changes": [ {...}, {...} ]}
    # This is a stub writing changeset to DB
    db = SessionLocal()
    try:
        rec_id = payload.get("recommendation_id", 0)
        action = OptimizerAction(
            recommendation_id = rec_id,
            change_set_json = json.dumps(payload),
            status = "pending"
        )
        db.add(action)
        db.commit()
        return jsonify({"status":"queued", "action_id": action.id})
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 400
    finally:
        db.close()
