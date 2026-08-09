"""
Database Connection API Routes
Handles database connections, schema discovery, and connection testing
"""
import time
import traceback
import re
from flask import Blueprint, request, jsonify
from app import db
from app.models.database_connection import DatabaseConnection
import subprocess
import sys  
import os
import logging
import datetime
import pandas as pd
import psycopg2
from flask_jwt_extended import jwt_required
from app.services import spreadsheet_service
from app.utils.auth_helpers import get_current_user
from app.services.audit_service import log_event

bp = Blueprint('database', __name__, url_prefix='/api/databases')


def _sanitize_identifier(name: str) -> str:
    """Turns a messy file/column name into a safe SQL table/column name."""
    name = re.sub(r'[^a-zA-Z0-9_]', '_', (name or '').strip().lower())
    name = re.sub(r'_+', '_', name).strip('_')
    if not name or name[0].isdigit():
        name = f"col_{name}"
    return name


def _dedupe_identifiers(names):
    """Ensures identifiers are unique after sanitization."""
    seen = {}
    out = []
    for raw in names:
        base = _sanitize_identifier(str(raw))
        count = seen.get(base, 0)
        seen[base] = count + 1
        out.append(base if count == 0 else f"{base}_{count + 1}")
    return out


def serialize_connection(conn):
    """Serialize database connection to dict"""
    try:
        return {
            'id': conn.id,
            'name': conn.name,
            'type': conn.type,
            'host': conn.host,
            'port': conn.port,
            'database': conn.database,
            'username': conn.username,
            'password': '********',
            'config': conn.config or {},
            'company_code': conn.company_code,
            'created_by_user_id': conn.created_by_user_id,
            'status': conn.status,
            'error_message': conn.error_message,
            'description': conn.description,
            'metamind_summary': conn.metamind_summary,
            'created_at': conn.created_at.isoformat() if conn.created_at else None,
            'updated_at': conn.updated_at.isoformat() if conn.updated_at else None,
            'last_tested': conn.last_tested.isoformat() if conn.last_tested else None
        }
    except Exception as e:
        print(f"Serialization error: {str(e)}")
        return {}

@bp.route('/', methods=['GET'])
@jwt_required()
def get_databases():
    """
    Lists database connections the current user created, plus any
    explicitly granted to them via Resource Mapping - nothing is
    auto-shared just for belonging to the same company.
    """
    current_user = get_current_user()
    if not current_user:
        return jsonify({'error': 'Authentication required', 'databases': []}), 401

    try:
        own = DatabaseConnection.query.filter_by(created_by_user_id=current_user.id).all()

        from app.models.resource_mapping import ResourceMapping
        granted_ids = [
            m.resource_id for m in ResourceMapping.query.filter_by(
                resource_type='database', user_id=current_user.id
            ).all()
        ]
        granted = DatabaseConnection.query.filter(DatabaseConnection.id.in_(granted_ids)).all() if granted_ids else []

        seen_ids = set()
        databases = []
        for conn in own + granted:
            if conn.id not in seen_ids:
                seen_ids.add(conn.id)
                databases.append(conn)

        return jsonify({
            'databases': [serialize_connection(conn) for conn in databases],
            'count': len(databases)
        }), 200
    except Exception as e:
        print(f"GET databases error: {str(e)}")
        print(traceback.format_exc())
        return jsonify({'error': str(e), 'databases': []}), 200

