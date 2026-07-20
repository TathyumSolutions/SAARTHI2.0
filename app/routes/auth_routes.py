# """
# Authentication API Routes
# Handles user login, logout, registration, and token management
# """
# from flask import Blueprint, request, jsonify
# from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity

# bp = Blueprint('auth', __name__, url_prefix='/api/auth')

# @bp.route('/login', methods=['POST'])
# def login():
#     """
#     User login endpoint
#     Request: { "email": "user@example.com", "password": "password123" }
#     Response: { "status": "success", "user_id": 42, "email": "..." }
#     """
#     data = request.get_json() or {}
#     email = data.get("email")
#     password = data.get("password")

#     # Guard clause: ensure data was received
#     if not email or not password:
#         return jsonify({"status": "error", "message": "Missing email or password fields."}), 400

#     # Simple local check for testing and demo phases
#     if email == "sahith@example.com" and password == "password123":
#         return jsonify({
#             "status": "success",
#             "message": "Authentication successful",
#             "user_id": 42,  # This ID will become the conversation session_id
#             "email": email
#         }), 200
    
#     # Return an unauthorized error status if text doesn't match
#     return jsonify({"status": "error", "message": "Invalid email or password combination."}), 401


# """
# Authentication API Routes
# Handles user login, logout, registration, and token management
# """
# from flask import Blueprint, request, jsonify
# from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity

# bp = Blueprint('auth', __name__, url_prefix='/api/auth')

# @bp.route('/login', methods=['POST'])
# def login():
#     """
#     User login endpoint
#     Validates default login credentials for the sign-in screen
#     """
#     # Robust data extraction: checks for JSON first, falls back to Form data
#     data = request.get_json(silent=True) or {}
    
#     email = data.get("email") or request.form.get("email")
#     password = data.get("password") or request.form.get("password")

#     # Guard clause: ensure credentials were sent
#     if not email or not password:
#         return jsonify({
#             "status": "error", 
#             "message": "Missing email or password fields."
#         }), 400

#     # Default login credentials validation check
#     if email == "sahith@example.com" and password == "password123":
#         return jsonify({
#             "status": "success",
#             "message": "Authentication successful",
#             "user_id": 42,  # Becomes the active conversation session_id
#             "email": email
#         }), 200
    
#     # Return unauthorized error if credentials do not match
#     return jsonify({
#         "status": "error", 
#         "message": "Invalid email or password combination."
#     }), 401


# #@bp.route('/login', methods=['POST'])
# #def login():
# #    """
# #    User login endpoint
# #    Request: { "email": "user@example.com", "password": "password123" }
# #    Response: { "access_token": "...", "user": {...} }
# #    """
#     # : Implement login logic
# #    pass

# @bp.route('/register', methods=['POST'])
# def register():
#     """
#     User registration endpoint
#     Request: { "email": "user@example.com", "password": "password123", "name": "John Doe" }
#     Response: { "message": "User registered successfully", "user": {...} }
#     """
#     # TODO: Implement registration logic
#     pass

# @bp.route('/logout', methods=['POST'])
# @jwt_required()
# def logout():
#     """
#     User logout endpoint
#     Response: { "message": "Logged out successfully" }
#     """
#     # TODO: Implement logout logic (blacklist token)
#     pass

# @bp.route('/refresh', methods=['POST'])
# @jwt_required()
# def refresh_token():
#     """
#     Refresh access token
#     Response: { "access_token": "..." }
#     """
#     # TODO: Implement token refresh logic
#     pass

# @bp.route('/profile', methods=['GET'])
# @jwt_required()
# def get_profile():
#     """
#     Get current user profile
#     Response: { "user": {...} }
#     """
#     # TODO: Implement get profile logic
#     pass

# @bp.route('/profile', methods=['PUT'])
# @jwt_required()
# def update_profile():
#     """
#     Update user profile
#     Request: { "name": "John Doe", "preferences": {...} }
#     Response: { "message": "Profile updated", "user": {...} }
#     """
#     # TODO: Implement update profile logic
#     pass



"""
Authentication API Routes
Handles user login, logout, registration, and token management
"""
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Blueprint, request, jsonify
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from werkzeug.security import generate_password_hash, check_password_hash

bp = Blueprint('auth', __name__, url_prefix='/api/auth')

# def get_auth_db_connection():
#     """Establishes an isolated connection to the authentication database."""
#     base_uri = os.environ.get('ENVIRONMENT_DATABASE_URL') or "postgresql://saarthi:password@db:5432/saarthi_db"
#     if "saarthi_db" in base_uri:
#         auth_db_uri = base_uri.replace("saarthi_db", "saarthi_chats_db")
#     else:
#         auth_db_uri = "postgresql://saarthi:password@db:5432/saarthi_chats_db"
#     return psycopg2.connect(auth_db_uri)

