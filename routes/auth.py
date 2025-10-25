#auth.py
import sys
import os
from flask import Blueprint, request, jsonify
from flask_jwt_extended import (
    JWTManager, create_access_token, create_refresh_token,
    jwt_required, get_jwt_identity
)
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import pytz
from mongo_client import non_flask_db as db  # direct pymongo Database
# Add parent directory (Backend) to Python path
from logger_config import setup_gibsi_logging
auth_logger = setup_gibsi_logging()
from routes.session import require_active_session

JWT_SECRET_KEY = "b71f276f0c473f1074c5f454f259afc494e888f1031054d36f765d038d8376d5" #WHILE PRODUCTION NEED TO BE REMOVED
#JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")

auth_api = Blueprint('auth_api', __name__)

utc_tz = pytz.UTC
ist_tz = pytz.timezone('Asia/Kolkata')

def init_auth(app):
    app.config["JWT_SECRET_KEY"] = JWT_SECRET_KEY
    app.config["SECRET_KEY"] = JWT_SECRET_KEY  # optional but safe
    JWTManager(app)

    # Create unique indexes
    db["user"].create_index("gid", unique=True)
    db["user"].create_index("email", unique=True)

    # Initialize counter document for gid if not exists
    if not db["counters"].find_one({"_id": "gid"}):
        db["counters"].insert_one({"_id": "gid", "seq": 0})

    app.register_blueprint(auth_api)

def get_next_gid():
    """Atomic GID generator using MongoDB find_one_and_update."""
    counter = db["counters"].find_one_and_update(
        {"_id": "gid"},
        {"$inc": {"seq": 1}},
        return_document=True
    )
    return counter["seq"]

# ---------------- REGISTER ----------------
@auth_api.route('/api/user_register', methods=['POST'])
def register():
    auth_logger.info("Registration attempt started")
    data = request.get_json(silent=True) or {}
    username = data.get('username')
    email = data.get('email')
    password = data.get('password')
    passcode = data.get('passcode')

    if not all([username, email, password, passcode]):
        auth_logger.warning(f"Registration failed - missing fields for email={email}")
        return jsonify({'error': 'All fields are required'}), 400

    if not passcode.isdigit() or len(passcode) != 4:
        auth_logger.warning(f"Registration failed - invalid passcode format for email={email}")
        return jsonify({'error': 'Passcode must be a 4-digit number'}), 400

    # Check for duplicate username or email in a single query
    existing_user = db["user"].find_one({'$or': [{'email': email}, {'username': username}]})
    if existing_user:
        duplicate_field = "email" if existing_user.get('email') == email else "username"
        auth_logger.warning(f"Registration failed - {duplicate_field} already registered: {email if duplicate_field == 'email' else username}")
        return jsonify({'error': f'{duplicate_field.capitalize()} already registered'}), 409

    usertype = data.get('usertype', 'normal')
    if usertype not in ['admin', 'normal']:
        auth_logger.info(f"Invalid usertype provided ({usertype}), defaulting to 'normal'")
        usertype = 'normal'

    password_hash = generate_password_hash(password)
    passcode_hash = generate_password_hash(passcode)

    user = {
        'gid': get_next_gid(),
        'username': username,
        'email': email,
        'password_hash': password_hash,
        'passcode_hash': passcode_hash,
        'created_at': datetime.utcnow(),
        'last_login': None,
        'Active': False,
        'logged_in': False,
        'usertype': usertype
    }
    db["user"].insert_one(user)
    auth_logger.info(f"User registered successfully - GID={user['gid']} Email={email}")
    return jsonify({'message': 'Registration successful', 'gid': user['gid']}), 201