@bp.route('/', methods=['POST'])
@jwt_required()
def create_database_connection():
    """
    Create new database connection
    Request: { "name": "Production DB", "type": "PostgreSQL", "host": "...", 
               "port": 5432, "database": "mydb", "username": "...", "password": "..." }
    Response: { "database": {...}, "message": "Connection created" }
    """
    current_user = get_current_user()
    if not current_user:
        return jsonify({'error': 'Authentication required'}), 401

    try:
        data = request.get_json()

        # Validate required fields based on database type
        db_type = data.get('type', '')
        
        # Basic required fields for all types
        required_fields = ['name', 'type', 'username', 'password']
        
        # Add database field requirement based on type
        database_required = db_type not in ['ODBC', 'Others', 'BigQuery', 'Salesforce']
        if database_required:
            required_fields.append('database')
            
        for field in required_fields:
            if field not in data or not data[field] or (isinstance(data[field], str) and data[field].strip() == ''):
                return jsonify({'error': f'Missing required field: {field}'}), 400
                
        # For database types that don't require database name, set a default
        if not database_required and (not data.get('database') or data.get('database').strip() == ''):
            data['database'] = f"{db_type.lower()}_connection"
        
        # Create new connection
        connection = DatabaseConnection(
            name=data.get('name'),
            type=data.get('type'),
            host=data.get('host'),
            port=data.get('port'),
            database=data.get('database'),
            username=data.get('username'),
            password=data.get('password'),
            connection_string=data.get('connection_string'),
            config=data.get('config', {}),
            description=(data.get('description') or '').strip() or None,
            company_code=current_user.company_code,
            created_by_user_id=current_user.id,
            status='connected'
        )

        db.session.add(connection)
        db.session.commit()

        log_event('database_connection_created', company_code=current_user.company_code, user_id=current_user.id,
                   resource_type='database', resource_id=connection.id, details={'name': connection.name, 'type': connection.type})

        from app.services.automated_metamind import generate_router_config
        generate_router_config(user_id=current_user.id)

        return jsonify({
            'database': serialize_connection(connection),
            'message': 'Connection created successfully'
        }), 201
    except Exception as e:
        db.session.rollback()
        print(f"POST error: {str(e)}")
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500


@bp.route('/excel', methods=['POST'])
@jwt_required()
def create_excel_database():
    """
    Uploads an Excel or CSV file and turns each sheet (or the CSV itself)
    into a queryable table - WITHOUT writing it into Postgres. There's no
    spare warehouse to hold this data, and no SQL runs against it: each
    table is saved as a Parquet file (see spreadsheet_service.py) and
    queried through a separate pandas-based path, never SQL. Every sheet
    in a workbook becomes its own table; a CSV file becomes one.
    Request: multipart/form-data with fields 'name' (connection name) and
    'file' (.xlsx/.xls/.csv)
    """
    current_user = get_current_user()
    if not current_user:
        return jsonify({'error': 'Authentication required'}), 401

    try:
        name = request.form.get('name', '').strip()
        file = request.files.get('file')

        if not name:
            return jsonify({'error': 'Connection name is required'}), 400
        if not file or file.filename == '':
            return jsonify({'error': 'An Excel or CSV file is required'}), 400

        filename_lower = file.filename.lower()
        if filename_lower.endswith('.csv'):
            sheets = {None: pd.read_csv(file)}
        elif filename_lower.endswith(('.xlsx', '.xls')):
            # sheet_name=None reads every sheet in the workbook, not just
            # the first - each one becomes its own table below.
            sheets = pd.read_excel(file, sheet_name=None)
        else:
            return jsonify({'error': 'Only .xlsx, .xls, or .csv files are supported'}), 400

        sheets = {sheet_name: df for sheet_name, df in sheets.items() if not df.empty}
        if not sheets:
            return jsonify({'error': 'The file has no data rows'}), 400

        base_table_name = _sanitize_identifier(name)
        if not base_table_name:
            return jsonify({'error': 'Could not derive a valid table name from the connection name'}), 400

        # Row created first so its id is available to key the spreadsheet
        # files/manifest by - filled in with the resulting tables below.
        connection = DatabaseConnection(
            name=name,
            type='Excel',
            host=None,
            port=None,
            database=base_table_name,
            username=None,
            password=None,
            config={'source_tables': []},
            description=(request.form.get('description') or '').strip() or None,
            company_code=current_user.company_code,
            created_by_user_id=current_user.id,
            status='connected'
        )
        db.session.add(connection)
        db.session.commit()

        # Only suffix table names with the sheet when there's more than one -
        # keeps the common single-sheet/CSV case's table named exactly after
        # the connection, same as before.
        multi_sheet = len(sheets) > 1
        used_table_names = set()
        created_tables = []

        for sheet_name, df in sheets.items():
            if multi_sheet:
                table_name = _sanitize_identifier(f"{base_table_name}_{sheet_name}")
            else:
                table_name = base_table_name
            if table_name in used_table_names:
                table_name = _sanitize_identifier(f"{table_name}_{len(used_table_names) + 1}")
            used_table_names.add(table_name)

            df.columns = _dedupe_identifiers(df.columns)
            record = spreadsheet_service.save_table(connection.id, table_name, sheet_name, df)
            created_tables.append(record)

        spreadsheet_service.set_original_filename(connection.id, file.filename)
        connection.config = {
            'source_tables': [{'table': t['table'], 'sheet': t['sheet'], 'row_count': t['row_count']} for t in created_tables],
            'original_filename': file.filename,
            'row_count': sum(t['row_count'] for t in created_tables)
        }
        db.session.commit()

        from app.services.automated_metamind import generate_router_config
        generate_router_config(user_id=current_user.id)

        log_event('database_connection_created', company_code=current_user.company_code, user_id=current_user.id,
                   resource_type='database', resource_id=connection.id, details={'name': connection.name, 'type': 'Excel'})

        table_summary = ', '.join(f'"{t["table"]}" ({t["row_count"]} rows)' for t in created_tables)
        return jsonify({
            'database': serialize_connection(connection),
            'message': f'File uploaded: {table_summary}.'
        }), 201

    except Exception as e:
        db.session.rollback()
        print(f"POST /excel error: {str(e)}")
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

