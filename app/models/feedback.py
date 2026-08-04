"""
Response Feedback Model - Self-Learning Mode like/dislike data, used to
build a company-scoped feedback context for the router.
"""
from app import db
from datetime import datetime


class ResponseFeedback(db.Model):
    __bind_key__ = 'workspace'
    __tablename__ = 'response_feedback'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    company_code = db.Column(db.String(50), nullable=True, index=True)

    question = db.Column(db.Text, nullable=False)
    answer = db.Column(db.Text, nullable=False)
    sql_query = db.Column(db.Text, nullable=True)
    router_decision = db.Column(db.String(50), nullable=True)

    feedback_type = db.Column(db.String(10), nullable=False)  # like or dislike
    remarks = db.Column(db.Text, nullable=True)

    metamind_snapshot = db.Column(db.JSON, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