# ---------------- LOGIN ----------------
@auth_api.route('/api/login', methods=['POST'])
def login():
    auth_logger.info("Login attempt started")
    data = request.get_json(silent=True) or {}
    email = data.get('email')
    password = data.get('password')
    passcode = data.get('passcode')

    if not (email) or (not password and not passcode):
        auth_logger.warning("Login failed - missing credentials")
        return jsonify({'error': 'A login ID (email, gid, or username) and either password or passcode are required'}), 400

    # Build the dynamic query
    user_query = {'$or': []}
    if email:  # Always check if there's any input
        # Check for email match (if format seems like an email)
        if '@' in email and '.' in email:
            user_query['$or'].append({'email': email})

        # Check for gid match (if input is a digit)
        try:
            gid = int(email)
            user_query['$or'].append({'gid': gid})
        except (ValueError, TypeError):
            pass

        # Always check for username match
        user_query['$or'].append({'username': email})

    if not user_query['$or']:
        auth_logger.warning("Login failed - missing login ID")
        return jsonify({'error': 'No valid login ID provided'}), 400

    user = db["user"].find_one(user_query)
    if not user:
        auth_logger.warning(f"Login failed - no such user: {email}")
        return jsonify({'error': 'Invalid credentials'}), 401

    if not user.get('Active', False):
        auth_logger.warning(f"Login denied - inactive account: GID={user['gid']}")
        return jsonify({'error': 'Account is not active. Please contact admin => (gbmultanu@gmail.com)'}), 403

    # ------------------ AUTO LOGOUT FOR INACTIVITY ------------------
    INACTIVITY_MINUTES = 20  # Change to 20 for production
    last_active = user.get("last_active")
    now = datetime.utcnow()
    if last_active and now - last_active > timedelta(minutes=INACTIVITY_MINUTES):
        db["user"].update_one({'gid': user['gid']}, {'$set': {'logged_in': False}})
        user['logged_in'] = False  # Ensure subsequent logic reflects update
        login_doc = db["login"].find_one({"gid": int(user["gid"])}, sort=[("login_time", -1)])
        if login_doc and login_doc.get("login_time"):
            session_seconds = (now - login_doc["login_time"]).total_seconds()
            db["login"].update_one(
                {"_id": login_doc["_id"]},
                {"$set": {
                    "logout_time": now,
                    "session_time_seconds": session_seconds
                }}
            )

    # ----------- END AUTO LOGOUT CHECK -----------------------------

    if user.get('logged_in', False):
        # Force logout previous session
        db["user"].update_one({'gid': user['gid']}, {'$set': {'logged_in': False}})
        # Update last login record as "logged out"
        login_doc = db["login"].find_one({"gid": int(user["gid"])}, sort=[("login_time", -1)])
        if login_doc and not login_doc.get("logout_time"):
            now = datetime.utcnow()
            session_seconds = (now - login_doc["login_time"]).total_seconds()
            db["login"].update_one(
                {"_id": login_doc["_id"]},
                {"$set": {"logout_time": now, "session_time_seconds": session_seconds}}
            )
        auth_logger.info(f"Forced logout of previous session for GID={user['gid']}")

    if password:
        if not check_password_hash(user['password_hash'], password):
            auth_logger.warning(f"Login failed - wrong password for GID={user['gid']}")
            return jsonify({'error': 'Invalid credentials'}), 401
    elif passcode:
        if not check_password_hash(user['passcode_hash'], passcode):
            auth_logger.warning(f"Login failed - wrong passcode for GID={user['gid']}")
            return jsonify({'error': 'Invalid credentials'}), 401

    login_time = datetime.utcnow()
    db["user"].update_one(
        {'gid': user['gid']},
        {'$set': {'last_login': login_time, 'logged_in': True, 'last_active': login_time}}
    )

    db["login"].insert_one({'gid': user['gid'], 'login_time': login_time})

    access_token = create_access_token(
        identity=str(user['gid']),
        expires_delta=timedelta(hours=1)
    )
    refresh_token = create_refresh_token(
        identity=str(user['gid']),
        expires_delta=timedelta(days=30)
    )

    return jsonify({
        'message': 'Login successful',
        'access_token': access_token,
        'refresh_token': refresh_token,
        'access_expires_in_seconds': 3600,
        'refresh_expires_in_days': 30,
        'username': user['username'],
        'email': user['email'],
        'gid': user['gid'],
        'usertype': user['usertype']
    }), 200

