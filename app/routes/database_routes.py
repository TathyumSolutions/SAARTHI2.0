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
from psycopg2 import sql as pgsql
from flask_jwt_extended import jwt_required

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


def _infer_pg_type(series: pd.Series) -> str:
    """Maps a pandas column's inferred dtype to a real Postgres type,
    instead of creating every column as TEXT regardless of content. All-TEXT
    columns silently break anything that relies on actual comparison
    semantics (numeric filters/aggregates, date ranges, sorting), since
    e.g. "9" > "10" as strings - this is the SQL-side "cleaning" a numeric
    or date column needs, not a separate execution engine."""
    non_null = series.dropna()
    if non_null.empty:
        return "TEXT"
    if pd.api.types.is_bool_dtype(series):
        return "BOOLEAN"
    if pd.api.types.is_integer_dtype(series):
        return "BIGINT"
    if pd.api.types.is_float_dtype(series):
        return "DOUBLE PRECISION"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "TIMESTAMP"
    return "TEXT"


def _format_cell_for_type(value, pg_type: str):
    """Converts a pandas cell value into something psycopg2 can bind
    correctly for the target column type."""
    if pd.isna(value):
        return None
    if pg_type == "BOOLEAN":
        return bool(value)
    if pg_type == "BIGINT":
        return int(value)
    if pg_type == "DOUBLE PRECISION":
        return float(value)
    if pg_type == "TIMESTAMP":
        return value.to_pydatetime() if hasattr(value, "to_pydatetime") else value
    return str(value)


def _get_databridge_db_config():
    return {
        "host": os.getenv("DATABRIDGE_DB_HOST", os.getenv("PGHOST", "db")),
        "port": os.getenv("DATABRIDGE_DB_PORT", os.getenv("PGPORT", "5432")),
        "dbname": os.getenv("DATABRIDGE_DB_NAME", os.getenv("PGDATABASE", "databrige_db")),
        "user": os.getenv("DATABRIDGE_DB_USER", os.getenv("PGUSER", "saarthi")),
        "password": os.getenv("DATABRIDGE_DB_PASSWORD", os.getenv("PGPASSWORD", "password")),
    }

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
            'workspace_id': conn.workspace_id,
            'status': conn.status,
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
    Get all configured database connections
    Query params: workspace_id
    Response: { "databases": [{id, name, type, host, status}] }
    """
    try:
        workspace_id = request.args.get('workspace_id', 1)
        
        try:
            if workspace_id:
                databases = DatabaseConnection.query.filter_by(workspace_id=workspace_id).all()
            else:
                databases = DatabaseConnection.query.all()
        except Exception as query_error:
            # If query fails (table might not exist), return empty list
            print(f"Query error: {str(query_error)}")
            databases = []
        
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
            workspace_id=data.get('workspace_id', 1),
            status='connected'
        )
        
        db.session.add(connection)
        db.session.commit()
        
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
    Uploads an Excel or CSV file and turns it into one or more queryable
    tables, treated exactly like a normal database connection. Every sheet
    in an Excel workbook becomes its own table; a CSV file becomes one.
    Request: multipart/form-data with fields 'name' (connection name) and
    'file' (.xlsx/.xls/.csv)
    """
    conn = None
    cursor = None
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

        # Only suffix table names with the sheet when there's more than one -
        # keeps the common single-sheet/CSV case's table named exactly after
        # the connection, same as before.
        multi_sheet = len(sheets) > 1
        used_table_names = set()
        created_tables = []

        conn = psycopg2.connect(**_get_databridge_db_config())
        conn.autocommit = True
        cursor = conn.cursor()

        for sheet_name, df in sheets.items():
            if multi_sheet:
                table_name = _sanitize_identifier(f"{base_table_name}_{sheet_name}")
            else:
                table_name = base_table_name
            if table_name in used_table_names:
                table_name = _sanitize_identifier(f"{table_name}_{len(used_table_names) + 1}")
            used_table_names.add(table_name)

            df.columns = _dedupe_identifiers(df.columns)
            col_types = {col: _infer_pg_type(df[col]) for col in df.columns}

            cursor.execute(pgsql.SQL('DROP TABLE IF EXISTS {};').format(pgsql.Identifier(table_name)))
            col_defs = pgsql.SQL(', ').join(
                pgsql.SQL('{} {}').format(pgsql.Identifier(col), pgsql.SQL(col_types[col]))
                for col in df.columns
            )
            cursor.execute(pgsql.SQL('CREATE TABLE {} ({});').format(pgsql.Identifier(table_name), col_defs))

            insert_sql = pgsql.SQL('INSERT INTO {} ({}) VALUES ({});').format(
                pgsql.Identifier(table_name),
                pgsql.SQL(', ').join(pgsql.Identifier(c) for c in df.columns),
                pgsql.SQL(', ').join(pgsql.Placeholder() for _ in df.columns),
            )
            rows = [
                tuple(_format_cell_for_type(v, col_types[col]) for col, v in zip(df.columns, row))
                for row in df.itertuples(index=False, name=None)
            ]
            cursor.executemany(insert_sql, rows)

            created_tables.append({
                'table': table_name,
                'sheet': sheet_name,
                'row_count': len(df),
            })

        connection = DatabaseConnection(
            name=name,
            type='Excel',
            host=None,
            port=None,
            database=base_table_name,
            username=None,
            password=None,
            config={
                'source_tables': created_tables,
                'original_filename': file.filename,
                'row_count': sum(t['row_count'] for t in created_tables)
            },
            workspace_id=int(request.form.get('workspace_id', 1) or 1),
            status='connected'
        )
        db.session.add(connection)
        db.session.commit()

        from app.services.automated_metamind import generate_router_config
        generate_router_config(force=True)

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
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

