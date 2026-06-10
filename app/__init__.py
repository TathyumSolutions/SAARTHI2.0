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
    print("👉 FLASK IS CURRENTLY CONNECTING TO DATABASE:", app.config.get('SQLALCHEMY_DATABASE_URI'))
   # app.config['SQLALCHEMY_DATABASE_URI'] = "postgresql://saarthi:password@db:5432/saarthi_db"
    app.config['SECRET_KEY'] = 'your-secret-key-change-in-production'
    app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB

    print("Working on initialisation")
    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)
    print("Initialisation completed")
    
    # Register blueprints
    from app.routes import (
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
    
    from app.routes.upload_routes import upload_bp
    app.register_blueprint(upload_bp)
    
    # Import models to ensure they're registered with SQLAlchemy
    #from app.models import (
    #    database_connection,
    #    workspace,
    #    user,
    #    chat,
    #    query,
    #    analytics,
    #    audit,
    #    datasource,
    #    model_config
    #)

    from app import models
    
    # Create database tables
    
    #with app.app_context():
    #    try:
    #        print("Creating database tables...")
    #        db.create_all()
            
            # Create default workspace if none exists
    #        from app.models.workspace import Workspace
    #        if not Workspace.query.first():
    #            default_workspace = Workspace(
    #                name='Default Workspace',
    #                description='Default workspace for database connections',
    #                owner_id=1  # Will need to create users too
    #            )
    #            db.session.add(default_workspace)
    #            db.session.commit()
    #            print("✓ Created default workspace")
            
    #        print("✓ Database tables created successfully")
    #    except Exception as e:
    #        print(f"⚠ Error creating tables: {str(e)}")

    # Create database tables
    #with app.app_context():
    #    try:
    #        print("Creating database tables...")
    #        db.create_all()
            
    #        from app.models.user import User
    #        from app.models.workspace import Workspace

            # STEP 1: Create the User first so the 'owner_id' has someone to point to
    #        if not User.query.get(1):
    #            print("Creating missing admin user...")
    #            admin = User(id=1, name='admin', email='admin@saarthi.ai',password_hash='scrypt:32768:8:1$dummyhash',
    #            role='viewer',
    #            status='active')
    #            db.session.add(admin)
    #            db.session.commit()

            # STEP 2: Now create the workspace
    #        if not Workspace.query.first():
    #            default_workspace = Workspace(
    #                name='Default Workspace',
    #                description='Default workspace for database connections',
    #                owner_id=1  # This now works because User 1 exists!
    #            )
    #            db.session.add(default_workspace)
    #            db.session.commit()
    #            print("✓ Database and User initialized successfully")
                
    #    except Exception as e:
    #       print(f"⚠ Error: {str(e)}")
    #        db.session.rollback()

    #with app.app_context():
    #    try:
    #        print("Creating database tables...")
    #        # This creates tables only if they don't exist
    #        db.create_all()
            
    #        from app.models.user import User
    #        from app.models.workspace import Workspace

    #        # STEP 1: Create the User first
    #        admin = User.query.get(1)
    #        if not admin:
    #            print("Creating missing admin user...")
    #           admin = User(
    #                id=1, 
    #                name='admin', 
    #                email='admin@saarthi.ai',
    #                password_hash='scrypt:32768:8:1$dummyhash',
    #                role='viewer',
    #                status='active'
                #)
    #            db.session.add(admin)
    #            db.session.commit()

     #       # STEP 2: Create the workspace
     #       if not Workspace.query.first():
     #           default_workspace = Workspace(
     #               name='Default Workspace',
     #               description='Default workspace for database connections',
     #               owner_id=1 
     #           )
     #           db.session.add(default_workspace)
     #           db.session.commit()
     #           print("✓ Database and User initialized successfully")
                
     #   except Exception as e:
            # This print will tell us exactly what is wrong if it still fails
     #       print(f"⚠ Database sync notice: {str(e)}")
     #       db.session.rollback()


    #with app.app_context():
    #    try:
    #        from sqlalchemy import text
    #        print("Cleaning up old types...")
    #        with db.engine.connect() as conn:
                # This prevents the CASCADE/Duplicate errors from previous screenshots
    #            conn.execute(text("DROP TYPE IF EXISTS user_role CASCADE"))
    #            conn.execute(text("DROP TYPE IF EXISTS user_status CASCADE"))
    #            conn.commit()
            
    #        print("Creating database tables...")
    #        db.create_all()

    #with app.app_context():
    #    try:
            # 1. Force SQLAlchemy to recognize all relationships before creation
    #        from sqlalchemy.orm import configure_mappers
    #        configure_mappers()
            
    #        print("Synchronizing database schema...")
            # create_all will build any missing tables (like database_connections)
    #        db.create_all() 
            
            # 2. Verify the table exists by performing a quick check
    #        from sqlalchemy import inspect
    #        inspector = inspect(db.engine)
    #        if 'database_connections' in inspector.get_table_names():
    #            print("✓ Table 'database_connections' is ready.")
            
    #        db.session.commit()
    #    except Exception as e:
    #        print(f"⚠ Database Sync Error: {str(e)}")
    #        db.session.rollback()        
            
    #        from app.models.user import User
    #        from app.models.workspace import Workspace

            # Check for existing admin
    #        admin = User.query.get(1)
    #        if not admin:
    #            print("Creating missing admin user...")
    #            admin = User(
    #                id=1,
    #                name='admin',
    #                email='admin@saarthi.ai',
    #                password_hash='scrypt:32768:8:1$dummyhash',
    #                role='viewer',
    #                status='active'
    #            )
    #            db.session.add(admin)
    #            db.session.commit()

    #        if not Workspace.query.first():
    #            print("Creating default workspace...")
    #            default_workspace = Workspace(
    #                name='Default Workspace',
    #                description='Default workspace for database connections',
    #                owner_id=1
    #           )
    #            db.session.add(default_workspace)
    #            db.session.commit()
    #           print("✓ Database and User initialized successfully")

    #    except Exception as e:
    #        print(f"⚠ Database initialization notice: {str(e)}")
    #        db.session.rollback()
    

    with app.app_context():
        try:
            # 1. Force SQLAlchemy to recognize all relationships before creation
            from sqlalchemy.orm import configure_mappers
            configure_mappers()
            
            print("Synchronizing database schema...")
            db.create_all() 
            
            # 2. ONLY attempt data initialization if tables were created successfully
            from app.models.user import User
            from app.models.workspace import Workspace

            # Check/Create Admin
            admin = User.query.get(1)
            if not admin:
                print("Creating missing admin user...")
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
                print("Creating default workspace...")
                default_workspace = Workspace(
                    name='Default Workspace',
                    description='Default workspace for database connections',
                    owner_id=1
                )
                db.session.add(default_workspace)
                db.session.commit()
            
            print("✓ Database and User initialized successfully")

        except Exception as e:
            # This prevents a second crash if a table (like 'reports') is still broken
            print(f"⚠ Database Setup Error: {str(e)}")
            db.session.rollback()
    
    print("Working on the blue print part")
    # Health check endpoint
    @app.route('/health')
    def health_check():
        return {'status': 'healthy', 'service': 'Saarthi Enterprise API'}, 200
    
    return app
