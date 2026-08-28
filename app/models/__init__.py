"""
Database Models

3 logical databases (see config/config.py SQLALCHEMY_BINDS):
  - core:      Company, User, ResourceMapping, AuditLog
  - resources: DatabaseConnection, ApiConnector, FileResource,
    SpreadsheetTable, SpreadsheetIngestionRun, SpreadsheetIngestionError
  - workspace: ChatSession, ModelConfiguration, ResponseFeedback, QueryLog,
    BiSemanticsConfig, LLMCallLog

A 4th bind, 'spreadsheet_db', holds the actual row data pushed from Excel/
CSV uploads as dynamically-created tables (see
app/services/spreadsheet_warehouse_service.py) - those tables have no
declarative model since their shape depends on the uploaded sheet; only
the metadata describing them (SpreadsheetTable etc., above) lives here.

The router config (which datasources/tables/tools a user's smart router
considers) used to be a persisted RouterConfig row per user here. It's
now computed live on every call (see automated_metamind.generate_router_
config()) straight from DatabaseConnection/ApiConnector/FileResource -
those are the single source of truth for MetaMind data, not a separate
cached table.
"""
from .company import Company
from .user import User
from .resource_mapping import ResourceMapping
from .audit_log import AuditLog

from .database_connection import DatabaseConnection
from .api_connector import ApiConnector
from .file_resource import FileResource
from .spreadsheet_warehouse import SpreadsheetTable, SpreadsheetIngestionRun, SpreadsheetIngestionError

from .chat import ChatSession
from .model_config import ModelConfiguration
from .feedback import ResponseFeedback
from .query_log import QueryLog
from .bi_semantics_config import BiSemanticsConfig
from .llm_call_log import LLMCallLog

__all__ = [
    'Company',
    'User',
    'ResourceMapping',
    'AuditLog',
    'DatabaseConnection',
    'ApiConnector',
    'FileResource',
    'SpreadsheetTable',
    'SpreadsheetIngestionRun',
    'SpreadsheetIngestionError',
    'ChatSession',
    'ModelConfiguration',
    'ResponseFeedback',
    'QueryLog',
    'BiSemanticsConfig',
    'LLMCallLog',
]
