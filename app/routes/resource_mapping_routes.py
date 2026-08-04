"""
Resource Mapping API Routes
Company-scoped: a company admin can only ever see/manage users and
resources belonging to their own company_code. Nothing is auto-shared -
uploading a file, registering a DB connection, or an API connector stays
private to its creator until an admin explicitly grants access here.
"""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

from app import db
from app.models.user import User
from app.models.database_connection import DatabaseConnection
from app.models.file_resource import FileResource
from app.models.api_connector import ApiConnector
from app.models.resource_mapping import ResourceMapping, RESOURCE_TYPES
from app.services.audit_service import log_event
from app.utils.decorators import admin_required

bp = Blueprint('resource_mapping', __name__, url_prefix='/api/resource-mapping')


def _resource_lookup(resource_type, resource_id, company_code):
    """Returns the resource row if it exists and belongs to company_code, else None."""
    model = {'database': DatabaseConnection, 'file': FileResource, 'api': ApiConnector}.get(resource_type)
    if not model:
        return None
    resource = model.query.get(resource_id)
    if not resource or resource.company_code != company_code:
        return None
    return resource


def _resource_display_name(resource_type, resource):
    if resource_type == 'file':
        return resource.file_name
    if resource_type == 'api':
        return resource.integration_name
    return resource.name


@bp.route('/users', methods=['GET'])
@jwt_required()
@admin_required
def list_users(current_user):
    """Users in the acting admin's own company, for the mapping picker."""
    if not current_user.company_code:
        return jsonify({"users": []}), 200

    users = User.query.filter_by(company_code=current_user.company_code, status='active').order_by(User.name).all()
    return jsonify({"users": [u.to_dict() for u in users]}), 200


@bp.route('/resources', methods=['GET'])
@jwt_required()
@admin_required
def list_resources(current_user):
    """All resources (database/file/api) belonging to the acting admin's own company."""
    if not current_user.company_code:
        return jsonify({"resources": []}), 200

    company_code = current_user.company_code
    resources = []

    for conn in DatabaseConnection.query.filter_by(company_code=company_code).all():
        resources.append({"type": "database", "id": conn.id, "name": conn.name})

    for f in FileResource.query.filter_by(company_code=company_code).all():
        resources.append({"type": "file", "id": f.id, "name": f.file_name})

    for tool in ApiConnector.query.filter_by(company_code=company_code).all():
        resources.append({"type": "api", "id": tool.id, "name": tool.integration_name})

    return jsonify({"resources": resources}), 200


@bp.route('/bulk', methods=['POST'])
@jwt_required()
@admin_required
def create_mappings_bulk(current_user):
    """Grants every (user_id x resource) combination submitted, all validated against the admin's own company."""
    if not current_user.company_code:
        return jsonify({"status": "error", "message": "Individual accounts have nothing to map."}), 400

    data = request.get_json(silent=True) or {}
    user_ids = data.get("user_ids") or []
    resources = data.get("resources") or []

    if not user_ids or not resources:
        return jsonify({"status": "error", "message": "user_ids and resources are required."}), 400

    # Checkbox values arrive as strings from the frontend's HTML attributes.
    try:
        user_ids = [int(u) for u in user_ids]
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "user_ids must be numeric."}), 400

    company_code = current_user.company_code
    valid_user_ids = {
        u.id for u in User.query.filter(
            User.id.in_(user_ids), User.company_code == company_code
        ).all()
    }

    created, skipped = 0, 0
    for user_id in user_ids:
        if user_id not in valid_user_ids:
            skipped += len(resources)
            continue
        for r in resources:
            resource_type = r.get("type")
            try:
                resource_id = int(r.get("id"))
            except (TypeError, ValueError):
                skipped += 1
                continue
            if resource_type not in RESOURCE_TYPES:
                skipped += 1
                continue
            if not _resource_lookup(resource_type, resource_id, company_code):
                skipped += 1
                continue

            exists = ResourceMapping.query.filter_by(
                resource_type=resource_type, resource_id=resource_id, user_id=user_id
            ).first()
            if exists:
                skipped += 1
                continue

            db.session.add(ResourceMapping(
                company_code=company_code,
                resource_type=resource_type,
                resource_id=resource_id,
                user_id=user_id,
                granted_by_user_id=current_user.id,
            ))
            created += 1

    db.session.commit()
    log_event('resource_mapping_bulk_grant', company_code=company_code, user_id=current_user.id,
               details={'created': created, 'skipped': skipped})

    return jsonify({"status": "success", "created": created, "skipped": skipped}), 201