@bp.route('/<int:db_id>', methods=['GET'])
@jwt_required()
def get_database(db_id):
    """
    Get specific database connection details
    Response: { "database": {...} }
    """
    try:
        connection = DatabaseConnection.query.get(db_id)
        if not connection:
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
    try:
        connection = DatabaseConnection.query.get(db_id)
        if not connection:
            return jsonify({'error': 'Connection not found'}), 404
        
        data = request.get_json()
        
        # Update fields
        for key in ['name', 'host', 'port', 'database', 'username', 'password', 'connection_string', 'type']:
            if key in data:
                setattr(connection, key, data[key])
        
        db.session.commit()
        
        return jsonify({
            'database': serialize_connection(connection),
            'message': 'Connection updated successfully'
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
    try:
        connection = DatabaseConnection.query.get(db_id)
        if not connection:
            return jsonify({'error': 'Connection not found'}), 404
        
        db.session.delete(connection)
        db.session.commit()
        
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


def _summarize_table_for_metamind(cursor, table_name: str) -> str:
    """Asks an LLM to describe what a table actually contains (e.g. "Player
    roster with season-by-season performance stats") from its columns and a
    few sample rows, then stores that as a real Postgres table comment.
    automated_metamind.py's DB introspection already reads table comments
    via obj_description() and uses them as the table's description in
    metamind_router_config.json ahead of the generic "Table storing X
    records" fallback - so this is the one place that needs to write it."""
    cursor.execute(
        pgsql.SQL('SELECT * FROM {} LIMIT 5;').format(pgsql.Identifier(table_name))
    )
    sample_rows = cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]

    sample_text = "\n".join(
        ", ".join(f"{col}={val}" for col, val in zip(columns, row))
        for row in sample_rows
    )

    from langchain_openai import ChatOpenAI
    from langchain_core.messages import SystemMessage, HumanMessage

    prompt = (
        f"Table name: {table_name}\n"
        f"Columns: {', '.join(columns)}\n"
        f"Sample rows:\n{sample_text}\n\n"
        "In one short sentence, describe what this table contains in "
        "plain business language (e.g. \"Player roster with season-by-"
        "season performance stats\"). Output only that sentence, no "
        "quotes, no preamble."
    )
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.2, openai_api_key=os.getenv("OPENAI_API_KEY"))
    response = llm.invoke([
        SystemMessage(content="You write single-sentence, plain-language summaries of database tables."),
        HumanMessage(content=prompt),
    ])
    description = (response.content or "").strip().strip('"')
    if not description:
        description = f"Table storing {table_name} records."

    cursor.execute(
        pgsql.SQL('COMMENT ON TABLE {} IS %s;').format(pgsql.Identifier(table_name)),
        (description,)
    )
    return description


