import os
from flask import Blueprint, request, jsonify, send_file
from mongo_client import non_flask_db as db
import firebase_admin
from firebase_admin import credentials, messaging
from pymongo import ASCENDING
from flask_jwt_extended import jwt_required, get_jwt_identity, verify_jwt_in_request, JWTManager
from functools import wraps

notifier = Blueprint("notifier", __name__)

# Firebase Admin
# Put your service account JSON path in env FIREBASE_SERVICE_ACCOUNT
cred_path = os.getenv("GIBSI_JSON_FILE", "/shared/gibsi-6de19-firebase-adminsdk-fbsvc-5929d07e4f.json")
if not firebase_admin._apps:
    cred = credentials.Certificate(cred_path)
    firebase_admin.initialize_app(cred)
    
def init_notifier_jwt(app):
    app.config['JWT_SECRET_KEY']  = os.getenv("JWT_SECRET_KEY")
    JWTManager(app)

def auth_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            print("=== JWT DEBUG ===")
            print("Headers:", dict(request.headers))
            verify_jwt_in_request()
            user = get_jwt_identity()
            print(f"JWT verified! User: {user}")
            print("==================")
            return f(*args, **kwargs)
        except Exception as e:
            print(f"JWT failed: {e}")
            return jsonify({"error": "Authentication required"}), 401
    return decorated_function

@notifier.route("/api/register", methods=["POST"])
@auth_required
def register_token():
    data = request.get_json(force=True) or {}
    token = data.get("token")
    gid = data.get("gid")
    
    print("Token registration data:")
    print(f"Token: {token[:20]}..." if token else "No token")
    print(f"GID: {gid}")
    
    if not token:
        return jsonify({"error": "token required"}), 400
    
    if not gid:
        return jsonify({"error": "gid required"}), 400
    
    # Get the authenticated user's GID from JWT
    current_user_gid = get_jwt_identity()
    
    # Verify that the user is registering their own token
    if str(current_user_gid) != str(gid):
        return jsonify({"error": "Invalid user"}), 403
    
    try:
        # Update user collection with device token
        user_collection = db["user"]
        result = user_collection.update_one(
            {"gid": int(gid)}, 
            {"$set": {"device_token": token}}
        )
        
        if result.matched_count == 0:
            return jsonify({"error": "User not found"}), 404
        
        print(f"Token registered successfully for user GID: {gid}")
        return jsonify({"status": "ok", "message": "Token registered successfully"}), 200
        
    except Exception as e:
        print(f"Error registering token: {e}")
        return jsonify({"error": "Internal server error"}), 500

@notifier.route("/api/alerts/broadcast", methods=["POST"])
def broadcast():
    data = request.get_json(force=True) or {}
    title = data.get("title") or "GIBSI Alert"
    message = data.get("message") or ""

    # Fetch device tokens from user collection
    user_collection = db["user"]
    users_with_tokens = user_collection.find(
        {"device_token": {"$exists": True, "$ne": None, "$ne": ""}},
        {"_id": 0, "device_token": 1, "gid": 1}
    )
    
    device_tokens = [doc["device_token"] for doc in users_with_tokens if doc.get("device_token")]
    
    if not device_tokens:
        return jsonify({"sent": 0, "detail": "no tokens"}), 200

    print(f"Broadcasting to {len(device_tokens)} devices")
    print(f"Title: {title}")
    print(f"Message: {message}")

    # Send in chunks (FCM recommends batches of up to 500)
    chunk_size = 500
    sent = 0
    errors = []

    for i in range(0, len(device_tokens), chunk_size):
        batch = device_tokens[i:i+chunk_size]
        notif = messaging.Notification(title=title, body=message)
        android_cfg = messaging.AndroidConfig(priority="high")
        data_payload = {"title": title, "message": message}

        try:
            # Create a single MulticastMessage object
            multicast_message = messaging.MulticastMessage(
                tokens=batch,
                notification=notif,
                android=android_cfg,
                data=data_payload
            )

            # Use messaging.send_each_for_multicast()
            resp = messaging.send_each_for_multicast(multicast_message)
            sent += resp.success_count

            # Clean up invalid tokens
            invalid = []
            for idx, res in enumerate(resp.responses):
                if not res.success:
                    code = getattr(res.exception, "code", None)
                    if code in ("registration-token-not-registered", "invalid-argument"):
                        invalid.append(batch[idx])
            
            if invalid:
                print(f"Removing {len(invalid)} invalid tokens")
                # Remove invalid tokens from user collection
                user_collection.update_many(
                    {"device_token": {"$in": invalid}},
                    {"$unset": {"device_token": ""}}
                )
                
        except Exception as e:
            print(f"Error sending batch: {e}")
            errors.append(str(e))

    print(f"Broadcast completed: {sent} sent, {len(errors)} errors")
    return jsonify({"sent": sent, "errors": errors})

