"""
API Routes
"""
from . import (
    page_routes,
    auth_routes,
    workspace_routes,
    llm_routes,
    database_routes,
    query_routes,
    datasource_routes,
    analytics_routes,
    chat_routes,
    history_routes,
    export_routes,
    model_config_routes,
    user_routes,
    upload_routes
)

__all__ = [
    'page_routes',
    'auth_routes',
    'workspace_routes',
    'llm_routes',
    'database_routes',
    'query_routes',
    'datasource_routes',
    'analytics_routes',
    'chat_routes',
    'history_routes',
    'export_routes',
    'model_config_routes',
    'user_routes',
    'upload_routes'
]
