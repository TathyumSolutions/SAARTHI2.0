"""
Workspace Model
"""
from app import db
from datetime import datetime

class Workspace(db.Model):
    """Workspace model for organizing data sources and queries"""
    __tablename__ = 'workspaces'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Settings
    settings = db.Column(db.JSON, default={})
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    databases = db.relationship('DatabaseConnection', backref='workspace', lazy=True, cascade='all, delete-orphan')
    datasources = db.relationship('Datasource', backref='workspace', lazy=True, cascade='all, delete-orphan')
    chat_sessions = db.relationship('ChatSession', backref='workspace', lazy=True, cascade='all, delete-orphan')
    
    def to_dict(self):
        """Convert workspace to dictionary"""
        # TODO: Implement serialization
        pass