# ---------------- APP ONETIME LOGIN ----------------
@auth_api.route('/api/precheck', methods=['POST'])
def precheck():
    auth_logger.info("Precheck attempt started")
    data = request.get_json(silent=True) or {}
    email = data.get('email')
    password = data.get('password')
    passcode = data.get('passcode')

    if not (email) or (not password and not passcode):
        auth_logger.warning("Login failed - missing credentials")
        return jsonify({'error': 'A login ID (email, gid, or username) and either password or passcode are required'}), 400

    user_query = {'$or': []}
    if email:  # Always check if there's any input
        # Check for email match (if format seems like an email)
        if '@' in email and '.' in email:
            user_query['$or'].append({'email': email})

        # Check for gid match (if input is a digit)
        try:
            gid = int(email)
            user_query['$or'].append({'gid': gid})
        except (ValueError, TypeError):
            pass

        # Always check for username match
        user_query['$or'].append({'username': email})

    if not user_query['$or']:
        auth_logger.warning("Login failed - missing login ID")
        return jsonify({'error': 'No valid login ID provided'}), 400

    user = db["user"].find_one(user_query)
    if not user:
        auth_logger.warning(f"Login failed - no such user: {email}")
        return jsonify({'error': 'Invalid credentials'}), 401

    if not user.get('Active', False):
        auth_logger.warning(f"Precheck denied - inactive account: GID={user['gid']}")
        return jsonify({'error': 'Account is not active. Please contact admin => (gbmultanu@gmail.com)'}), 403

    if password:
        if not check_password_hash(user['password_hash'], password):
            auth_logger.warning(f"Login failed - wrong password for GID={user['gid']}")
            return jsonify({'error': 'Invalid credentials'}), 401
    elif passcode:
        if not check_password_hash(user['passcode_hash'], passcode):
            auth_logger.warning(f"Login failed - wrong passcode for GID={user['gid']}")
            return jsonify({'error': 'Invalid credentials'}), 401

     # FIX: Convert GID to string for JWT
    access_token = create_access_token(identity=str(user['gid']))
    
    return jsonify({
        'message': 'Precheck successful',
        'username': user['username'],
        'email': user['email'],
        'gid': user['gid'],
        'usertype': user['usertype'],
        'access_token': access_token
    }), 200

