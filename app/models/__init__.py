"""
Database Models

3 logical databases (see config/config.py SQLALCHEMY_BINDS):
  - core:      Company, User, ResourceMapping, AuditLog
  - resources: DatabaseConnection, ApiConnector, FileResource
  - workspace: ChatSession, ModelConfiguration, ResponseFeedback
"""
from .company import Company
from .user import User
from .resource_mapping import ResourceMapping
from .audit_log import AuditLog

from .database_connection import DatabaseConnection
from .api_connector import ApiConnector
from .file_resource import FileResource

from .chat import ChatSession
from .model_config import ModelConfiguration
from .feedback import ResponseFeedback

__all__ = [
    'Company',
    'User',
    'ResourceMapping',
    'AuditLog',
    'DatabaseConnection',
    'ApiConnector',
    'FileResource',
    'ChatSession',
    'ModelConfiguration',
    'ResponseFeedback',
]
