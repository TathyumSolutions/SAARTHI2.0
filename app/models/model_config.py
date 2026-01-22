"""
Model Configuration Model
"""
from app import db
from datetime import datetime

class ModelConfiguration(db.Model):
    """LLM model configurations"""
    __tablename__ = 'model_configurations'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    model = db.Column(db.String(100), nullable=False)
    provider = db.Column(db.String(50), nullable=False)
    settings = db.Column(db.JSON, default={})
    
    workspace_id = db.Column(db.Integer, db.ForeignKey('workspaces.id'))
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        # TODO: Implement
        pass
