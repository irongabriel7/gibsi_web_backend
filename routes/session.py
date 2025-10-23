from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request
from flask import request, jsonify
from functools import wraps
from datetime import datetime, timedelta
from mongo_client import non_flask_db as db

INACTIVITY_MINUTES = 20

def require_active_session(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        # Short-circuit for OPTIONS requests (CORS preflight)
        if request.method == "OPTIONS":
            return '', 200
        try:
            verify_jwt_in_request()
        except Exception:
            return jsonify({"error": "Missing or invalid token."}), 401

        gid = get_jwt_identity()
        try:
            gid = int(gid)
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid user ID format"}), 400

        user = db["user"].find_one({"gid": gid})
        if not user or not user.get("logged_in", False):
            return jsonify({"error": "User not logged in."}), 403

        last_active = user.get("last_active")
        now = datetime.utcnow()
        if last_active is None or now - last_active > timedelta(minutes=INACTIVITY_MINUTES):
            # Update user's logged_in status
            db["user"].update_one({"gid": gid}, {"$set": {"logged_in": False}})
            # Find the latest login document for this user
            login_doc = db["login"].find_one({"gid": int(gid)}, sort=[("login_time", -1)])
            if login_doc and login_doc.get("login_time"):
                session_seconds = (now - login_doc["login_time"]).total_seconds()
                db["login"].update_one(
                    {"_id": login_doc["_id"]},
                    {"$set": {
                        "logout_time": now,
                        "session_time_seconds": session_seconds
                    }}
                )
            return jsonify({"error": "Session expired due to inactivity. Please login again."}), 401

        # Update last_active time
        db["user"].update_one({"gid": gid}, {"$set": {"last_active": now}})
        return fn(*args, **kwargs)
    return wrapper