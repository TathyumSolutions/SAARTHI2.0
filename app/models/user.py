"""
User Model
"""
from app import db
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

class User(db.Model):
    """User model for authentication and authorization"""
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default='viewer')  # admin, editor, viewer, analyst
    status = db.Column(db.String(20), default='active')  # active, inactive, suspended
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    
    # Relationships
    workspaces = db.relationship('Workspace', backref='owner', lazy=True)
    chat_sessions = db.relationship('ChatSession', backref='user', lazy=True)
    queries = db.relationship('Query', backref='user', lazy=True)
    
    def set_password(self, password):
        """Hash and set password"""
        # TODO: Implement password hashing
        pass
    
    def check_password(self, password):
        """Check password against hash"""
        # TODO: Implement password verification
        pass
    
    def to_dict(self):
        """Convert user to dictionary"""
        # TODO: Implement serialization
        pass
