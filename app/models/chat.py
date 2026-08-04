"""
Chat Session Model.

Replaces the old raw-SQL `chat_sessions` table that lived in a separate
saarthi_chats_db (accessed via ad-hoc psycopg2 in chat_routes.py) with no
tenant tagging. There was also a second, entirely unused SQLAlchemy
ChatSession/ChatMessage pair with a per-message granular design that
nothing ever actually wrote to - dropped in favor of the one design that's
actually used: one row per session holding the rendered chat history.
"""
from app import db
from datetime import datetime


class ChatSession(db.Model):
    __bind_key__ = 'workspace'
    __tablename__ = 'chat_sessions'

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.String(255), unique=True, nullable=False, index=True)
    title = db.Column(db.String(255), nullable=False)
    chat_history = db.Column(db.Text, nullable=False)

    company_code = db.Column(db.String(50), nullable=True, index=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'session_id': self.session_id,
            'title': self.title,
            'chat_history': self.chat_history,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
