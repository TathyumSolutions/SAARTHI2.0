"""
BI Semantics Config API Routes
Lets an admin/settings screen view and tune the per-entity default measure
and aggregation (e.g. sales orders -> SUM(net_value)) that the SQL
Generator Agent consults when a question doesn't explicitly say what to
measure. See app/services/bi_semantics_service.py for the built-in
defaults and merge logic.
"""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from app import db
from app.models.bi_semantics_config import BiSemanticsConfig
from app.utils.auth_helpers import get_current_user
from app.services.bi_semantics_service import list_entries, DEFAULT_BI_SEMANTICS


bp = Blueprint('bi_semantics', __name__, url_prefix='/api/bi-semantics')


@bp.route('/entries', methods=['GET'])
@jwt_required()
def get_entries():
    """
    List every table this user has BI semantics for - their own overrides
    plus any built-in default not yet overridden.
    Response: { "entries": [{table_name, entity_label, measure_column, aggregation, source}] }
    """
    current_user = get_current_user()
    if not current_user:
        return jsonify({"error": "Authentication required"}), 401
    return jsonify({"entries": list_entries(user_id=current_user.id)}), 200


@bp.route('/entries', methods=['POST'])
@jwt_required()
def upsert_entry():
    """
    Create or update this user's override for one table.
    Request: { "table_name": "vbak", "measure_column": "net_value", "aggregation": "SUM", "entity_label": "Sales Orders" }
    Response: { "entry": {...}, "message": "..." }
    """
    current_user = get_current_user()
    if not current_user:
        return jsonify({"error": "Authentication required"}), 401

    data = request.get_json() or {}
    table_name = (data.get('table_name') or '').strip()
    measure_column = (data.get('measure_column') or '').strip()
    aggregation = (data.get('aggregation') or 'SUM').strip().upper()

    if not table_name or not measure_column:
        return jsonify({"error": "table_name and measure_column are required"}), 400
    if aggregation not in ('SUM', 'COUNT', 'AVG', 'MIN', 'MAX'):
        return jsonify({"error": "aggregation must be one of SUM, COUNT, AVG, MIN, MAX"}), 400

    entry = BiSemanticsConfig.query.filter_by(user_id=current_user.id, table_name=table_name).first()
    if not entry:
        entry = BiSemanticsConfig(user_id=current_user.id, table_name=table_name)

    entry.entity_label = data.get('entity_label') or table_name
    entry.measure_column = measure_column
    entry.aggregation = aggregation
    entry.company_code = current_user.company_code

    db.session.add(entry)
    db.session.commit()

    return jsonify({"entry": {**entry.to_dict(), "source": "custom"}, "message": "Saved successfully."}), 200


@bp.route('/entries/<string:table_name>', methods=['DELETE'])
@jwt_required()
def delete_entry(table_name):
    """
    Remove this user's override for a table, reverting it to the built-in
    default (if one exists) rather than deleting the concept entirely.
    """
    current_user = get_current_user()
    if not current_user:
        return jsonify({"error": "Authentication required"}), 401

    entry = BiSemanticsConfig.query.filter_by(user_id=current_user.id, table_name=table_name).first()
    if not entry:
        return jsonify({"error": "No custom override found for this table."}), 404

    db.session.delete(entry)
    db.session.commit()
    reverted_to = DEFAULT_BI_SEMANTICS.get(table_name.lower())
    return jsonify({
        "message": f"Override for '{table_name}' removed.",
        "reverted_to_default": reverted_to,
    }), 200
