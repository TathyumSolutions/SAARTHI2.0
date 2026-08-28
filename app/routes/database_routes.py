"""
Database Connection API Routes
Handles database connections, schema discovery, and connection testing
"""
import time
import traceback
import re
import io
from flask import Blueprint, request, jsonify, send_file
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
from app.services import spreadsheet_warehouse_service
from app.services import spreadsheet_matching_service
from app.utils.auth_helpers import get_current_user
from app.utils.identifiers import sanitize_identifier as _sanitize_identifier, dedupe_identifiers as _dedupe_identifiers
from app.services.audit_service import log_event

bp = Blueprint('database', __name__, url_prefix='/api/databases')


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
    into its own independent datasource - WITHOUT writing it into
    Postgres. There's no spare warehouse to hold this data, and no SQL
    runs against it: each table is saved as a Parquet file (see
    spreadsheet_service.py) and queried through a separate pandas-based
    path, never SQL.

    Each sheet becomes its own DatabaseConnection row, not one row per
    uploaded file with sheets bundled invisibly inside it - so every
    sheet gets its own place in the Knowledge Base / Data Sources list,
    its own Process/Description/Details lifecycle, and its own Resource
    Mapping sharing grant, the same first-class treatment any other
    single-table connection gets. A CSV file (which has no sheets) still
    produces exactly one connection, same as before.
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
            # the first - each one becomes its own connection below.
            sheets = pd.read_excel(file, sheet_name=None)
        else:
            return jsonify({'error': 'Only .xlsx, .xls, or .csv files are supported'}), 400

        sheets = {sheet_name: df for sheet_name, df in sheets.items() if not df.empty}
        if not sheets:
            return jsonify({'error': 'The file has no data rows'}), 400

        base_table_name = _sanitize_identifier(name)
        if not base_table_name:
            return jsonify({'error': 'Could not derive a valid table name from the connection name'}), 400

        # Only suffix table/connection names with the sheet when there's
        # more than one - keeps the common single-sheet/CSV case named
        # exactly after the connection, same as before.
        multi_sheet = len(sheets) > 1
        used_table_names = set()
        custom_description = (request.form.get('description') or '').strip() or None
        created_connections = []
        created_tables = []

        for sheet_name, df in sheets.items():
            if multi_sheet:
                table_name = _sanitize_identifier(f"{base_table_name}_{sheet_name}")
                connection_name = f"{name}_{sheet_name}"
            else:
                table_name = base_table_name
                connection_name = name
            if table_name in used_table_names:
                table_name = _sanitize_identifier(f"{table_name}_{len(used_table_names) + 1}")
            used_table_names.add(table_name)

            # Row created first so its id is available to key the
            # spreadsheet manifest by - filled in with the resulting
            # table right after.
            connection = DatabaseConnection(
                name=connection_name,
                type='Excel',
                host=None,
                port=None,
                database=table_name,
                username=None,
                password=None,
                config={'source_tables': []},
                description=custom_description,
                company_code=current_user.company_code,
                created_by_user_id=current_user.id,
                status='connected'
            )
            db.session.add(connection)
            db.session.commit()

            df.columns = _dedupe_identifiers(df.columns)
            record = spreadsheet_service.save_table(connection.id, table_name, sheet_name, df)
            spreadsheet_service.set_original_filename(connection.id, file.filename)
            connection.config = {
                'source_tables': [{'table': record['table'], 'sheet': record['sheet'], 'row_count': record['row_count']}],
                'original_filename': file.filename,
                'row_count': record['row_count'],
            }
            db.session.commit()

            created_connections.append(connection)
            created_tables.append(record)

        from app.services.automated_metamind import generate_router_config
        generate_router_config(user_id=current_user.id)

        for connection in created_connections:
            log_event('database_connection_created', company_code=current_user.company_code, user_id=current_user.id,
                       resource_type='database', resource_id=connection.id, details={'name': connection.name, 'type': 'Excel'})

        table_summary = ', '.join(f'"{t["table"]}" ({t["row_count"]} rows)' for t in created_tables)
        return jsonify({
            'database': serialize_connection(created_connections[0]),
            'databases': [serialize_connection(c) for c in created_connections],
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

def _excel_sheet_names(tables):
    """Unique, <=31-char sheet names (Excel's own limit) for a set of
    spreadsheet_service table records, preserving their stored sheet name
    where possible."""
    used = set()
    names = []
    for table in tables:
        base = (table.get('sheet') or table['table'])[:31] or table['table'][:31]
        name = base
        n = 2
        while name in used:
            suffix = f"_{n}"
            name = base[:31 - len(suffix)] + suffix
            n += 1
        used.add(name)
        names.append(name)
    return names


@bp.route('/<int:db_id>/download', methods=['GET'])
@jwt_required()
def download_excel_connection(db_id):
    """Reconstructs a .xlsx from this connection's Parquet-backed table(s) -
    there's no original upload kept on disk (create_excel_database parses
    straight into Parquet), so this is generated on demand, one sheet per
    table for connections that still hold more than one (a shape from
    before Excel connections were split one-table-per-connection)."""
    current_user = get_current_user()
    if not current_user:
        return jsonify({'error': 'Authentication required'}), 401

    connection = DatabaseConnection.query.get(db_id)
    if not connection or not _can_view_connection(current_user, connection):
        return jsonify({'error': 'Connection not found'}), 404
    if (connection.type or '').lower() != 'excel':
        return jsonify({'error': 'Download is only available for spreadsheet connections'}), 400

    tables = spreadsheet_service.get_tables_for_connection(db_id)
    if not tables:
        return jsonify({'error': 'No data found for this connection - the uploaded file may be missing.'}), 404

    sheet_names = _excel_sheet_names(tables)
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        for table, sheet_name in zip(tables, sheet_names):
            spreadsheet_service.get_table_df(table['table']).to_excel(writer, sheet_name=sheet_name, index=False)
    buffer.seek(0)

    download_name = _sanitize_identifier(connection.name) or f"connection_{db_id}"
    return send_file(
        buffer,
        as_attachment=True,
        download_name=f"{download_name}.xlsx",
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )


@bp.route('/<int:db_id>/preview', methods=['GET'])
@jwt_required()
def preview_excel_connection(db_id):
    """First 50 rows of every table under this connection, for the
    Spreadsheet page's 'View' action - a raw file preview doesn't make
    sense here since there's no original file, only Parquet-backed data."""
    current_user = get_current_user()
    if not current_user:
        return jsonify({'error': 'Authentication required'}), 401

    connection = DatabaseConnection.query.get(db_id)
    if not connection or not _can_view_connection(current_user, connection):
        return jsonify({'error': 'Connection not found'}), 404
    if (connection.type or '').lower() != 'excel':
        return jsonify({'error': 'Preview is only available for spreadsheet connections'}), 400

    tables = spreadsheet_service.get_tables_for_connection(db_id)
    if not tables:
        return jsonify({'error': 'No data found for this connection - the uploaded file may be missing.'}), 404

    import json as _json
    preview_tables = []
    for table in tables:
        df = spreadsheet_service.get_table_df(table['table'])
        head = df.head(50)
        preview_tables.append({
            'table': table['table'],
            'sheet': table.get('sheet'),
            'columns': list(df.columns),
            'rows': _json.loads(head.to_json(orient='records', date_format='iso')),
            'row_count': len(df),
            'truncated': len(df) > 50,
        })

    return jsonify({'status': 'success', 'tables': preview_tables}), 200


@bp.route('/<int:db_id>/excel', methods=['PUT'])
@jwt_required()
def update_excel_connection(db_id):
    """
    Renames/re-describes an Excel connection, and optionally replaces its
    single table's data with a newly uploaded single-sheet Excel/CSV file -
    the "Edit" flow on the Spreadsheet page. Deliberately restricted to
    connections backing exactly one table, uploading exactly one sheet:
    Excel connections are one-table-per-connection everywhere else in the
    app (router config, chat table lookups), so letting an edit reshape
    that into a different table count would break those invariants -
    delete and re-upload instead for that case.
    """
    current_user = get_current_user()
    if not current_user:
        return jsonify({'error': 'Authentication required'}), 401

    connection = DatabaseConnection.query.get(db_id)
    if not connection or not _can_modify_connection(current_user, connection):
        return jsonify({'error': 'Connection not found'}), 404
    if (connection.type or '').lower() != 'excel':
        return jsonify({'error': 'This endpoint is only for spreadsheet connections'}), 400

    try:
        name = (request.form.get('name') or '').strip()
        if name:
            connection.name = name

        if 'description' in request.form:
            connection.description = request.form.get('description', '').strip() or None

        file = request.files.get('file')
        if file and file.filename:
            existing_tables = spreadsheet_service.get_tables_for_connection(db_id)
            if len(existing_tables) > 1:
                return jsonify({
                    'error': 'This connection has multiple tables bundled together - replacing its file '
                             'isn\'t supported here. Delete this connection and re-upload instead.'
                }), 400

            filename_lower = file.filename.lower()
            if filename_lower.endswith('.csv'):
                sheets = {None: pd.read_csv(file)}
            elif filename_lower.endswith(('.xlsx', '.xls')):
                sheets = pd.read_excel(file, sheet_name=None)
            else:
                return jsonify({'error': 'Only .xlsx, .xls, or .csv files are supported'}), 400

            sheets = {sheet_name: df for sheet_name, df in sheets.items() if not df.empty}
            if not sheets:
                return jsonify({'error': 'The file has no data rows'}), 400
            if len(sheets) > 1:
                return jsonify({
                    'error': 'This connection holds a single table - upload a single-sheet Excel or CSV to '
                              'replace it. For a multi-sheet file, delete this connection and upload it fresh '
                              'so each sheet gets its own connection.'
                }), 400

            sheet_name, df = next(iter(sheets.items()))
            table_name = existing_tables[0]['table'] if existing_tables else (
                _sanitize_identifier(connection.database or connection.name)
            )

            df.columns = _dedupe_identifiers(df.columns)
            record = spreadsheet_service.save_table(connection.id, table_name, sheet_name, df)
            spreadsheet_service.set_original_filename(connection.id, file.filename)
            connection.config = {
                'source_tables': [{'table': record['table'], 'sheet': record['sheet'], 'row_count': record['row_count']}],
                'original_filename': file.filename,
                'row_count': record['row_count'],
            }
            # Stale after a data swap - Process regenerates it against the new data.
            connection.metamind_summary = None
            connection.status = 'connected'
            connection.error_message = None

        db.session.commit()

        from app.services.automated_metamind import generate_router_config
        from app.models.resource_mapping import ResourceMapping
        affected_user_ids = {current_user.id, connection.created_by_user_id} | {
            m.user_id for m in ResourceMapping.query.filter_by(resource_type='database', resource_id=connection.id).all()
        }
        for uid in affected_user_ids:
            generate_router_config(user_id=uid)

        log_event('database_connection_updated', company_code=current_user.company_code, user_id=current_user.id,
                   resource_type='database', resource_id=connection.id)

        return jsonify({'database': serialize_connection(connection), 'message': 'Connection updated successfully'}), 200
    except Exception as e:
        db.session.rollback()
        print(f"PUT /excel error: {str(e)}")
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


@bp.route('/<int:db_id>/match-candidates', methods=['GET'])
@jwt_required()
def get_match_candidates(db_id):
    """
    Returns existing warehouse tables that might be the same logical
    table as this connection's data - powers the "use existing table"
    checkbox shown before Process. See spreadsheet_matching_service.py
    for the matching pipeline; nothing here writes anything.
    Response: { "status": "success", "candidates": {"<table>": [ {...}, ... ]} }
    """
    current_user = get_current_user()
    if not current_user:
        return jsonify({"status": "error", "message": "Authentication required"}), 401

    connection = DatabaseConnection.query.get(db_id)
    if not connection or not _can_view_connection(current_user, connection):
        return jsonify({"status": "error", "message": "Connection not found"}), 404
    if (connection.type or '').lower() != 'excel':
        return jsonify({"status": "error", "message": "Matching is only available for spreadsheet connections"}), 400

    table_records = spreadsheet_service.get_tables_for_connection(connection.id)
    if not table_records:
        return jsonify({"status": "error", "message": "No data found for this connection."}), 404

    try:
        candidates_by_table = {
            record['table']: spreadsheet_matching_service.match_candidates_for_table(
                record.get('columns', []), connection.name, connection,
            )
            for record in table_records
        }
        return jsonify({"status": "success", "candidates": candidates_by_table}), 200
    except Exception as e:
        print(f"Match candidates error: {e}")
        print(traceback.format_exc())
        return jsonify({"status": "error", "message": "Could not compute match candidates. Please try again."}), 500


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
            table_records = spreadsheet_service.get_tables_for_connection(connection.id)
            tables = [t['table'] for t in table_records]

            if not tables:
                # The most common cause: this connection's row survived in
                # the database, but the actual parquet file/manifest entry
                # it points to is gone from disk (e.g. the uploads volume
                # wasn't persisted across a container rebuild - see
                # docker-compose.yml's uploads_data volume). There's no
                # data left to recover here; re-uploading is the only fix.
                message = 'No data found for this connection - the uploaded file may be missing. Please delete this connection and re-upload the file.'
                connection.status = 'error'
                connection.error_message = message
                db.session.commit()
                return jsonify({"status": "error", "message": message}), 404

            # Optional per-table "use existing table" selections from the
            # checkbox shown after /match-candidates - {"<table>": {
            # "use_existing_table_id": <id>, "column_mapping": {...}}}.
            # Absent/empty means "create or append to this connection's
            # own table", the existing behavior.
            payload = request.get_json(silent=True) or {}
            table_selections = payload.get('table_selections') or {}

            # Push each table into the dedicated Postgres warehouse first -
            # this is the actual "Process" action now. A hard failure here
            # (e.g. the spreadsheet_db bind is unreachable) fails the whole
            # request; a bad row within an otherwise-good upload does not -
            # see spreadsheet_warehouse_service.bulk_insert_rows.
            try:
                push_runs = []
                for record in table_records:
                    df = spreadsheet_service.get_table_df(record['table'])
                    selection = table_selections.get(record['table']) or {}
                    run = spreadsheet_warehouse_service.push_table_to_warehouse(
                        connection_id=connection.id,
                        table_name=record['table'],
                        sheet_name=record.get('sheet'),
                        display_name=connection.name,
                        df=df,
                        company_code=connection.company_code,
                        created_by_user_id=connection.created_by_user_id,
                        use_existing_table_id=selection.get('use_existing_table_id'),
                        column_mapping=selection.get('column_mapping'),
                    )
                    push_runs.append(run)
            except ValueError as e:
                connection.status = 'error'
                connection.error_message = str(e)
                db.session.commit()
                return jsonify({"status": "error", "message": str(e)}), 400
            except Exception as e:
                print(f"Warehouse push error: {e}")
                print(traceback.format_exc())
                connection.status = 'error'
                connection.error_message = 'Could not push this data into the database. Please try again.'
                db.session.commit()
                return jsonify({"status": "error", "message": connection.error_message}), 500

            # Best-effort content summarization for the AI router - doesn't
            # block success now that the warehouse push above is the
            # primary outcome of clicking Process.
            try:
                for table_name in tables:
                    _summarize_spreadsheet_table_for_metamind(table_name)
            except Exception as e:
                print(f"Table summarization error: {e}")
                print(traceback.format_exc())

            for uid in affected_user_ids:
                generate_router_config(user_id=uid)

            total_success = sum(r.success_rows for r in push_runs)
            total_errors = sum(r.error_rows for r in push_runs)
            connection.status = 'processed'
            connection.error_message = None
            db.session.commit()

            described = ", ".join(f'"{t}"' for t in tables)
            message = f"Pushed {total_success} row(s) into the database"
            message += f", {total_errors} row(s) failed - see run details." if total_errors else "."
            message += f" Tables ready for queries: {described}."
            return jsonify({
                "status": "success" if not total_errors else "partial_error",
                "message": message,
                "runs": [r.to_dict() for r in push_runs],
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