def _can_view_connection(user, connection):
    if connection.created_by_user_id == user.id:
        return True
    from app.models.resource_mapping import ResourceMapping
    return ResourceMapping.query.filter_by(resource_type='database', resource_id=connection.id, user_id=user.id).first() is not None


def _can_modify_connection(user, connection):
    if connection.created_by_user_id == user.id:
        return True
    return user.role == 'admin' and user.company_code and user.company_code == connection.company_code


@bp.route('/<int:db_id>', methods=['GET'])
@jwt_required()
def get_database(db_id):
    """
    Get specific database connection details
    Response: { "database": {...} }
    """
    current_user = get_current_user()
    if not current_user:
        return jsonify({'error': 'Authentication required'}), 401
    try:
        connection = DatabaseConnection.query.get(db_id)
        if not connection or not _can_view_connection(current_user, connection):
            return jsonify({'error': 'Connection not found'}), 404

        return jsonify({'database': serialize_connection(connection)}), 200
    except Exception as e:
        print(f"GET database error: {str(e)}")
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@bp.route('/<int:db_id>', methods=['PUT'])
@jwt_required()
def update_database_connection(db_id):
    """
    Update database connection
    Request: { "name": "...", "host": "...", ... }
    Response: { "database": {...}, "message": "Connection updated" }
    """
    current_user = get_current_user()
    if not current_user:
        return jsonify({'error': 'Authentication required'}), 401
    try:
        connection = DatabaseConnection.query.get(db_id)
        if not connection or not _can_modify_connection(current_user, connection):
            return jsonify({'error': 'Connection not found'}), 404

        data = request.get_json()

        # Update fields
        for key in ['name', 'host', 'port', 'database', 'username', 'password', 'connection_string', 'type', 'description']:
            if key in data:
                setattr(connection, key, data[key])

        db.session.commit()
        log_event('database_connection_updated', company_code=current_user.company_code, user_id=current_user.id,
                   resource_type='database', resource_id=connection.id)

        from app.services.automated_metamind import generate_router_config
        from app.models.resource_mapping import ResourceMapping
        affected_user_ids = {current_user.id, connection.created_by_user_id} | {
            m.user_id for m in ResourceMapping.query.filter_by(resource_type='database', resource_id=connection.id).all()
        }
        try:
            for uid in affected_user_ids:
                generate_router_config(user_id=uid)
            # generate_router_config()'s DB introspection already sets
            # connection.status/error_message directly on this row when it
            # can't reach the database (see automated_metamind.py's
            # _introspect_visible_databases) - only clear a stale error here
            # if this run didn't just set a fresh one.
            if connection.status != 'error':
                connection.status = 'connected'
                connection.error_message = None
        except Exception as e:
            print(f"Router config regeneration error after update: {e}")
            print(traceback.format_exc())
            connection.status = 'error'
            connection.error_message = 'Connection details were saved, but the AI router config could not be regenerated.'
        db.session.commit()

        return jsonify({
            'database': serialize_connection(connection),
            'message': 'Connection updated successfully' if connection.status != 'error' else connection.error_message
        }), 200
    except Exception as e:
        db.session.rollback()
        print(f"PUT error: {str(e)}")
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@bp.route('/<int:db_id>', methods=['DELETE'])
@jwt_required()
def delete_database_connection(db_id):
    """
    Delete database connection
    Response: { "message": "Connection deleted" }
    """
    current_user = get_current_user()
    if not current_user:
        return jsonify({'error': 'Authentication required'}), 401
    try:
        connection = DatabaseConnection.query.get(db_id)
        if not connection or not _can_modify_connection(current_user, connection):
            return jsonify({'error': 'Connection not found'}), 404

        is_excel = (connection.type or '').lower() == 'excel'
        connection_id = connection.id
        db.session.delete(connection)
        db.session.commit()

        if is_excel:
            spreadsheet_service.delete_connection_tables(db_id)

        log_event('database_connection_deleted', company_code=current_user.company_code, user_id=current_user.id,
                   resource_type='database', resource_id=connection_id)

        # No router config to refresh - it's computed live on every chat
        # query, so a deleted connection simply stops appearing on the
        # very next query with nothing to proactively clear.

        return jsonify({'message': 'Connection deleted successfully'}), 200
    except Exception as e:
        db.session.rollback()
        print(f"DELETE error: {str(e)}")
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@bp.route('/<int:db_id>/test', methods=['POST'])
@jwt_required()

