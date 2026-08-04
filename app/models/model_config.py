"""
Model Configuration Model - per-user LLM pipeline settings.
"""
from app import db
from datetime import datetime


class ModelConfiguration(db.Model):
    __bind_key__ = 'workspace'
    __tablename__ = 'model_configurations'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    model = db.Column(db.String(100), nullable=False)
    provider = db.Column(db.String(50), nullable=False)
    settings = db.Column(db.JSON, default={})

    company_code = db.Column(db.String(50), nullable=True, index=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "model": self.model,
            "provider": self.provider,
            "settings": self.settings,
            "company_code": self.company_code,
            "user_id": self.user_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }
