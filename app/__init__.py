"""
Flask Application Factory
"""
from flask import Flask
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_jwt_extended import JWTManager
from config.config import config
import os

# Initialize extensions
db = SQLAlchemy()
migrate = Migrate()
jwt = JWTManager()

print("Working on upload folder")
print("Current file path:", os.path.abspath(__file__))

# Set up upload folder
UPLOAD_FOLDER = "/workspaces/SAARTHI2.0/uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def create_app(config_name='development'):
    """Create and configure the Flask application"""
    app = Flask(__name__)
    CORS(app)
    
    # Load configuration
    app.config.from_object(config[config_name])
    app.config['SECRET_KEY'] = 'your-secret-key-change-in-production'
    app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB

    print("Working on initialisation")
    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)
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
    
    from app.api.routes.upload_routes import upload_bp
    app.register_blueprint(upload_bp)
    
    # Import models to ensure they're registered with SQLAlchemy
    from app.models import (
        database_connection,
        workspace,
        user,
        chat,
        query,
        analytics,
        audit,
        datasource,
        model_config
    )
    
    # Create database tables
    with app.app_context():
        try:
            print("Creating database tables...")
            db.create_all()
            
            # Create default workspace if none exists
            from app.models.workspace import Workspace
            if not Workspace.query.first():
                default_workspace = Workspace(
                    name='Default Workspace',
                    description='Default workspace for database connections',
                    owner_id=1  # Will need to create users too
                )
                db.session.add(default_workspace)
                db.session.commit()
                print("✓ Created default workspace")
            
            print("✓ Database tables created successfully")
        except Exception as e:
            print(f"⚠ Error creating tables: {str(e)}")
    
    print("Working on the blue print part")
    # Health check endpoint
    @app.route('/health')
    def health_check():
        return {'status': 'healthy', 'service': 'Saarthi Enterprise API'}, 200
    
    return app
