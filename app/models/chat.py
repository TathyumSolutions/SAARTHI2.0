"""
Chat Models
"""
from app import db
from datetime import datetime

class ChatSession(db.Model):
    """Chat session"""
    __tablename__ = 'chat_sessions'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200))
    mode = db.Column(db.String(20), default='query')  # query or chat
    
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    workspace_id = db.Column(db.Integer, db.ForeignKey('workspaces.id'))
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    messages = db.relationship('ChatMessage', backref='session', lazy=True, cascade='all, delete-orphan')
    
    def to_dict(self):
        # TODO: Implement
        pass

class ChatMessage(db.Model):
    """Individual chat message"""
    __tablename__ = 'chat_messages'
    
    id = db.Column(db.Integer, primary_key=True)
    role = db.Column(db.String(20), nullable=False)  # user, assistant, system
    content = db.Column(db.Text, nullable=False)
    query_result = db.Column(db.JSON)
    
    session_id = db.Column(db.Integer, db.ForeignKey('chat_sessions.id'), nullable=False)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        # TODO: Implement
        pass
