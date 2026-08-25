"""
LLM Call Log Model - one row per individual LLM invocation anywhere in the
app (RAG synthesis, SQL/query generation, routing decisions, summaries,
captions, etc.), cloud (OpenAI/Anthropic/Gemini/DeepSeek) and local (Ollama)
alike. Powers the "LLM Calls" page: a user-readable log of every call with
its token counts and cost, groupable by purpose (the sub-menus).
"""
from app import db
from datetime import datetime


class LLMCallLog(db.Model):
    __bind_key__ = 'workspace'
    __tablename__ = 'llm_call_logs'

    id = db.Column(db.Integer, primary_key=True)
    # Fixed-width LLMC########## code (4 letters + 8 zero-padded digits),
    # e.g. LLMC00000001 - see app/utils/llm_call_codes.py.
    call_code = db.Column(db.String(12), unique=True, nullable=False, index=True)

    user_id = db.Column(db.Integer, nullable=True, index=True)
    company_code = db.Column(db.String(50), nullable=True, index=True)
    session_id = db.Column(db.String(100), nullable=True, index=True)
    # Links back to QueryLog.query_code when this call happened while
    # answering a logged chat query - null for calls outside that flow
    # (document ingestion summaries, image captioning, etc.).
    query_code = db.Column(db.String(10), nullable=True, index=True)

    # Short dotted label identifying where in the app this call came from,
    # e.g. "rag.answer", "rag.hyde", "router.decision", "sql_generator",
    # "query_formatter", "query_simplifier", "query_sense", "data_insight",
    # "metamind.summary". This is what the LLM Calls page groups into
    # sub-menus.
    purpose = db.Column(db.String(100), nullable=False, index=True)
    provider = db.Column(db.String(50), nullable=True, index=True)
    model = db.Column(db.String(150), nullable=False, index=True)

    prompt_tokens = db.Column(db.Integer, nullable=True)
    completion_tokens = db.Column(db.Integer, nullable=True)
    total_tokens = db.Column(db.Integer, nullable=True)

    # USD, computed from the settings-driven pricing table at log time.
    cost = db.Column(db.Float, nullable=True)
    currency = db.Column(db.String(8), default='USD')

    duration_ms = db.Column(db.Integer, nullable=True)
    status = db.Column(db.String(10), default='success', index=True)  # success | error
    error_message = db.Column(db.Text, nullable=True)

    # Truncated (per llm_logging.preview_max_chars) prompt/response text so
    # the log stays human-readable without ballooning the table - gated by
    # llm_logging.log_prompts so a deployment can disable prompt capture
    # entirely and keep only the metering columns above.
    prompt_preview = db.Column(db.Text, nullable=True)
    response_preview = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    def to_dict(self):
        return {
            'call_code': self.call_code,
            'user_id': self.user_id,
            'company_code': self.company_code,
            'session_id': self.session_id,
            'query_code': self.query_code,
            'purpose': self.purpose,
            'provider': self.provider,
            'model': self.model,
            'prompt_tokens': self.prompt_tokens,
            'completion_tokens': self.completion_tokens,
            'total_tokens': self.total_tokens,
            'cost': self.cost,
            'currency': self.currency,
            'duration_ms': self.duration_ms,
            'status': self.status,
            'error_message': self.error_message,
            'prompt_preview': self.prompt_preview,
            'response_preview': self.response_preview,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
