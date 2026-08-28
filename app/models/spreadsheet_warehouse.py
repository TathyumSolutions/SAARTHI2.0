"""
Spreadsheet Warehouse Models - metadata for the dedicated Postgres warehouse
that Excel/CSV data gets pushed into (see
app/services/spreadsheet_warehouse_service.py). These rows describe *where*
a spreadsheet's data physically lives (in the 'spreadsheet_db' bind) and
*how* each push went - the actual row data itself is not modeled here, it
lives in dynamically-created tables in that separate bind, since its shape
is whatever the uploaded sheet's columns happen to be.

This is deliberately separate from the existing Parquet-backed path
(app/services/spreadsheet_service.py), which stays as-is for the pandas/
chat-query workflow - this warehouse is an additive path for users who want
their spreadsheet pushed into a real, editable Postgres table instead.
"""
from app import db
from datetime import datetime


class SpreadsheetTable(db.Model):
    __bind_key__ = 'resources'
    __tablename__ = 'spreadsheet_tables'

    id = db.Column(db.Integer, primary_key=True)
    # Links back to the DatabaseConnection (type='Excel') this table was
    # pushed from - not a hard FK since it lives in the same bind but is a
    # separate model/table, matching this codebase's existing convention of
    # plain integer references instead of cross-model ForeignKeys (see
    # ResourceMapping.resource_id).
    connection_id = db.Column(db.Integer, nullable=False, index=True)

    # The literal table name inside the 'spreadsheet_db' bind - sanitized/
    # unique, generated once at creation time and never changed.
    pg_table_name = db.Column(db.String(150), unique=True, nullable=False)
    display_name = db.Column(db.String(200), nullable=False)
    sheet_name = db.Column(db.String(200), nullable=True)

    # [{"name": <original header>, "pg_name": <sanitized column>, "type": "boolean"|"number"|"date"|"text"}, ...]
    # The whitelist used to validate any incoming column reference (LLM
    # column-mapping suggestions, inline-edit requests) before it's ever
    # interpolated into SQL as an identifier.
    column_schema = db.Column(db.JSON, default=list)

    row_count = db.Column(db.Integer, default=0)

    company_code = db.Column(db.String(50), nullable=True, index=True)
    created_by_user_id = db.Column(db.Integer, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'connection_id': self.connection_id,
            'pg_table_name': self.pg_table_name,
            'display_name': self.display_name,
            'sheet_name': self.sheet_name,
            'column_schema': self.column_schema or [],
            'row_count': self.row_count,
            'company_code': self.company_code,
            'created_by_user_id': self.created_by_user_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class SpreadsheetIngestionRun(db.Model):
    __bind_key__ = 'resources'
    __tablename__ = 'spreadsheet_ingestion_runs'

    id = db.Column(db.Integer, primary_key=True)
    spreadsheet_table_id = db.Column(db.Integer, nullable=False, index=True)
    connection_id = db.Column(db.Integer, nullable=False, index=True)

    mode = db.Column(db.String(20), nullable=False)  # 'new_table' | 'append_existing'
    status = db.Column(db.String(20), default='running', index=True)  # running | success | partial_error | failed

    total_rows = db.Column(db.Integer, default=0)
    success_rows = db.Column(db.Integer, default=0)
    error_rows = db.Column(db.Integer, default=0)

    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    finished_at = db.Column(db.DateTime, nullable=True)

    def to_dict(self):
        return {
            'id': self.id,
            'spreadsheet_table_id': self.spreadsheet_table_id,
            'connection_id': self.connection_id,
            'mode': self.mode,
            'status': self.status,
            'total_rows': self.total_rows,
            'success_rows': self.success_rows,
            'error_rows': self.error_rows,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'finished_at': self.finished_at.isoformat() if self.finished_at else None,
        }


class SpreadsheetIngestionError(db.Model):
    __bind_key__ = 'resources'
    __tablename__ = 'spreadsheet_ingestion_errors'

    id = db.Column(db.Integer, primary_key=True)
    run_id = db.Column(db.Integer, nullable=False, index=True)

    # 1-based position of the failing row within the uploaded sheet (not the
    # Postgres row id, since the row never made it into the table).
    row_number = db.Column(db.Integer, nullable=False)
    error_message = db.Column(db.Text, nullable=False)
    # The offending row's original values, keyed by source column name -
    # lets the "View Error" UI show what was actually in the row, not just
    # the DB error string.
    raw_row = db.Column(db.JSON, default=dict)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'run_id': self.run_id,
            'row_number': self.row_number,
            'error_message': self.error_message,
            'raw_row': self.raw_row or {},
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
