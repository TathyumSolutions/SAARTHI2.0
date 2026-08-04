"""
Authorization Utilities
"""
from functools import wraps
from flask import jsonify, current_app
from flask_jwt_extended import get_jwt_identity
from app.models.user import User, ROLE_ADMIN


def admin_required(f):
    """
    Requires the JWT-authenticated user to have role='admin', and passes
    that resolved User object into the view as its first argument. Must
    be applied *after* @jwt_required() (i.e. listed below it) so a JWT
    identity is already available.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = User.query.get(int(get_jwt_identity()))
        if not user:
            return jsonify({"status": "error", "message": "User not found."}), 401
        if user.role != ROLE_ADMIN:
            return jsonify({"status": "error", "message": "Admin access required."}), 403
        return f(user, *args, **kwargs)
    return decorated_function


def superadmin_required(f):
    """
    Requires the JWT-authenticated user's email to be in the SUPERADMIN_EMAILS
    env-var allowlist (config.SUPERADMIN_EMAILS) - a small, fixed set of
    platform-staff accounts, not a role anyone can sign up or be promoted
    into. Passes the resolved User object into the view as its first
    argument. Must be applied after @jwt_required().
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = User.query.get(int(get_jwt_identity()))
        if not user:
            return jsonify({"status": "error", "message": "User not found."}), 401
        if user.email.lower() not in current_app.config.get('SUPERADMIN_EMAILS', []):
            return jsonify({"status": "error", "message": "Superadmin access required."}), 403
        return f(user, *args, **kwargs)
    return decorated_function
