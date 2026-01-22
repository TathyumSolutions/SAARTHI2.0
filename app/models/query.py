"""
Query Models
"""
from app import db
from datetime import datetime

class Query(db.Model):
    """Query execution history"""
    __tablename__ = 'queries'
    
    id = db.Column(db.Integer, primary_key=True)
    natural_language_query = db.Column(db.Text, nullable=False)
    sql_query = db.Column(db.Text)
    results = db.Column(db.JSON)
    status = db.Column(db.String(20))  # success, error, pending
    error_message = db.Column(db.Text)
    execution_time_ms = db.Column(db.Integer)
    
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    database_id = db.Column(db.Integer, db.ForeignKey('database_connections.id'))
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        # TODO: Implement
        pass

class SavedQuery(db.Model):
    """Saved queries for reuse"""
    __tablename__ = 'saved_queries'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    natural_language_query = db.Column(db.Text)
    sql_query = db.Column(db.Text, nullable=False)
    
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    workspace_id = db.Column(db.Integer, db.ForeignKey('workspaces.id'))
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        # TODO: Implement
        pass
