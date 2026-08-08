"""
Authentication API Routes
Handles user login, logout, registration, email verification, and the
company employee-approval workflow.
"""
import secrets
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from app import db, limiter
from app.models.user import User, ROLE_ADMIN, ROLE_USER, STATUS_ACTIVE, STATUS_PENDING, STATUS_REJECTED
from app.models.company import Company
from app.services.email_service import send_verification_email
from app.services.audit_service import log_event
from app.utils.decorators import admin_required

VERIFICATION_TOKEN_TTL = timedelta(hours=24)

bp = Blueprint('auth', __name__, url_prefix='/api/auth')


@bp.route('/register', methods=['POST'])
@limiter.limit("10 per hour")
def register():
    """
    User registration.

    - No company_code -> individual account: role=admin, status=active,
      nothing ever shared with anyone.
    - company_code given but no matching Company exists -> rejected
      outright (companies are pre-provisioned by a superadmin, never
      auto-created here).
    - company_code matches an existing Company -> role=user,
      status=pending, blocked from logging in until an admin of that
      company approves them.
    """
    data = request.get_json(silent=True) or {}

    name = data.get("name") or request.form.get("name")
    email = data.get("email") or request.form.get("email")
    password = data.get("password") or request.form.get("password")
    confirm_password = data.get("confirm_password") or request.form.get("confirm_password")
    company_code = (data.get("company_code") or request.form.get("company_code") or "").strip()
    agree_terms = data.get("agree_terms")
    if agree_terms is None:
        agree_terms = request.form.get("agree_terms")

    if email:
        email = email.strip().lower()

    if not all([name, email, password, confirm_password]):
        return jsonify({"status": "error", "message": "Missing required registration fields."}), 400

    if password != confirm_password:
        return jsonify({"status": "error", "message": "Passwords do not match."}), 400

    if agree_terms not in (True, "true", "True", "1", 1):
        return jsonify({"status": "error", "message": "You must accept the Terms & Privacy Policy to create an account."}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({"status": "error", "message": "An account with this email already exists."}), 400

    if company_code:
        company = Company.query.get(company_code)
        if not company:
            return jsonify({"status": "error", "message": "Unknown company code. Ask your company admin for the correct code."}), 400
        if company.initial_admin_email and company.initial_admin_email.lower() == email:
            role, status = ROLE_ADMIN, STATUS_ACTIVE
        else:
            role, status = ROLE_USER, STATUS_PENDING
    else:
        company = None
        role = ROLE_ADMIN
        status = STATUS_ACTIVE

    verification_token = secrets.token_urlsafe(32)

    user = User(
        name=name,
        email=email,
        company_code=company.company_code if company else None,
        role=role,
        status=status,
        email_verified=False,
        verification_token=verification_token,
        verification_token_expires=datetime.utcnow() + VERIFICATION_TOKEN_TTL,
    )
    user.set_password(password)

    try:
        db.session.add(user)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Registration DB Error: {e}")
        return jsonify({"status": "error", "message": "Internal server registration failure."}), 500

    verification_link = f"{request.host_url.rstrip('/')}/verify-email?token={verification_token}"
    send_verification_email(email, name, verification_link)

    log_event('user_registered', company_code=user.company_code, user_id=user.id,
               details={'status': status, 'role': role})

    if status == STATUS_PENDING:
        message = "Account created! Check your email for a verification link. Your company admin will also need to approve your access before you can sign in."
    else:
        message = "Account created! Check your email for a verification link, then sign in."

    return jsonify({"status": "success", "message": message}), 201


@bp.route('/verify-email', methods=['GET'])
def verify_email():
    """Confirms a signup verification token and marks the account as verified."""
    token = request.args.get('token', '')
    if not token:
        return jsonify({"status": "error", "message": "Missing verification token."}), 400

    user = User.query.filter_by(verification_token=token).first()
    if not user:
        return jsonify({"status": "error", "message": "Invalid or already-used verification link."}), 400

    if user.email_verified:
        return jsonify({"status": "success", "message": "Email already verified - you can sign in."}), 200

    if user.verification_token_expires and user.verification_token_expires < datetime.utcnow():
        return jsonify({"status": "error", "message": "This verification link has expired. Please request a new one."}), 400

    user.email_verified = True
    user.verification_token = None
    user.verification_token_expires = None
    db.session.commit()

    return jsonify({"status": "success", "message": "Email verified! You can now sign in."}), 200


@bp.route('/resend-verification', methods=['POST'])
@limiter.limit("5 per hour")
def resend_verification():
    """Regenerates and re-sends the verification email for an unverified account."""
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or request.form.get("email") or "").strip().lower()

    if not email:
        return jsonify({"status": "error", "message": "Missing email field."}), 400

    user = User.query.filter_by(email=email).first()

    # Don't reveal whether the account exists - respond the same way either way.
    if not user or user.email_verified:
        return jsonify({"status": "success", "message": "If that account needs verifying, a new email has been sent."}), 200

    user.verification_token = secrets.token_urlsafe(32)
    user.verification_token_expires = datetime.utcnow() + VERIFICATION_TOKEN_TTL
    db.session.commit()

    verification_link = f"{request.host_url.rstrip('/')}/verify-email?token={user.verification_token}"
    send_verification_email(email, user.name, verification_link)

    return jsonify({"status": "success", "message": "Verification email sent - check your inbox."}), 200


