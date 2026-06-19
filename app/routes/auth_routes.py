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


"""
Authentication API Routes
Handles user login, logout, registration, and token management
"""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity

bp = Blueprint('auth', __name__, url_prefix='/api/auth')

@bp.route('/login', methods=['POST'])
def login():
    """
    User login endpoint
    Validates default login credentials for the sign-in screen
    """
    # Robust data extraction: checks for JSON first, falls back to Form data
    data = request.get_json(silent=True) or {}
    
    email = data.get("email") or request.form.get("email")
    password = data.get("password") or request.form.get("password")

    # Guard clause: ensure credentials were sent
    if not email or not password:
        return jsonify({
            "status": "error", 
            "message": "Missing email or password fields."
        }), 400

    # Default login credentials validation check
    if email == "sahith@example.com" and password == "password123":
        return jsonify({
            "status": "success",
            "message": "Authentication successful",
            "user_id": 42,  # Becomes the active conversation session_id
            "email": email
        }), 200
    
    # Return unauthorized error if credentials do not match
    return jsonify({
        "status": "error", 
        "message": "Invalid email or password combination."
    }), 401


#@bp.route('/login', methods=['POST'])
#def login():
#    """
#    User login endpoint
#    Request: { "email": "user@example.com", "password": "password123" }
#    Response: { "access_token": "...", "user": {...} }
#    """
    # : Implement login logic
#    pass

@bp.route('/register', methods=['POST'])
def register():
    """
    User registration endpoint
    Request: { "email": "user@example.com", "password": "password123", "name": "John Doe" }
    Response: { "message": "User registered successfully", "user": {...} }
    """
    # TODO: Implement registration logic
    pass

@bp.route('/logout', methods=['POST'])
@jwt_required()
def logout():
    """
    User logout endpoint
    Response: { "message": "Logged out successfully" }
    """
    # TODO: Implement logout logic (blacklist token)
    pass

@bp.route('/refresh', methods=['POST'])
@jwt_required()
def refresh_token():
    """
    Refresh access token
    Response: { "access_token": "..." }
    """
    # TODO: Implement token refresh logic
    pass

@bp.route('/profile', methods=['GET'])
@jwt_required()
def get_profile():
    """
    Get current user profile
    Response: { "user": {...} }
    """
    # TODO: Implement get profile logic
    pass

@bp.route('/profile', methods=['PUT'])
@jwt_required()
def update_profile():
    """
    Update user profile
    Request: { "name": "John Doe", "preferences": {...} }
    Response: { "message": "Profile updated", "user": {...} }
    """
    # TODO: Implement update profile logic
    pass
