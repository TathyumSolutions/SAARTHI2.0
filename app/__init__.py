"""
Flask Application Factory
"""
from flask import Flask
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_jwt_extended import JWTManager
from config.config import config

# Initialize extensions
db = SQLAlchemy()
migrate = Migrate()
jwt = JWTManager()

def create_app(config_name='development'):
    """Create and configure the Flask application"""
    app = Flask(__name__)
    
    # Load configuration
    app.config.from_object(config[config_name])

    print("Working on initialisation")
    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)
    CORS(app)
    print("Initialisation completed")
    # Register blueprints
    from app.api.routes import (
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
    app.register_blueprint(upload_routes.bp)
    print("Working on the blue print part")
    # Health check endpoint
    @app.route('/health')
    def health_check():
        return {'status': 'healthy', 'service': 'Saarthi Enterprise API'}, 200
    
    return app
