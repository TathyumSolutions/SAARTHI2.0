"""
Configuration settings for different environments
"""
import os
from datetime import timedelta
from urllib.parse import urlparse, urlunparse
from dotenv import load_dotenv

load_dotenv()


def _derive_db_url(base_url, db_name):
    """
    Swaps just the database name in a connection URL, keeping the same
    host/port/credentials - so the app's 3 logical databases (core,
    resources, workspace) are always derived from ONE configured base URL
    instead of each needing its own env var. Works for both Postgres
    (swap the URL path) and SQLite (swap the filename), so local dev
    without Postgres still gets 3 separate, independent databases.
    """
    parsed = urlparse(base_url)
    if parsed.scheme.startswith('sqlite'):
        return f"sqlite:///{db_name}.db"
    return urlunparse(parsed._replace(path=f"/{db_name}"))


class Config:
    """Base configuration"""
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY', 'jwt-secret-key')
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=1)
    # Default is headers only - query-string tokens (needed for the SSE
    # Chain of Thought stream, since browsers' native EventSource can't set
    # custom headers) are opted into per-route with
    # @jwt_required(locations=["query_string"]), not globally. Query
    # strings routinely end up in server access logs and browser history,
    # so every other endpoint should only ever accept the Authorization
    # header.
    JWT_TOKEN_LOCATION = ['headers']
    JWT_QUERY_STRING_NAME = 'token'
    
    # CORS
    CORS_HEADERS = 'Content-Type'
    
    # Database
    # The app is split into 3 logical databases (see app/models/ - core:
    # identity/tenancy/access/audit, resources: database connections/files/
    # API connectors, workspace: chat/model-config/feedback), all derived
    # from this one base URL so there's a single place to point the app at
    # a different Postgres server. DATABASE_URL's own dbname is ignored -
    # only host/port/credentials are kept, since the 3 logical databases
    # each get their own name via _derive_db_url.
    _BASE_DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://saarthi:password@db:5432/saarthi')
    SQLALCHEMY_DATABASE_URI = _derive_db_url(_BASE_DATABASE_URL, 'saarthi_core_db')
    SQLALCHEMY_BINDS = {
        'core': _derive_db_url(_BASE_DATABASE_URL, 'saarthi_core_db'),
        'resources': _derive_db_url(_BASE_DATABASE_URL, 'saarthi_resources_db'),
        'workspace': _derive_db_url(_BASE_DATABASE_URL, 'saarthi_workspace_db'),
    }

    # Superadmin emails (comma-separated) allowed to provision new
    # companies via /api/platform/companies - not a signup-able role,
    # nobody can self-elevate into it.
    SUPERADMIN_EMAILS = [e.strip().lower() for e in os.getenv('SUPERADMIN_EMAILS', '').split(',') if e.strip()]

    # MongoDB
    MONGODB_URI = os.getenv('MONGODB_URI', 'mongodb://localhost:27017/saarthi_db')
    
    # Redis
    REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
    
    # LLM API Keys
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
    ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')
    AZURE_OPENAI_KEY = os.getenv('AZURE_OPENAI_KEY')
    AZURE_OPENAI_ENDPOINT = os.getenv('AZURE_OPENAI_ENDPOINT')
    
    # AWS
    AWS_ACCESS_KEY_ID = os.getenv('AWS_ACCESS_KEY_ID')
    AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')
    AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')

class DevelopmentConfig(Config):
    """Development configuration"""
    DEBUG = True
    TESTING = False

class ProductionConfig(Config):
    """Production configuration"""
    DEBUG = False
    TESTING = False

class TestingConfig(Config):
    """Testing configuration"""
    DEBUG = True
    TESTING = True
    SQLALCHEMY_DATABASE_URI = _derive_db_url('sqlite:///test_saarthi.db', 'test_saarthi_core')
    SQLALCHEMY_BINDS = {
        'core': _derive_db_url('sqlite:///test_saarthi.db', 'test_saarthi_core'),
        'resources': _derive_db_url('sqlite:///test_saarthi.db', 'test_saarthi_resources'),
        'workspace': _derive_db_url('sqlite:///test_saarthi.db', 'test_saarthi_workspace'),
    }

config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}
