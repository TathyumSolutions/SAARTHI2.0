"""
API Connector Model - a registered external REST API tool
(API Integrations page). Replaces the old raw-SQL `registered_tools`
table that lived in a separate saarthi_api_db with no tenant tagging.
"""
from app import db
from datetime import datetime


class ApiConnector(db.Model):
    __bind_key__ = 'resources'
    __tablename__ = 'api_connectors'

    id = db.Column(db.Integer, primary_key=True)
    integration_name = db.Column(db.String(100), unique=True, nullable=False)
    base_url = db.Column(db.Text, nullable=False)
    endpoint = db.Column(db.Text, nullable=False)
    method = db.Column(db.String(10), nullable=False, default='GET')
    auth_type = db.Column(db.String(50), nullable=False, default='No Auth')
    api_token = db.Column(db.Text)
    api_description = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default='Active')

    company_code = db.Column(db.String(50), nullable=True, index=True)
    created_by_user_id = db.Column(db.Integer, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self, include_token=False):
        data = {
            'id': self.id,
            'integration_name': self.integration_name,
            'base_url': self.base_url,
            'endpoint': self.endpoint,
            'method': self.method,
            'auth_type': self.auth_type,
            'api_description': self.api_description,
            'status': self.status,
            'company_code': self.company_code,
            'created_by_user_id': self.created_by_user_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
        data['api_token'] = self.api_token if include_token else ('********' if self.api_token else None)
        return data