@bp.route('/all', methods=['GET'])
@jwt_required()
@admin_required
def get_all_mappings(current_user):
    """All mappings in the acting admin's own company, joined with user + resource names."""
    if not current_user.company_code:
        return jsonify({"mappings": []}), 200

    mappings = ResourceMapping.query.filter_by(company_code=current_user.company_code).order_by(ResourceMapping.created_at.desc()).all()
    users_by_id = {u.id: u for u in User.query.filter_by(company_code=current_user.company_code).all()}

    result = []
    for m in mappings:
        resource = _resource_lookup(m.resource_type, m.resource_id, current_user.company_code)
        user = users_by_id.get(m.user_id)
        result.append({
            "id": m.id,
            "user_id": m.user_id,
            "user_name": user.name if user else None,
            "user_email": user.email if user else None,
            "resource_type": m.resource_type,
            "resource_id": m.resource_id,
            "resource_name": _resource_display_name(m.resource_type, resource) if resource else None,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        })

    return jsonify({"mappings": result}), 200


@bp.route('/<int:user_id>', methods=['GET'])
@jwt_required()
@admin_required
def get_user_mappings(current_user, user_id):
    """Resources a specific (same-company) user is currently mapped to."""
    target = User.query.get(user_id)
    if not target or target.company_code != current_user.company_code:
        return jsonify({"status": "error", "message": "User not found in your company."}), 404

    mappings = ResourceMapping.query.filter_by(user_id=user_id).order_by(ResourceMapping.created_at.desc()).all()
    return jsonify({"mappings": [m.to_dict() for m in mappings]}), 200


@bp.route('', methods=['POST'])
@jwt_required()
@admin_required
def create_mapping(current_user):
    """Grants one user access to one resource, both validated against the admin's own company."""
    if not current_user.company_code:
        return jsonify({"status": "error", "message": "Individual accounts have nothing to map."}), 400

    data = request.get_json(silent=True) or {}
    resource_type = data.get("resource_type")

    if not all([data.get("user_id"), resource_type, data.get("resource_id")]):
        return jsonify({"status": "error", "message": "user_id, resource_type, and resource_id are required."}), 400

    try:
        user_id = int(data.get("user_id"))
        resource_id = int(data.get("resource_id"))
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "user_id and resource_id must be numeric."}), 400

    if resource_type not in RESOURCE_TYPES:
        return jsonify({"status": "error", "message": "resource_type must be 'database', 'file', or 'api'."}), 400

    target = User.query.get(user_id)
    if not target or target.company_code != current_user.company_code:
        return jsonify({"status": "error", "message": "User not found in your company."}), 404

    if not _resource_lookup(resource_type, resource_id, current_user.company_code):
        return jsonify({"status": "error", "message": "Resource not found in your company."}), 404

    if ResourceMapping.query.filter_by(resource_type=resource_type, resource_id=resource_id, user_id=user_id).first():
        return jsonify({"status": "success", "message": "Already mapped."}), 200

    mapping = ResourceMapping(
        company_code=current_user.company_code,
        resource_type=resource_type,
        resource_id=resource_id,
        user_id=user_id,
        granted_by_user_id=current_user.id,
    )
    db.session.add(mapping)
    db.session.commit()

    log_event('resource_mapping_grant', company_code=current_user.company_code, user_id=current_user.id,
               resource_type=resource_type, resource_id=resource_id, details={'granted_to_user_id': user_id})

    return jsonify({"status": "success", "message": "Resource mapped to user."}), 201


@bp.route('/<int:mapping_id>', methods=['DELETE'])
@jwt_required()
@admin_required
def delete_mapping(current_user, mapping_id):
    """Removes a single mapping, only if it belongs to the acting admin's own company."""
    mapping = ResourceMapping.query.get(mapping_id)
    if not mapping or mapping.company_code != current_user.company_code:
        return jsonify({"status": "error", "message": "Mapping not found."}), 404

    db.session.delete(mapping)
    db.session.commit()

    log_event('resource_mapping_revoke', company_code=current_user.company_code, user_id=current_user.id,
               resource_type=mapping.resource_type, resource_id=mapping.resource_id,
               details={'revoked_from_user_id': mapping.user_id})

    return jsonify({"status": "success", "message": "Mapping removed."}), 200