@bp.route('/login', methods=['POST'])
@limiter.limit("10 per minute")
def login():
    """Validates user credentials and returns a JWT access token."""
    data = request.get_json(silent=True) or {}

    email = data.get("email") or request.form.get("email")
    password = data.get("password") or request.form.get("password")

    if not email or not password:
        return jsonify({"status": "error", "message": "Missing email or password fields."}), 400

    email = email.strip().lower()
    user = User.query.filter_by(email=email).first()

    if not user or not user.check_password(password):
        return jsonify({"status": "error", "message": "Invalid email or password combination."}), 401

    if not user.email_verified:
        log_event('login_blocked', company_code=user.company_code, user_id=user.id, details={'reason': 'email_not_verified'})
        return jsonify({
            "status": "error",
            "reason": "email_not_verified",
            "message": "Please verify your email before signing in."
        }), 403

    if user.status == STATUS_PENDING:
        log_event('login_blocked', company_code=user.company_code, user_id=user.id, details={'reason': 'pending_approval'})
        return jsonify({
            "status": "error",
            "reason": "pending_approval",
            "message": "Your account is waiting for approval from your company admin."
        }), 403

    if user.status == STATUS_REJECTED:
        log_event('login_blocked', company_code=user.company_code, user_id=user.id, details={'reason': 'rejected'})
        return jsonify({
            "status": "error",
            "reason": "rejected",
            "message": "Your access request was declined. Contact your company admin for details."
        }), 403

    user.last_login = datetime.utcnow()
    db.session.commit()

    access_token = create_access_token(identity=str(user.id))
    log_event('login_success', company_code=user.company_code, user_id=user.id)

    return jsonify({
        "status": "success",
        "message": "Authentication successful",
        "access_token": access_token,
        "user": {
            "user_id": user.id,
            "name": user.name,
            "email": user.email,
            "role": user.role,
            "company_code": user.company_code,
        }
    }), 200


@bp.route('/logout', methods=['POST'])
@jwt_required()
def logout():
    return jsonify({"status": "success", "message": "Logged out successfully"}), 200


@bp.route('/profile', methods=['GET'])
@jwt_required()
def get_profile():
    """Get current logged-in user's profile."""
    current_user_id = get_jwt_identity()
    user = User.query.get(int(current_user_id))
    if not user:
        return jsonify({"status": "error", "message": "User profile not found."}), 404
    profile = user.to_dict()
    profile['is_superadmin'] = user.email.lower() in current_app.config.get('SUPERADMIN_EMAILS', [])
    return jsonify({"status": "success", "user": profile}), 200


@bp.route('/pending-approvals', methods=['GET'])
@jwt_required()
@admin_required
def pending_approvals(current_user):
    """Lists users pending approval in the acting admin's own company."""
    if not current_user.company_code:
        return jsonify({"status": "error", "message": "Individual accounts have no employees to approve."}), 400

    pending = (
        User.query
        .filter_by(company_code=current_user.company_code, status=STATUS_PENDING)
        .order_by(User.created_at.asc())
        .all()
    )
    return jsonify({"status": "success", "pending_users": [u.to_dict() for u in pending]}), 200


@bp.route('/approve/<int:user_id>', methods=['POST'])
@jwt_required()
@admin_required
def approve_employee(current_user, user_id):
    """Approves a pending employee in the acting admin's own company."""
    target = User.query.get(user_id)
    if not target or target.company_code != current_user.company_code:
        return jsonify({"status": "error", "message": "User not found in your company."}), 404

    target.status = STATUS_ACTIVE
    db.session.commit()
    log_event('employee_approved', company_code=current_user.company_code, user_id=current_user.id,
               resource_type='user', resource_id=target.id)

    return jsonify({"status": "success", "message": f"{target.name} has been approved."}), 200


@bp.route('/reject/<int:user_id>', methods=['POST'])
@jwt_required()
@admin_required
def reject_employee(current_user, user_id):
    """Rejects a pending employee in the acting admin's own company."""
    target = User.query.get(user_id)
    if not target or target.company_code != current_user.company_code:
        return jsonify({"status": "error", "message": "User not found in your company."}), 404

    target.status = STATUS_REJECTED
    db.session.commit()
    log_event('employee_rejected', company_code=current_user.company_code, user_id=current_user.id,
               resource_type='user', resource_id=target.id)

    return jsonify({"status": "success", "message": f"{target.name}'s access request was declined."}), 200