def test_database_connection(db_id):
    """
    Test database connection
    Response: { "status": "success/failed", "latency_ms": 45, "error": null }
    """
    try:
        connection = DatabaseConnection.query.get(db_id)
        if not connection:
            return jsonify({'error': 'Connection not found'}), 404
        
        start_time = time.time()
        
        try:
            if connection.type == 'PostgreSQL':
                try:
                    import psycopg2
                    conn = psycopg2.connect(
                        host=connection.host,
                        port=connection.port or 5432,
                        database=connection.database,
                        user=connection.username,
                        password=connection.password,
                        connect_timeout=5
                    )
                    conn.close()
                except ImportError:
                    pass  # psycopg2 not installed
            elif connection.type == 'MySQL':
                try:
                    import mysql.connector
                    conn = mysql.connector.connect(
                        host=connection.host,
                        port=connection.port or 3306,
                        database=connection.database,
                        user=connection.username,
                        password=connection.password,
                        connection_timeout=5
                    )
                    conn.close()
                except ImportError:
                    pass  # mysql.connector not installed
            
            latency_ms = (time.time() - start_time) * 1000
            return jsonify({
                'status': 'success',
                'latency_ms': round(latency_ms, 2),
                'error': None
            }), 200
        except Exception as test_error:
            latency_ms = (time.time() - start_time) * 1000
            return jsonify({
                'status': 'failed',
                'latency_ms': round(latency_ms, 2),
                'error': str(test_error)
            }), 200
    except Exception as e:
        print(f"Test connection error: {str(e)}")
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500


def _summarize_spreadsheet_table_for_metamind(table_name: str) -> str:
    """Asks an LLM to describe what a spreadsheet-backed table actually
    contains (e.g. "Player roster with season-by-season performance
    stats") from its columns and a few sample rows, then stores that on
    the table's manifest record. automated_metamind.py's spreadsheet
    introspection reads that description and uses it when building each
    user's router config - this is the one place that generates it."""
    df = spreadsheet_service.get_table_df(table_name)
    sample = df.head(5)
    sample_text = "\n".join(
        ", ".join(f"{col}={row[col]}" for col in df.columns)
        for _, row in sample.iterrows()
    )

    from langchain_openai import ChatOpenAI
    from langchain_core.messages import SystemMessage, HumanMessage

    prompt = (
        f"Table name: {table_name}\n"
        f"Columns: {', '.join(df.columns)}\n"
        f"Sample rows:\n{sample_text}\n\n"
        "In one short sentence, describe what this table contains in "
        "plain business language (e.g. \"Player roster with season-by-"
        "season performance stats\"). Output only that sentence, no "
        "quotes, no preamble."
    )
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.2, openai_api_key=os.getenv("OPENAI_API_KEY"))
    response = llm.invoke([
        SystemMessage(content="You write single-sentence, plain-language summaries of spreadsheet tables."),
        HumanMessage(content=prompt),
    ])
    description = (response.content or "").strip().strip('"')
    if not description:
        description = f"Table storing {table_name} records."

    spreadsheet_service.set_table_description(table_name, description)
    return description


