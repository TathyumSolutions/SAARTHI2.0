"""
Datasource Model
"""
from app import db
from datetime import datetime

class Datasource(db.Model):
    """External data source connections"""
    __tablename__ = 'datasources'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    type = db.Column(db.String(50), nullable=False)  # api, file, s3, gcs, etc.
    config = db.Column(db.JSON, default={})
    status = db.Column(db.String(20), default='active')
    
    workspace_id = db.Column(db.Integer, db.ForeignKey('workspaces.id'), nullable=False)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_sync = db.Column(db.DateTime)
    
    def to_dict(self):
        # TODO: Implement
        pass
