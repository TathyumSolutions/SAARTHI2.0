"""
LLM Connection Model - a registered LLM provider connection (OpenAI,
Anthropic, Azure OpenAI, Google, a custom/self-hosted endpoint, etc.).

Mirrors DatabaseConnection/ApiConnector: created by any authenticated user
as their own private connection (company_code tags tenant ownership but
grants no visibility by itself), api_key stored encrypted (see
app/utils/crypto.py), and only becomes usable by another user of the same
company once an admin grants it to them via Resource Mapping
(resource_type='llm') - see app/models/resource_mapping.py.
"""
from app import db
from datetime import datetime


class LLMConnection(db.Model):
    __bind_key__ = 'resources'
    __tablename__ = 'llm_connections'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    provider = db.Column(db.String(50), nullable=False)  # openai, anthropic, azure_openai, google, custom, ...
    model = db.Column(db.String(100), nullable=False)    # default model id, e.g. gpt-4o, claude-sonnet-5

    # Credentials (encrypted at rest - see app/utils/crypto.py). Nullable
    # since a local/self-hosted endpoint (e.g. Ollama) may need no key.
    api_key = db.Column(db.Text, nullable=True)
    api_base_url = db.Column(db.String(255), nullable=True)  # custom/self-hosted or Azure endpoint
    api_version = db.Column(db.String(50), nullable=True)    # Azure OpenAI api-version

    config = db.Column(db.JSON, default={})  # temperature, max_tokens, deployment_name, headers, etc.
    status = db.Column(db.String(20), default='active')  # active, inactive, error
    error_message = db.Column(db.Text, nullable=True)
    description = db.Column(db.Text, nullable=True)

    # Tenancy: which company this connection belongs to (NULL = individual
    # user's private connection) and who created it - same pattern as
    # DatabaseConnection/ApiConnector.
    company_code = db.Column(db.String(50), nullable=True, index=True)
    created_by_user_id = db.Column(db.Integer, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_tested = db.Column(db.DateTime)

    def to_dict(self, include_api_key=False):
        data = {
            'id': self.id,
            'name': self.name,
            'provider': self.provider,
            'model': self.model,
            'api_base_url': self.api_base_url,
            'api_version': self.api_version,
            'config': self.config or {},
            'status': self.status,
            'error_message': self.error_message,
            'description': self.description,
            'company_code': self.company_code,
            'created_by_user_id': self.created_by_user_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'last_tested': self.last_tested.isoformat() if self.last_tested else None,
        }
        data['api_key'] = self.api_key if include_api_key else ('********' if self.api_key else None)
        return data