@bp.route('/<int:db_id>/process', methods=['POST'])
@jwt_required()
def process_database_connection(db_id):
    """
    Explicit process action for a saved database connection.
    For Excel/CSV connections, generates a content-aware summary of each
    table (via LLM) and stores it as the table's description so the router
    can tell what it's actually useful for - then regenerates the router
    config (for whoever can currently see this connection) either way.
    """
    current_user = get_current_user()
    if not current_user:
        return jsonify({"status": "error", "message": "Authentication required"}), 401
    try:
        connection = DatabaseConnection.query.get(db_id)
        if not connection or not _can_view_connection(current_user, connection):
            return jsonify({"status": "error", "message": "Connection not found"}), 404

        from app.services.automated_metamind import generate_router_config
        from app.models.resource_mapping import ResourceMapping
        affected_user_ids = {current_user.id, connection.created_by_user_id} | {
            m.user_id for m in ResourceMapping.query.filter_by(resource_type='database', resource_id=connection.id).all()
        }

        if (connection.type or '').lower() == 'excel':
            tables = [t['table'] for t in spreadsheet_service.get_tables_for_connection(connection.id)]

            if not tables:
                connection.status = 'error'
                connection.error_message = 'No tables found for this connection.'
                db.session.commit()
                return jsonify({"status": "error", "message": "No tables found for this connection."}), 404

            try:
                for table_name in tables:
                    _summarize_spreadsheet_table_for_metamind(table_name)
            except Exception as e:
                print(f"Table summarization error: {e}")
                print(traceback.format_exc())
                connection.status = 'error'
                connection.error_message = 'Something went wrong while summarizing these tables. Please try again.'
                db.session.commit()
                return jsonify({"status": "error", "message": "Something went wrong while summarizing these tables. Please try again."}), 500

            for uid in affected_user_ids:
                generate_router_config(user_id=uid)
            connection.status = 'processed'
            connection.error_message = None
            db.session.commit()
            described = ", ".join(f'"{t}"' for t in tables)
            return jsonify({
                "status": "success",
                "message": f"Tables ready for queries: {described}."
            })

        try:
            if (connection.type or '').lower() == 'postgresql':
                # Best-effort: writes an LLM-generated description back onto
                # any table this connection can see that has no real
                # COMMENT ON TABLE yet (e.g. unlabeled SAP-replica tables
                # like MARA/VBAK/KNA1) - see enrich_table_descriptions_with_
                # llm()'s docstring for why this persists via COMMENT ON
                # TABLE rather than a separate store, and why it's safe to
                # run every time Process is clicked (already-commented
                # tables are left untouched).
                from app.services.automated_metamind import enrich_table_descriptions_with_llm
                from app.utils.crypto import decrypt
                try:
                    enrich_table_descriptions_with_llm(
                        {
                            "host": connection.host,
                            "port": connection.port or 5432,
                            "dbname": connection.database,
                            "user": connection.username,
                            "password": decrypt(connection.password) if connection.password else "",
                        },
                        connection_description=connection.description,
                    )
                except Exception as e:
                    print(f"⚠️ Table description enrichment failed for connection {connection.id}: {e}")

            for uid in affected_user_ids:
                generate_router_config(user_id=uid)
            # generate_router_config()'s DB introspection already sets
            # connection.status/error_message directly on this row when it
            # can't reach the database - don't clobber an 'error' it just
            # set with a blanket 'processed'.
            if connection.status == 'error':
                db.session.commit()
                return jsonify({"status": "error", "message": connection.error_message or "Could not connect to this database."}), 502
            connection.status = 'processed'
            connection.error_message = None
            db.session.commit()
            return jsonify({"status": "success", "message": "This connection's tables are now ready for queries."})
        except Exception as e:
            print(f"Router config regeneration error: {e}")
            connection.status = 'error'
            connection.error_message = 'Something went wrong while activating this connection. Please try again.'
            db.session.commit()
            return jsonify({"status": "error", "message": "Something went wrong while activating this connection. Please try again."}), 500
    except Exception as e:
        print(f"Process connection error: {str(e)}")
        print(traceback.format_exc())
        try:
            connection.status = 'error'
            connection.error_message = str(e)
            db.session.commit()
        except Exception:
            db.session.rollback()
        return jsonify({"status": "error", "message": "Something went wrong. Please try again."}), 500