def get_auth_db_connection():
    base_uri = os.environ.get('ENVIRONMENT_DATABASE_URL') or "postgresql://saarthi:password@db:5432/saarthi_db"
    if "saarthi_db" in base_uri:
        auth_db_uri = base_uri.replace("saarthi_db", "saarthi_auth_db")
    else:
        auth_db_uri = "postgresql://saarthi:password@db:5432/saarthi_auth_db"
    return psycopg2.connect(auth_db_uri)


@bp.route('/register', methods=['POST'])
def register():
    """
    User registration endpoint
    Extracts Name, Email, Password, and Confirm Password from JSON or Forms.
    """
    data = request.get_json(silent=True) or {}
    
    name = data.get("name") or request.form.get("name")
    email = data.get("email") or request.form.get("email")
    password = data.get("password") or request.form.get("password")
    confirm_password = data.get("confirm_password") or request.form.get("confirm_password")

    # Normalize email so different casing maps to one account identity.
    if email:
        email = email.strip().lower()
    company_code = (data.get("company_code") or request.form.get("company_code") or "").strip()
    role = (data.get("role") or request.form.get("role") or "user").strip().lower()

    # Guard clause: Verify all inputs are present
    if not all([name, email, password, confirm_password, company_code]):
        return jsonify({"status": "error", "message": "Missing required registration fields."}), 400

    if role not in ("admin", "user"):
        return jsonify({"status": "error", "message": "Role must be either 'admin' or 'user'."}), 400

    # Guard clause: Match verification passwords
    if password != confirm_password:
        return jsonify({"status": "error", "message": "Passwords do not match."}), 400

    try:
        conn = get_auth_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Check if email is already taken
        cursor.execute("SELECT id FROM users WHERE email = %s;", (email,))
        existing_user = cursor.fetchone()

        if existing_user:
            cursor.close()
            conn.close()
            return jsonify({"status": "error", "message": "An account with this email already exists."}), 400

        # Hash password securely before database write
        password_hash = generate_password_hash(password, method='scrypt')

        # Insert user into PostgreSQL table
        cursor.execute(
            "INSERT INTO users (name, email, password_hash, company_code, role) VALUES (%s, %s, %s, %s, %s);",
            (name, email, password_hash, company_code, role)
        )
        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({
            "status": "success", 
            "message": "User registered successfully"
        }), 201

    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        return jsonify({"status": "error", "message": "An account with this email already exists."}), 400

    except Exception as e:
        print(f"Registration DB Error: {e}")
        return jsonify({"status": "error", "message": "Internal server registration failure."}), 500


@bp.route('/login', methods=['POST'])
def login():
    """
    User login endpoint
    Validates user credentials against Postgres and returns an enterprise JWT access token.
    """
    data = request.get_json(silent=True) or {}
    
    email = data.get("email") or request.form.get("email")
    password = data.get("password") or request.form.get("password")

    if not email or not password:
        return jsonify({"status": "error", "message": "Missing email or password fields."}), 400

    # Same normalization as register() so login matches stored lowercase emails.
    email = email.strip().lower()

    try:
        conn = get_auth_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Lookup user profile by email
        cursor.execute("SELECT id, name, email, password_hash FROM users WHERE email = %s;", (email,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()

        # Check if user exists and verify password hash match
        if not user or not check_password_hash(user['password_hash'], password):
            return jsonify({"status": "error", "message": "Invalid email or password combination."}), 401

        # Generate enterprise JWT secure access token string
        access_token = create_access_token(identity=str(user['id']))

        return jsonify({
            "status": "success",
            "message": "Authentication successful",
            "access_token": access_token,
            "user": {
                "user_id": user['id'],
                "name": user['name'],
                "email": user['email']
            }
        }), 200

    except Exception as e:
        print(f"Login DB Error: {e}")
        return jsonify({"status": "error", "message": "Internal validation failure."}), 500


@bp.route('/logout', methods=['POST'])
@jwt_required()
def logout():
    """
    User logout endpoint
    """
    # Simply tell frontend to drop the token client-side
    return jsonify({"status": "success", "message": "Logged out successfully"}), 200


@bp.route('/profile', methods=['GET'])
@jwt_required()
def get_profile():
    """
    Get current logged-in user profile utilizing the secure JWT identity
    """
    current_user_id = get_jwt_identity()
    try:
        conn = get_auth_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT id, name, email, created_at FROM users WHERE id = %s;", (current_user_id,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()

        if not user:
            return jsonify({"status": "error", "message": "User profile not found."}), 404

        return jsonify({"status": "success", "user": user}), 200
    except Exception as e:
        print(f"Profile Fetch Error: {e}")
        return jsonify({"status": "error", "message": "Failed to load user info."}), 500