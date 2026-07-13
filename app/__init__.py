"""
Flask Application Factory
"""
import logging
import os

from flask import Flask
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_jwt_extended import JWTManager
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from config.config import config, ProductionConfig
from app.services.api_db__init__ import initialize_api_database
from app.services.chat_db__init__ import initialize_chats_database
from app.services.auth_db__init__ import init_auth_database

logger = logging.getLogger(__name__)

# Initialize extensions
db = SQLAlchemy()
migrate = Migrate()
jwt = JWTManager()
limiter = Limiter(key_func=get_remote_address)

# Set up upload folder
UPLOAD_FOLDER = "/workspaces/SAARTHI2.0/uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def create_app(config_name='development'):
    """Create and configure the Flask application"""
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')

    app = Flask(__name__)
    CORS(app, supports_credentials=True)

    # Load configuration
    app_config = config[config_name]
    if app_config is ProductionConfig:
        app_config.validate()
    app.config.from_object(app_config)

    live_db_uri = app.config.get('SQLALCHEMY_DATABASE_URI')
    logger.info("Connecting to database: %s", live_db_uri)

    initialize_api_database(live_db_uri)
    initialize_chats_database(live_db_uri)
    init_auth_database(live_db_uri)

    app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB

    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)
    limiter.init_app(app)

    # Register blueprints
    from app.routes import (
        page_routes,
        auth_routes,
        workspace_routes,
        api_routes,
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

    # HTML page routes (no prefix)
    app.register_blueprint(page_routes.bp)
    # API routes
    app.register_blueprint(auth_routes.bp)
    app.register_blueprint(workspace_routes.bp)
    app.register_blueprint(llm_routes.bp)
    app.register_blueprint(database_routes.bp)
    app.register_blueprint(query_routes.bp)
    app.register_blueprint(datasource_routes.bp)
    app.register_blueprint(analytics_routes.bp)
    app.register_blueprint(chat_routes.bp)
    app.register_blueprint(history_routes.bp)
    app.register_blueprint(export_routes.bp)
    app.register_blueprint(model_config_routes.bp)
    app.register_blueprint(user_routes.bp)
    app.register_blueprint(api_routes.bp)

    from app.routes.upload_routes import upload_bp
    app.register_blueprint(upload_bp)

    # Import models to ensure they're registered with SQLAlchemy
    from app import models

    with app.app_context():
        try:
            # Force SQLAlchemy to recognize all relationships before creation
            from sqlalchemy.orm import configure_mappers
            configure_mappers()

            logger.info("Synchronizing database schema...")
            db.create_all()

            from app.models.user import User
            from app.models.workspace import Workspace

            # Check/Create Admin
            admin = User.query.get(1)
            if not admin:
                logger.info("Creating missing admin user...")
                admin = User(
                    id=1,
                    name='admin',
                    email='admin@saarthi.ai',
                    password_hash='scrypt:32768:8:1$dummyhash',
                    role='viewer',
                    status='active'
                )
                db.session.add(admin)
                db.session.commit()

            # Check/Create Workspace
            if not Workspace.query.first():
                logger.info("Creating default workspace...")
                default_workspace = Workspace(
                    name='Default Workspace',
                    description='Default workspace for database connections',
                    owner_id=1
                )
                db.session.add(default_workspace)
                db.session.commit()

            logger.info("Database and admin user initialized successfully")

        except Exception:
            # This prevents a second crash if a table (like 'reports') is still broken
            logger.exception("Database setup error")
            db.session.rollback()

    # Health check endpoint
    @app.route('/health')
    def health_check():
        return {'status': 'healthy', 'service': 'Saarthi Enterprise API'}, 200

    return app