@notifier.route("/api/alerts/send_to_user/<int:gid>", methods=["POST"])
@auth_required
def send_to_user(gid):
    """Send notification to a specific user by GID"""
    data = request.get_json(force=True) or {}
    title = data.get("title") or "GIBSI Alert"
    message = data.get("message") or ""
    
    if not message:
        return jsonify({"error": "message required"}), 400
    
    # Get user's device token
    user_collection = db["user"]
    user = user_collection.find_one({"gid": gid}, {"device_token": 1})
    
    if not user or not user.get("device_token"):
        return jsonify({"error": "User not found or no device token"}), 404
    
    device_token = user["device_token"]
    
    try:
        notif = messaging.Notification(title=title, body=message)
        android_cfg = messaging.AndroidConfig(priority="high")
        data_payload = {"title": title, "message": message}
        
        message_obj = messaging.Message(
            notification=notif,
            android=android_cfg,
            data=data_payload,
            token=device_token
        )
        
        resp = messaging.send(message_obj)
        print(f"Notification sent to user {gid}: {resp}")
        
        return jsonify({"status": "ok", "message_id": resp})
        
    except Exception as e:
        print(f"Error sending notification to user {gid}: {e}")
        
        # Check if token is invalid and remove it
        if "registration-token-not-registered" in str(e) or "invalid-argument" in str(e):
            user_collection.update_one(
                {"gid": gid},
                {"$unset": {"device_token": ""}}
            )
            print(f"Removed invalid token for user {gid}")
        
        return jsonify({"error": "Failed to send notification"}), 500

@notifier.route("/api/tokens/status", methods=["GET"])
@auth_required
def get_token_status():
    """Get token registration status for authenticated user"""
    current_user_gid = get_jwt_identity()
    
    user_collection = db["user"]
    user = user_collection.find_one({"gid": int(current_user_gid)}, {"device_token": 1})
    
    if not user:
        return jsonify({"error": "User not found"}), 404
    
    has_token = bool(user.get("device_token"))
    
    return jsonify({
        "has_token": has_token,
        "token_preview": user.get("device_token", "")[:20] + "..." if has_token else None
    })

@notifier.route("/api/tokens/remove", methods=["POST"])
@auth_required
def remove_token():
    """Remove device token for authenticated user"""
    current_user_gid = get_jwt_identity()
    
    user_collection = db["user"]
    result = user_collection.update_one(
        {"gid": int(current_user_gid)},
        {"$unset": {"device_token": ""}}
    )
    
    if result.matched_count == 0:
        return jsonify({"error": "User not found"}), 404
    
    return jsonify({"status": "ok", "message": "Token removed successfully"})

@notifier.route("/api/register/test", methods=["GET"])
def test_endpoint():
    """Simple test endpoint to verify the blueprint is registered"""
    return jsonify({"status": "ok", "message": "Notifier blueprint is working!"}), 200

@notifier.route("/api/alerts/active_users", methods=["GET"])
@auth_required  # Optionally require authentication for privacy
def get_active_users():
    # Get users with a valid device_token
    user_collection = db["user"]
    users = user_collection.find(
        {"device_token": {"$exists": True, "$ne": None, "$ne": ""}},
        {"gid": 1, "username": 1, "_id": 0}
    )
    # Build list for dropdown
    results = []
    for u in users:
        if u.get("username") and u.get("gid"):
            results.append({"gid": u["gid"], "username": u["username"]})
    return jsonify(results)