@auth_api.route('/api/app_login', methods=['POST'])
def app_login():
    auth_logger.info("App login attempt started")
    data = request.get_json(silent=True) or {}
    device_token = data.get('device_token')

    if not device_token:
        auth_logger.warning("App login failed - missing device_token")
        return jsonify({'error': 'Device token is required'}), 400

    user = db["user"].find_one({"device_token": device_token})
    if not user:
        auth_logger.warning("App login failed - no user with device_token")
        return jsonify({'error': 'Invalid device token'}), 401

    if not user.get('Active', False):
        auth_logger.warning(f"App login denied - inactive account: GID={user.get('gid')}")
        return jsonify({'error': 'Account is not active. Please contact admin => (gbmultanu@gmail.com)'}), 403

    # ------------------ AUTO LOGOUT FOR INACTIVITY ------------------
    INACTIVITY_MINUTES = 20  # Change to 20 for production
    last_active = user.get("last_active")
    now = datetime.utcnow()
    if last_active and now - last_active > timedelta(minutes=INACTIVITY_MINUTES):
        db["user"].update_one({'gid': user['gid']}, {'$set': {'logged_in': False}})
        user['logged_in'] = False  # Ensure subsequent logic reflects update
        login_doc = db["login"].find_one({"gid": int(user["gid"])}, sort=[("login_time", -1)])
        if login_doc and login_doc.get("login_time"):
            session_seconds = (now - login_doc["login_time"]).total_seconds()
            db["login"].update_one(
                {"_id": login_doc["_id"]},
                {"$set": {
                    "logout_time": now,
                    "session_time_seconds": session_seconds
                }}
            )

    # ----------- END AUTO LOGOUT CHECK -----------------------------

    if user.get('logged_in', False):
        # Force logout previous session
        db["user"].update_one({'gid': user['gid']}, {'$set': {'logged_in': False}})
        # Update last login record as "logged out"
        login_doc = db["login"].find_one({"gid": int(user["gid"])}, sort=[("login_time", -1)])
        if login_doc and not login_doc.get("logout_time"):
            now = datetime.utcnow()
            session_seconds = (now - login_doc["login_time"]).total_seconds()
            db["login"].update_one(
                {"_id": login_doc["_id"]},
                {"$set": {"logout_time": now, "session_time_seconds": session_seconds}}
            )
        auth_logger.info(f"Forced logout of previous session for GID={user['gid']}")

    login_time = datetime.utcnow()
    db["user"].update_one(
        {'gid': user['gid']},
        {'$set': {'last_login': login_time, 'logged_in': True, 'last_active': login_time}}
    )

    db["login"].insert_one({'gid': user['gid'], 'login_time': login_time})

    access_token = create_access_token(
        identity=str(user['gid']),  # FIX: Convert to string
        expires_delta=timedelta(hours=1)
    )
    refresh_token = create_refresh_token(
        identity=str(user['gid']),  # FIX: Convert to string
        expires_delta=timedelta(days=30)
    )

    return jsonify({
        'message': 'Login successful',
        'access_token': access_token,
        'refresh_token': refresh_token,
        'access_expires_in_seconds': 3600,
        'refresh_expires_in_days': 30,
        'username': user['username'],
        'email': user['email'],
        'gid': user['gid'],
        'usertype': user['usertype']
    }), 200

# ---------------- LOGOUT ----------------
@auth_api.route('/api/logout', methods=['POST'])
@jwt_required()
def logout():
    gid = int(get_jwt_identity())
    auth_logger.info(f"Logout attempt - GID={gid}")
    logout_time = datetime.utcnow()

    login_doc = db["login"].find_one({"gid": gid}, sort=[("login_time", -1)])
    if not login_doc:
        auth_logger.warning(f"Logout failed - no login record for GID={gid}")
        return jsonify({'error': 'No login record found'}), 404

    session_seconds = (logout_time - login_doc["login_time"]).total_seconds()

    db["login"].update_one(
        {"_id": login_doc["_id"]},
        {"$set": {
            "logout_time": logout_time,
            "session_time_seconds": session_seconds
        }}
    )

    db["user"].update_one({"gid": gid}, {"$set": {"logged_in": False}})
    auth_logger.info(f"Logout successful - GID={gid}, Session length: {session_seconds} sec")
    return jsonify({
        'message': 'Logout successful',
        'logout_time': logout_time.isoformat(),
        'session_time_seconds': session_seconds
    }), 200

# ---------------- REFRESH TOKEN ----------------
@auth_api.route('/api/refresh', methods=['POST'])
@jwt_required(refresh=True)
def refresh():
    gid = get_jwt_identity()
    new_access_token = create_access_token(
        identity=str(gid),
        expires_delta=timedelta(hours=1)
    )
    return jsonify({
        'access_token': new_access_token,
        'access_expires_in_seconds': 3600
    }), 200


