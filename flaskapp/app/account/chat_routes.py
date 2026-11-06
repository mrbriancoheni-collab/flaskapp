import uuid
from flask import request, jsonify, render_template, session
from app.account import account_bp, login_required, current_account_id


@account_bp.route("/chat", methods=["GET"])
@login_required
def chat():
    return render_template("account/chat.html")


@account_bp.route("/chat/send", methods=["POST"])
@login_required
def chat_send():
    data = request.get_json(silent=True) or {}
    message = str(data.get("message") or "").strip()
    if not message:
        return jsonify({"ok": False, "error": "message required"}), 400
    if len(message) > 2000:
        return jsonify({"ok": False, "error": "message too long"}), 400

    conversation_id = str(data.get("conversation_id") or session.get("chat_conv_id") or "")
    if not conversation_id:
        conversation_id = str(uuid.uuid4())
    session["chat_conv_id"] = conversation_id

    history = data.get("history")
    if not isinstance(history, list):
        history = []
    history = history[-10:]  # keep last 10 turns for context window

    aid = current_account_id()
    uid = session.get("user_id") or 0

    try:
        from app.services.chat_service import get_chat_response
        result = get_chat_response(aid, uid, conversation_id, message, history)
        return jsonify({
            "ok": True,
            "reply": result["reply"],
            "conversation_id": conversation_id,
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": "AI unavailable — try again shortly"}), 503


@account_bp.route("/chat/new", methods=["POST"])
@login_required
def chat_new():
    session.pop("chat_conv_id", None)
    return jsonify({"ok": True, "conversation_id": str(uuid.uuid4())})
