"""
Analytics Models
"""
from app import db
from datetime import datetime

class Chart(db.Model):
    """Visualization charts"""
    __tablename__ = 'charts'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    type = db.Column(db.String(50), nullable=False)  # bar, line, pie, etc.
    data = db.Column(db.JSON, nullable=False)
    config = db.Column(db.JSON, default={})
    
    workspace_id = db.Column(db.Integer, db.ForeignKey('workspaces.id'))
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        # TODO: Implement
        pass

class Report(db.Model):
    """Analytics reports"""
    __tablename__ = 'reports'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    type = db.Column(db.String(50), nullable=False)
    content = db.Column(db.JSON)
    config = db.Column(db.JSON, default={})
    
    workspace_id = db.Column(db.Integer, db.ForeignKey('workspaces.id'))
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_generated = db.Column(db.DateTime)
    
    def to_dict(self):
        # TODO: Implement
        pass