@bp.route('/test', methods=['POST'])
@jwt_required()
def test_new_connection():
    """
    Test a new database connection (before saving)
    Request: { "type": "PostgreSQL", "host": "...", "port": 5432, ... }
    Response: { "status": "success/failed", "latency_ms": 45, "error": null }
    """
    try:
        data = request.get_json()
        start_time = time.time()
        
        try:
            if data.get('type') == 'PostgreSQL':
                try:
                    import psycopg2
                    conn = psycopg2.connect(
                        host=data.get('host'),
                        port=data.get('port', 5432),
                        database=data.get('database'),
                        user=data.get('username'),
                        password=data.get('password'),
                        connect_timeout=5
                    )
                    conn.close()
                except ImportError:
                    pass

            elif data.get('type') == 'MySQL':
                try:
                    import mysql.connector
                    conn = mysql.connector.connect(
                        host=data.get('host'),
                        port=data.get('port', 3306),
                        database=data.get('database'),
                        user=data.get('username'),
                        password=data.get('password'),
                        connection_timeout=5
                    )
                    conn.close()
                except ImportError:
                    pass
            
            latency_ms = (time.time() - start_time) * 1000
            return jsonify({
                'status': 'success',
                'latency_ms': round(latency_ms, 2),
                'error': None
            }), 200
        except Exception as test_error:
            latency_ms = (time.time() - start_time) * 1000
            return jsonify({
                'status': 'failed',
                'latency_ms': round(latency_ms, 2),
                'error': str(test_error)
            }), 200
    except Exception as e:
        print(f"Test new connection error: {str(e)}")
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@bp.route('/<int:db_id>/schema', methods=['GET'])
@jwt_required()
def get_database_schema(db_id):
    """
    Get database schema (tables, columns, relationships)
    Response: { "schema": {tables: [{name, columns: [...]}]} }
    """
    try:
        connection = DatabaseConnection.query.get(db_id)
        if not connection:
            return jsonify({'error': 'Connection not found'}), 404
        
        return jsonify({
            'schema': {'tables': []}
        }), 200
    except Exception as e:
        print(f"Schema error: {str(e)}")
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@bp.route('/<int:db_id>/tables', methods=['GET'])
@jwt_required()
def get_database_tables(db_id):
    """
    Get list of tables in database
    Response: { "tables": ["users", "orders", "products", ...] }
    """
    try:
        connection = DatabaseConnection.query.get(db_id)
        if not connection:
            return jsonify({'error': 'Connection not found'}), 404
        
        return jsonify({'tables': []}), 200
    except Exception as e:
        print(f"Tables error: {str(e)}")
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@bp.route('/<int:db_id>/tables/<string:table_name>/columns', methods=['GET'])
@jwt_required()
def get_table_columns(db_id, table_name):
    """
    Get columns for specific table
    Response: { "columns": [{name, type, nullable, primary_key}] }
    """
    try:
        connection = DatabaseConnection.query.get(db_id)
        if not connection:
            return jsonify({'error': 'Connection not found'}), 404
        
        return jsonify({'columns': []}), 200
    except Exception as e:
        print(f"Columns error: {str(e)}")
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@bp.route('/types', methods=['GET'])
@jwt_required()
def get_database_types():
    """
    Get supported database types
    Response: { "types": ["PostgreSQL", "MySQL", "MongoDB", "SQL Server", "Oracle", "BigQuery"] }
    """
    types = [
        'PostgreSQL', 'MySQL', 'MongoDB', 'SQL Server', 'Oracle',
        'BigQuery', 'Snowflake', 'Redis', 'SAP HANA', 'Salesforce', 'ODBC', 'Excel'
    ]
    return jsonify({'types': types}), 200