@bp.route('/<int:db_id>/process', methods=['POST'])
@jwt_required()
def process_database_connection(db_id):
    """
    Explicit process action for a saved database connection.
    For Excel/CSV connections, generates a content-aware summary of each
    table (via LLM) and stores it as the table's description so the router
    can tell what it's actually useful for - then regenerates the router
    config either way.
    """
    conn = None
    cursor = None
    try:
        connection = DatabaseConnection.query.get(db_id)
        if not connection:
            return jsonify({"status": "error", "message": "Connection not found"}), 404

        from app.services.automated_metamind import generate_router_config

        if (connection.type or '').lower() == 'excel':
            cfg = connection.config or {}
            tables = [t['table'] for t in cfg.get('source_tables', [])]
            if not tables and cfg.get('source_table'):
                tables = [cfg['source_table']]  # connections created before multi-sheet support

            if not tables:
                return jsonify({"status": "error", "message": "No tables found for this connection."}), 404

            try:
                conn = psycopg2.connect(**_get_databridge_db_config())
                conn.autocommit = True
                cursor = conn.cursor()
                summaries = {}
                for table_name in tables:
                    summaries[table_name] = _summarize_table_for_metamind(cursor, table_name)
            except Exception as e:
                print(f"Table summarization error: {e}")
                print(traceback.format_exc())
                return jsonify({"status": "error", "message": "Something went wrong while summarizing these tables. Please try again."}), 500

            generate_router_config(force=True)
            described = ", ".join(f'"{t}"' for t in tables)
            return jsonify({
                "status": "success",
                "message": f"Tables ready for queries: {described}."
            })

        try:
            generate_router_config(force=True)
            return jsonify({"status": "success", "message": "This connection's tables are now ready for queries."})
        except Exception as e:
            print(f"Router config regeneration error: {e}")
            return jsonify({"status": "error", "message": "Something went wrong while activating this connection. Please try again."}), 500
    except Exception as e:
        print(f"Process connection error: {str(e)}")
        print(traceback.format_exc())
        return jsonify({"status": "error", "message": "Something went wrong. Please try again."}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


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

#@bp.route('/run-agentic-process/<int:conn_id>', methods=['POST'])
#def run_agentic_process(conn_id):
#    try:
        # Step 1: Build tables in databrige_db
        # Ensure the path matches your 'services' folder in the sidebar
#        subprocess.run(["python", "services/databridge_services/db.py"], check=True)
        
#        time.sleep(10) # Let the CPU breathe

        # Step 2: Run the 40-minute LLM analysis
#        subprocess.run(["python", "services/databridge_services/metamind.py"], check=True)

#        return jsonify({"status": "success", "message": "Successfully JSON file created!"}), 200
#    except Exception as e:
#        return jsonify({"error": str(e)}), 500
    
@bp.route('/run-agentic-process/<int:conn_id>', methods=['POST'])
@jwt_required()
def run_agentic_process(conn_id):
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = "/app/logs"
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

    logger.info(f"Process started for connection ID: {conn_id}")
    try:
        # We add the extra /app/ here based on your 'find' command
        base_path = "/app/app/services/databridge_services"
        
        db_script = os.path.join(base_path, "db.py")
        meta_script = os.path.join(base_path, "metamind.py")

        # Step 1: Build SAP tables
        logger.info(f"Step 1 [build_sap_tables] start | conn_id={conn_id} | script={db_script}")
        result1 = subprocess.run(
            [sys.executable, db_script],
            check=True,
            timeout=5000,
            capture_output=True,
            text=True,
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
        )
        logger.info(f"Step 2 stdout:\n{result2.stdout}")
        logger.info(f"Step 2 stderr:\n{result2.stderr}")
        logger.info("Step 2 completed successfully")
        logger.info("Process finished successfully, router config JSON updated")

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