# ---------------- PROFILE ----------------
@auth_api.route('/api/profile', methods=['GET', 'OPTIONS'])
@require_active_session
def profile():
    if request.method == "OPTIONS":
        return '', 200

    gid = get_jwt_identity()
    try:
        gid = int(gid)
    except (ValueError, TypeError):
        return jsonify({'error': 'Invalid user ID format'}), 400

    user = db["user"].find_one({'gid': gid})
    if not user or not user.get('logged_in', False):
        return jsonify({'error': 'User not logged in.'}), 403

    utc_tz = pytz.UTC
    ist_tz = pytz.timezone('Asia/Kolkata')

    def to_ist_string(dt):
        if isinstance(dt, datetime):
            if dt.tzinfo is None:
                dt = utc_tz.localize(dt)  # assume UTC
            return dt.astimezone(ist_tz).strftime("%Y-%m-%d %H:%M:%S")
        return None

    last_login_str = to_ist_string(user.get('last_login'))
    created_login_str = to_ist_string(user.get('created_at'))

    return jsonify({
        'gid': user.get('gid'),
        'username': user.get('username', ''),
        'email': user.get('email'),
        'usertype': user.get('usertype', 'normal'),
        'last_login': last_login_str,
        'created_at': created_login_str,
        'logged_in': user.get('logged_in', False)
    }), 200

# Reset password
@auth_api.route('/api/reset-password', methods=['POST'])
@require_active_session
def reset_password():
    data = request.get_json(silent=True) or {}
    new_password = data.get('new_password')

    if not new_password or len(new_password) < 6:
        return jsonify({'error': 'Password must be at least 6 characters long'}), 400

    gid = get_jwt_identity()
    try:
        gid = int(gid)
    except Exception:
        return jsonify({'error': 'Invalid user ID format'}), 400

    password_hash = generate_password_hash(new_password)
    result = db["user"].update_one({'gid': gid}, {'$set': {'password_hash': password_hash}})

    if result.matched_count == 0:
        return jsonify({'error': 'User not found'}), 404

    return jsonify({'message': 'Password updated successfully'}), 200

# Admin - Reset password with gid in URL path
@auth_api.route('/api/admin/reset-password/<int:gid>', methods=['POST'])
@require_active_session
def admin_reset_password(gid):
    data = request.get_json(silent=True) or {}
    new_password = data.get('new_password')

    if not new_password or len(new_password) < 6:
        return jsonify({'error': 'Password must be at least 6 characters long'}), 400

    password_hash = generate_password_hash(new_password)
    result = db["user"].update_one({'gid': gid}, {'$set': {'password_hash': password_hash}})

    if result.matched_count == 0:
        return jsonify({'error': 'User not found'}), 404

    return jsonify({'message': 'Password updated successfully'}), 200

# Admin - Delete user with gid in URL path
@auth_api.route('/api/admin/delete-user/<int:gid>', methods=['DELETE'])
@require_active_session
def admin_delete_user(gid):
    result = db["user"].delete_one({'gid': gid})

    if result.deleted_count == 0:
        return jsonify({'error': 'User not found'}), 404

    return jsonify({'message': 'User deleted successfully'}), 200


# Reset passcode
@auth_api.route('/api/reset-passcode', methods=['POST'])
@require_active_session
def reset_passcode():
    data = request.get_json(silent=True) or {}
    new_passcode = data.get('new_passcode')

    if not new_passcode or not new_passcode.isdigit() or len(new_passcode) != 4:
        return jsonify({'error': 'Passcode must be exactly 4 digits'}), 400

    gid = get_jwt_identity()
    try:
        gid = int(gid)
    except Exception:
        return jsonify({'error': 'Invalid user ID format'}), 400

    passcode_hash = generate_password_hash(new_passcode)
    result = db["user"].update_one({'gid': gid}, {'$set': {'passcode_hash': passcode_hash}})

    if result.matched_count == 0:
        return jsonify({'error': 'User not found'}), 404

    return jsonify({'message': 'Passcode updated successfully'}), 200

