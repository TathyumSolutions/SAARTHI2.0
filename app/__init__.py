"""
Flask Application Factory
"""
from flask import Flask
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_jwt_extended import JWTManager
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flasgger import Swagger
from config.config import config
import os
from app.services.db_bootstrap import bootstrap_databases


# Initialize extensions
db = SQLAlchemy()
migrate = Migrate()
jwt = JWTManager()
# Rate limits are keyed by client IP, with a generous default so normal
# use of the app is unaffected - the tighter, per-route limits (login,
# chat, uploads, outbound tool calls) are what actually matter for abuse
# and cost control. Falls back to in-memory storage (per-worker, so less
# effective with multiple gunicorn workers) if Redis isn't reachable
# rather than failing app startup over it.
limiter = Limiter(key_func=get_remote_address, default_limits=["200 per minute"])

# Uploaded files land next to wherever the app actually runs from, not a
# hardcoded container path - the same "assumed one specific machine's
# layout" mistake that broke the SAP data seeding script.
UPLOAD_FOLDER = os.path.join(os.getcwd(), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def create_app(config_name='development'):
    """Create and configure the Flask application"""
    app = Flask(__name__)

    # Load configuration
    app.config.from_object(config[config_name])

    # CORS is restricted to an explicit allow-list (ALLOWED_ORIGINS env var,
    # comma-separated). With no origins configured, cross-origin requests
    # are simply denied - same-origin requests (the normal way this app is
    # used, since Flask serves both the API and the templates) are
    # unaffected by CORS either way. Do NOT widen this to "*" - the API
    # carries a bearer token in requests, and a wildcard origin combined
    # with credentialed requests is exactly the CSRF-adjacent hole CORS
    # exists to prevent.
    allowed_origins = [o.strip() for o in os.getenv('ALLOWED_ORIGINS', '').split(',') if o.strip()]
    if allowed_origins:
        CORS(app, origins=allowed_origins, supports_credentials=True)
    else:
        print("⚠️  ALLOWED_ORIGINS is not set - cross-origin requests will be denied. "
              "Set ALLOWED_ORIGINS to a comma-separated list of trusted origins if a "
              "separately-hosted frontend needs to call this API.")

    if config_name == 'production' and app.config.get('SECRET_KEY') in (None, 'dev-secret-key'):
        raise RuntimeError(
            "SECRET_KEY is not set. Refusing to start in production with the "
            "insecure default - set the SECRET_KEY (and JWT_SECRET_KEY) "
            "environment variables."
        )
    app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB

    # The app is split across 3 logical databases (core / resources /
    # workspace - see config/config.py SQLALCHEMY_BINDS). Create whichever
    # of them don't exist yet on the target Postgres server before
    # SQLAlchemy tries to use them.
    print("[DB Bootstrap] Ensuring core/resources/workspace databases exist...")
    bootstrap_databases(app.config['SQLALCHEMY_BINDS'])

    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)
    # Flask-Limiter reads its storage backend from config at init time - set
    # it to Redis (already used elsewhere in this app) so limits are shared
    # across gunicorn's multiple worker processes, instead of each worker
    # tracking its own counts independently.
    app.config.setdefault('RATELIMIT_STORAGE_URI', app.config.get('REDIS_URL'))
    limiter.init_app(app)
    swagger_template = {
        "swagger": "2.0",
        "info": {
            "title": "Saarthi API",
            "description": "Saarthi Chat API reference",
            "version": "1.0.0"
        }
    }
    Swagger(app, template=swagger_template)

    # Register blueprints
    from app.routes import (
        page_routes,
        auth_routes,
        platform_routes,
        workspace_routes,
        api_routes,
        api_v1_routes,
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
        upload_routes,
        settings_routes,
        resource_mapping_routes,
        warehouse_routes
    )

    # HTML page routes (no prefix)
    app.register_blueprint(page_routes.bp)
    # API routes
    app.register_blueprint(auth_routes.bp)
    app.register_blueprint(platform_routes.bp)
    app.register_blueprint(workspace_routes.bp)
    app.register_blueprint(llm_routes.bp)
    app.register_blueprint(database_routes.bp)
    app.register_blueprint(query_routes.bp)
    app.register_blueprint(datasource_routes.bp)
    app.register_blueprint(analytics_routes.bp)
    app.register_blueprint(chat_routes.bp)
    app.register_blueprint(api_v1_routes.bp)
    app.register_blueprint(history_routes.bp)
    app.register_blueprint(export_routes.bp)
    app.register_blueprint(model_config_routes.bp)
    app.register_blueprint(user_routes.bp)
    app.register_blueprint(api_routes.bp)
    app.register_blueprint(settings_routes.bp)
    app.register_blueprint(resource_mapping_routes.bp)
    app.register_blueprint(warehouse_routes.bp)

    from app.routes.upload_routes import upload_bp
    app.register_blueprint(upload_bp)

    # Import models so they're registered with SQLAlchemy before create_all()
    from app import models  # noqa: F401

    with app.app_context():
        try:
            from sqlalchemy.orm import configure_mappers
            configure_mappers()
            print("[DB Bootstrap] Synchronizing schema across core/resources/workspace...")
            db.create_all()
            print("[DB Bootstrap] Schema is up to date.")
        except Exception as e:
            print(f"[DB Bootstrap] Schema sync error: {e}")
            db.session.rollback()

    # Health check endpoint
    @app.route('/health')
    def health_check():
        return {'status': 'healthy', 'service': 'Saarthi Enterprise API'}, 200

    return app
