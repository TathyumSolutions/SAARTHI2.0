"""
Resource Mapping Model - admin-curated grants of a company's resources
(database connections, files, API connectors) to specific users of that
same company. Nothing is auto-shared: a resource only becomes visible to
someone other than its creator once an admin of the same company
explicitly grants it here.
"""
from app import db
from datetime import datetime

RESOURCE_TYPES = ('database', 'file', 'api')


class ResourceMapping(db.Model):
    __bind_key__ = 'core'
    __tablename__ = 'resource_mapping'

    id = db.Column(db.Integer, primary_key=True)
    company_code = db.Column(db.String(50), db.ForeignKey('companies.company_code'), nullable=False, index=True)
    resource_type = db.Column(db.String(20), nullable=False)  # 'database' | 'file' | 'api'
    resource_id = db.Column(db.Integer, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    granted_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

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
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