# Admin Reset Passcode
@auth_api.route('/api/admin/reset-passcode/<int:user_id>', methods=['POST'])
@require_active_session
def admin_reset_passcode(user_id):
    data = request.get_json(silent=True) or {}
    new_passcode = data.get('new_passcode')

    # Validate passcode (exactly 4 digits)
    if not new_passcode or not new_passcode.isdigit() or len(new_passcode) != 4:
        return jsonify({'error': 'Passcode must be exactly 4 digits'}), 400

    # Update passcode for the given user_id
    passcode_hash = generate_password_hash(new_passcode)
    result = db["user"].update_one({'gid': user_id}, {'$set': {'passcode_hash': passcode_hash}})
    
    if result.matched_count == 0:
        return jsonify({'error': 'User not found'}), 404

    return jsonify({'message': 'Passcode updated successfully'}), 200

# Admin route to get all users
@auth_api.route('/api/users', methods=['GET'])
@require_active_session
def list_users():
    gid = get_jwt_identity()
    try:
        gid = int(gid)
    except Exception:
        return jsonify({'error': 'Invalid user ID format'}), 400

    user = db["user"].find_one({'gid': gid})
    if not user or user.get('usertype') != 'admin':
        return jsonify({'error': 'Admin access required'}), 403

    utc_tz = pytz.UTC
    ist_tz = pytz.timezone('Asia/Kolkata')

    def to_ist_string(dt):
        if isinstance(dt, datetime):
            if dt.tzinfo is None:
                dt = utc_tz.localize(dt)
            return dt.astimezone(ist_tz).strftime("%Y-%m-%d %H:%M:%S")
        return None

    users_list = []
    for u in db["user"].find({}, {'_id': 0, 'password_hash': 0, 'passcode_hash': 0}):
        u['created_at'] = to_ist_string(u.get('created_at'))
        u['last_login'] = to_ist_string(u.get('last_login'))
        users_list.append(u)

    return jsonify(users_list), 200

# Admin route to update user info
@auth_api.route('/api/update-user/<int:target_gid>', methods=['POST'])
@require_active_session
def update_user(target_gid):
    admin_gid = get_jwt_identity()
    try:
        admin_gid = int(admin_gid)
    except Exception:
        return jsonify({'error': 'Invalid admin ID format'}), 400

    admin = db["user"].find_one({'gid': admin_gid})
    if not admin or admin.get('usertype') != 'admin':
        return jsonify({'error': 'Admin access required'}), 403

    data = request.get_json(silent=True) or {}
    updates = {}

    # Allow updates to email
    new_email = data.get('email')
    if new_email:
        if db["user"].find_one({'email': new_email, 'gid': {'$ne': target_gid}}):
            return jsonify({'error': 'Email already in use by another user'}), 409
        updates['email'] = new_email

    # Allow updates to username
    new_username = data.get('username')
    if new_username:
        updates['username'] = new_username

    # Allow toggle of Active status
    if 'Active' in data:
        if isinstance(data['Active'], bool):
            updates['Active'] = data['Active']
        else:
            return jsonify({'error': 'Active must be a boolean (true or false)'}), 400

    # --- NEW: Allow updating usertype ---
    if 'usertype' in data:
        new_usertype = data['usertype']
        if new_usertype not in ('admin', 'normal'):
            return jsonify({'error': 'Invalid usertype. Only "admin" or "normal" allowed.'}), 400
        updates['usertype'] = new_usertype

    if not updates:
        return jsonify({'error': 'No valid fields to update'}), 400

    result = db["user"].update_one({'gid': target_gid}, {'$set': updates})
    if result.matched_count == 0:
        return jsonify({'error': 'Target user not found'}), 404

    return jsonify({'message': 'User updated successfully'}), 200

# Protected example
@auth_api.route('/api/protected', methods=['GET'])
@require_active_session
def protected():
    gid = get_jwt_identity()
    try:
        gid = int(gid)
    except Exception:
        return jsonify({'error': 'Invalid user ID format'}), 400

    user = db["user"].find_one({'gid': gid})
    if not user:
        return jsonify({'error': 'User not found'}), 404

    return jsonify({
        'gid': user['gid'],
        'username': user['username'],
        'email': user['email'],
        'usertype': user['usertype']
    }), 200
