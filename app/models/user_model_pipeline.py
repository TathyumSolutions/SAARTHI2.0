"""
User Model Pipeline Configuration Model
Stores per-user selection of models for each pipeline step
"""
from app import db
from datetime import datetime


class UserModelPipeline(db.Model):
    """Store user's LLM pipeline model selections"""
    __bind_key__ = 'workspace'
    __tablename__ = 'user_model_pipelines'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    
    # Main model selected in top dropdown
    main_model = db.Column(db.String(100), nullable=True)
    
    # User's preference: 'oss' or 'api'
    model_type_preference = db.Column(db.String(20), default='oss')
    
    # Per-step model overrides (step_key -> model_name)
    # Example: {'query_sense': 'llama2:7b', 'sql_generator': 'gpt-4o', ...}
    step_models = db.Column(db.JSON, default={})
    
    # Metadata
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "main_model": self.main_model,
            "model_type_preference": self.model_type_preference,
            "step_models": self.step_models or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }
