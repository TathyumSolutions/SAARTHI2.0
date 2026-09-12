"""
Resource Mapping Model - admin-curated grants of a company's resources
(database connections, files, API connectors, Model Configurations - see
app/models/model_config.py) to specific users of that same company.
Nothing is auto-shared: a resource only becomes visible to someone other
than its creator once an admin of the same company explicitly grants it
here.

daily_budget/budget_currency only apply to 'llm' grants (a Model
Configuration allocation may cap how much that user can spend on it per
day - see app/services/model_config_access_service.py); they stay NULL
for every other resource_type.
"""
from app import db
from datetime import datetime

RESOURCE_TYPES = ('database', 'file', 'api', 'llm')


class ResourceMapping(db.Model):
    __bind_key__ = 'core'
    __tablename__ = 'resource_mapping'

    id = db.Column(db.Integer, primary_key=True)
    company_code = db.Column(db.String(50), db.ForeignKey('companies.company_code'), nullable=False, index=True)
    resource_type = db.Column(db.String(20), nullable=False)  # 'database' | 'file' | 'api' | 'llm'
    resource_id = db.Column(db.Integer, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    granted_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    # Daily spend cap for this grant, in budget_currency (NULL = unlimited).
    # Meaningful only when resource_type='llm'.
    daily_budget = db.Column(db.Numeric(10, 2), nullable=True)
    budget_currency = db.Column(db.String(3), nullable=False, default='USD')

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('resource_type', 'resource_id', 'user_id', name='uq_resource_mapping_target'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'company_code': self.company_code,
            'resource_type': self.resource_type,
            'resource_id': self.resource_id,
            'user_id': self.user_id,
            'granted_by_user_id': self.granted_by_user_id,
            'daily_budget': float(self.daily_budget) if self.daily_budget is not None else None,
            'budget_currency': self.budget_currency,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
