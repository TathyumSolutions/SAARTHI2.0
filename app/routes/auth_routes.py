"""
Authentication API Routes
Handles user login, logout, registration, and token management.

Tokens are issued as httpOnly, Secure cookies (see config/config.py:
JWT_TOKEN_LOCATION = ['cookies']) rather than returned in the response body,
so client-side JS never has direct access to the raw JWT.
"""
import logging
import os

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Blueprint, request, jsonify
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    set_access_cookies,
    set_refresh_cookies,
    unset_jwt_cookies,
    jwt_required,
    get_jwt_identity,
)
from werkzeug.security import generate_password_hash, check_password_hash

from app import limiter

logger = logging.getLogger(__name__)

bp = Blueprint('auth', __name__, url_prefix='/api/auth')


def get_auth_db_connection():
    base_uri = os.environ.get('ENVIRONMENT_DATABASE_URL') or "postgresql://saarthi:password@db:5432/saarthi_db"
    if "saarthi_db" in base_uri:
        auth_db_uri = base_uri.replace("saarthi_db", "saarthi_auth_db")
    else:
        auth_db_uri = "postgresql://saarthi:password@db:5432/saarthi_auth_db"
    return psycopg2.connect(auth_db_uri)


@bp.route('/register', methods=['POST'])
@limiter.limit("10 per hour")
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

    # Guard clause: Verify all inputs are present
    if not all([name, email, password, confirm_password]):
        return jsonify({"status": "error", "message": "Missing required registration fields."}), 400

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
            "INSERT INTO users (name, email, password_hash) VALUES (%s, %s, %s);",
            (name, email, password_hash)
        )
        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({
            "status": "success",
            "message": "User registered successfully"
        }), 201

    except Exception:
        logger.exception("Registration DB error")
        return jsonify({"status": "error", "message": "Internal server registration failure."}), 500


@bp.route('/login', methods=['POST'])
@limiter.limit("10 per minute")
def login():
    """
    User login endpoint
    Validates user credentials against Postgres and sets a JWT access/refresh
    cookie pair (plus a readable CSRF cookie) on success.
    """
    data = request.get_json(silent=True) or {}

    email = data.get("email") or request.form.get("email")
    password = data.get("password") or request.form.get("password")

    if not email or not password:
        return jsonify({"status": "error", "message": "Missing email or password fields."}), 400

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

        identity = str(user['id'])
        access_token = create_access_token(identity=identity)
        refresh_token = create_refresh_token(identity=identity)

        response = jsonify({
            "status": "success",
            "message": "Authentication successful",
            "user": {
                "user_id": user['id'],
                "name": user['name'],
                "email": user['email']
            }
        })
        set_access_cookies(response, access_token)
        set_refresh_cookies(response, refresh_token)
        return response, 200

    except Exception:
        logger.exception("Login DB error")
        return jsonify({"status": "error", "message": "Internal validation failure."}), 500


@bp.route('/refresh', methods=['POST'])
@jwt_required(refresh=True)
def refresh_token():
    """Reissue an access token cookie from a valid refresh token cookie."""
    identity = get_jwt_identity()
    access_token = create_access_token(identity=identity)

    response = jsonify({"status": "success", "message": "Token refreshed"})
    set_access_cookies(response, access_token)
    return response, 200


@bp.route('/logout', methods=['POST'])
@jwt_required()
def logout():
    """User logout endpoint - clears the JWT cookies server-side."""
    response = jsonify({"status": "success", "message": "Logged out successfully"})
    unset_jwt_cookies(response)
    return response, 200


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
    except Exception:
        logger.exception("Profile fetch error")
        return jsonify({"status": "error", "message": "Failed to load user info."}), 500
