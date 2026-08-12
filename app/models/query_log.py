"""
Query Log Model - one row per chat query that reached a data-source track
(DB, API, files, spreadsheet, general). Powers the "Queries" section of the
Knowledge Base page: what was asked, the strategy/sources/main query used to
answer it, whether it was freshly executed or reused from a prior accepted
(liked) query, and any self-learning feedback given on it.
"""
from app import db
from datetime import datetime


class QueryLog(db.Model):
    __bind_key__ = 'workspace'
    __tablename__ = 'query_logs'

    id = db.Column(db.Integer, primary_key=True)
    # Fixed-width QUERY##### code (5 letters + 5 digits = 10 chars), e.g.
    # QUERY00001 - see app/utils/query_codes.py for the generator.
    query_code = db.Column(db.String(10), unique=True, nullable=False, index=True)

    user_id = db.Column(db.Integer, nullable=False, index=True)
    company_code = db.Column(db.String(50), nullable=True, index=True)

    question = db.Column(db.Text, nullable=False)
    answer = db.Column(db.Text, nullable=True)
    router_decision = db.Column(db.String(50), nullable=True, index=True)

    strategy = db.Column(db.Text, nullable=True)
    sources = db.Column(db.JSON, nullable=True)
    main_query = db.Column(db.Text, nullable=True)

    # 'fresh' - generated and executed from scratch this run.
    # 'reused' - a strong semantic match against a previously-accepted
    # (liked) query was found, and that query's main_query was re-executed
    # instead of regenerating it.
    execution_type = db.Column(db.String(10), nullable=False, default='fresh')
    matched_query_code = db.Column(db.String(10), nullable=True, index=True)
    match_score = db.Column(db.Float, nullable=True)

    # Populated later, if/when the user rates this answer - mirrors
    # ResponseFeedback's feedback_type/remarks so the Queries section can
    # show the same self-learning signal without a second lookup.
    feedback_type = db.Column(db.String(10), nullable=True, index=True)  # like or dislike
    remarks = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    def to_dict(self):
        return {
            'query_code': self.query_code,
            'user_id': self.user_id,
            'company_code': self.company_code,
            'question': self.question,
            'answer': self.answer,
            'router_decision': self.router_decision,
            'strategy': self.strategy,
            'sources': self.sources or [],
            'main_query': self.main_query,
            'execution_type': self.execution_type,
            'matched_query_code': self.matched_query_code,
            'match_score': self.match_score,
            'feedback_type': self.feedback_type,
            'remarks': self.remarks,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
