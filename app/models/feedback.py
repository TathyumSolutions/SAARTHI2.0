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

    # The QueryLog row this feedback was given on (see app/models/query_log.py
    # and app/utils/query_codes.py) - lets a feedback row be joined straight
    # back to the query that produced it (its strategy/sources/main_query),
    # instead of only carrying a denormalized copy of question/answer/sql.
    # Nullable because older rows predate this column.
    query_code = db.Column(db.String(10), nullable=True, index=True)

    question = db.Column(db.Text, nullable=False)
    answer = db.Column(db.Text, nullable=False)
    sql_query = db.Column(db.Text, nullable=True)
    router_decision = db.Column(db.String(50), nullable=True)

    feedback_type = db.Column(db.String(10), nullable=False)  # like or dislike
    remarks = db.Column(db.Text, nullable=True)

    metamind_snapshot = db.Column(db.JSON, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