@bp.route('/run-agentic-process/<int:conn_id>', methods=['POST'])
@jwt_required()
def run_agentic_process(conn_id):
    """
    Runs the SAP-style demo-data seeding (db.py) and schema/comment
    generation (metamind.py) against the external database registered as
    connection `conn_id` - neither script assumes a local Docker network
    or any app-internal database, they connect to whatever host/port/
    credentials are stored on this DatabaseConnection record.
    """
    current_user = get_current_user()
    if not current_user:
        return jsonify({"error": "Authentication required"}), 401

    connection = DatabaseConnection.query.get(conn_id)
    if not connection or not (
        connection.created_by_user_id == current_user.id
        or (current_user.role == 'admin' and current_user.company_code == connection.company_code)
    ):
        return jsonify({"error": "Connection not found"}), 404

    if not connection.host or not connection.database or not connection.username:
        return jsonify({"error": "This connection is missing host/database/username - edit it before running the agentic process."}), 400

    from app.utils.crypto import decrypt

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    # Relative to wherever the app actually runs from, not a hardcoded
    # container path - the same "assumed one specific machine's layout"
    # mistake that broke this endpoint before.
    log_dir = os.path.join(os.getcwd(), 'logs')
    log_path = os.path.join(log_dir, f"process_{conn_id}_{timestamp}.log")
    os.makedirs(log_dir, exist_ok=True)

    logger_name = f"process_{conn_id}_{timestamp}"
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    # Ensure we don't duplicate handlers if this logger name is reused.
    for existing_handler in list(logger.handlers):
        logger.removeHandler(existing_handler)

    handler = logging.FileHandler(log_path)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(handler)

    logger.info(f"Process started for connection ID: {conn_id} (host={connection.host})")
    try:
        # Resolved relative to this file, not a hardcoded container path -
        # works no matter where the repo actually lives on disk.
        base_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'services', 'databridge_services')
        db_script = os.path.join(base_path, "db.py")
        meta_script = os.path.join(base_path, "metamind.py")

        # The target database's credentials are passed via environment,
        # not CLI args (which would leak the password into `ps aux`
        # output for any user on the box) and not read from any
        # app-internal fallback - db.py/metamind.py only ever connect to
        # whatever this specific DatabaseConnection record points at.
        subprocess_env = dict(os.environ)
        subprocess_env.update({
            "DATABRIDGE_TARGET_HOST": connection.host,
            "DATABRIDGE_TARGET_PORT": str(connection.port or 5432),
            "DATABRIDGE_TARGET_DBNAME": connection.database,
            "DATABRIDGE_TARGET_USER": connection.username,
            "DATABRIDGE_TARGET_PASSWORD": decrypt(connection.password) if connection.password else "",
        })

        # Step 1: Build SAP tables
        logger.info(f"Step 1 [build_sap_tables] start | conn_id={conn_id} | script={db_script}")
        result1 = subprocess.run(
            [sys.executable, db_script],
            check=True,
            timeout=5000,
            capture_output=True,
            text=True,
            env=subprocess_env,
        )
        logger.info(f"Step 1 stdout:\n{result1.stdout}")
        logger.info(f"Step 1 stderr:\n{result1.stderr}")
        logger.info("Step 1 completed successfully")

        time.sleep(5)

        # Step 2: Running the 40-minute LLM analysis
        logger.info(f"Step 2 [metamind_analysis] start | conn_id={conn_id} | script={meta_script}")
        result2 = subprocess.run(
            [sys.executable, meta_script],
            check=True,
            timeout=5000,
            capture_output=True,
            text=True,
            env=subprocess_env,
        )
        logger.info(f"Step 2 stdout:\n{result2.stdout}")
        logger.info(f"Step 2 stderr:\n{result2.stderr}")
        logger.info("Step 2 completed successfully")
        logger.info("Process finished successfully, regenerating router config")

        # Passed explicitly rather than relying on DATABRIDGE_TARGET_* env
        # vars - those were only ever set on the subprocess above, not
        # this parent process's own environment.
        from app.services.automated_metamind import generate_router_config
        from app.models.resource_mapping import ResourceMapping
        sap_db_config = {
            "host": connection.host,
            "port": connection.port or 5432,
            "dbname": connection.database,
            "user": connection.username,
            "password": decrypt(connection.password) if connection.password else "",
        }
        affected_user_ids = {current_user.id, connection.created_by_user_id} | {
            m.user_id for m in ResourceMapping.query.filter_by(resource_type='database', resource_id=connection.id).all()
        }
        for uid in affected_user_ids:
            generate_router_config(user_id=uid, sap_db_config=sap_db_config)

        log_event('agentic_process_run', company_code=current_user.company_code, user_id=current_user.id,
                   resource_type='database', resource_id=conn_id, details={'log_path': log_path})

        return jsonify({"status": "success", "message": "Successfully JSON file created!", "log_path": log_path}), 200

    except subprocess.CalledProcessError as e:
        logger.error(f"Script crashed: {e}")
        logger.error(f"stdout:\n{e.stdout}")
        logger.error(f"stderr:\n{e.stderr}")
        return jsonify({"error": f"Script failed: {e.stderr or str(e)}", "log_path": log_path}), 500
    except Exception as e:
        logger.error(f"Unexpected system error: {e}", exc_info=True)
        return jsonify({"error": str(e), "log_path": log_path}), 500
    finally:
        handler.close()
        logger.removeHandler(handler)