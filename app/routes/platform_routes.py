"""
Platform (Superadmin) API Routes
Company provisioning - restricted to the SUPERADMIN_EMAILS allowlist
(config/config.py), not a role anyone can sign up or be promoted into.
Companies must exist here before anyone can sign up under their
company_code (see app/routes/auth_routes.py register()).
"""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from app import db
from app.models.company import Company
from app.services.audit_service import log_event
from app.utils.decorators import superadmin_required

bp = Blueprint('platform', __name__, url_prefix='/api/platform')


@bp.route('/companies', methods=['GET'])
@jwt_required()
@superadmin_required
def list_companies(current_user):
    companies = Company.query.order_by(Company.created_at.desc()).all()
    return jsonify({"status": "success", "companies": [c.to_dict() for c in companies]}), 200


@bp.route('/companies', methods=['POST'])
@jwt_required()
@superadmin_required
def create_company(current_user):
    """
    Provisions a new company. `initial_admin_email`, if given, designates
    who becomes that company's founding admin the moment they sign up
    (or immediately, if they already have an individual account with
    that email - see below).
    """
    data = request.get_json(silent=True) or {}
    company_code = (data.get('company_code') or '').strip()
    company_name = (data.get('company_name') or '').strip()
    initial_admin_email = (data.get('initial_admin_email') or '').strip().lower() or None

    if not company_code or not company_name:
        return jsonify({"status": "error", "message": "company_code and company_name are required."}), 400

    if Company.query.get(company_code):
        return jsonify({"status": "error", "message": "A company with this code already exists."}), 400

    company = Company(
        company_code=company_code,
        company_name=company_name,
        created_by_email=current_user.email,
        initial_admin_email=initial_admin_email,
    )
    db.session.add(company)

    # If the designated admin already has an individual (no-company)
    # account, attach them to the company as its admin immediately
    # instead of waiting for them to sign up again.
    if initial_admin_email:
        from app.models.user import User, ROLE_ADMIN, STATUS_ACTIVE
        existing = User.query.filter_by(email=initial_admin_email).first()
        if existing and not existing.company_code:
            existing.company_code = company_code
            existing.role = ROLE_ADMIN
            existing.status = STATUS_ACTIVE

    db.session.commit()
    log_event('company_provisioned', company_code=company_code, user_id=current_user.id,
               details={'initial_admin_email': initial_admin_email})

    return jsonify({"status": "success", "company": company.to_dict()}), 201
