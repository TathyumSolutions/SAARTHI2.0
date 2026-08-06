"""
Audit Log Model - the detailed, actually-written-to log of tenant-relevant
events (signup, approval, resource creation, resource mapping grants,
logins). Replaces the old AuditLog/Activity models that existed but were
never once instantiated anywhere in the app.
"""
from app import db
from datetime import datetime


class AuditLog(db.Model):
    __bind_key__ = 'core'
    __tablename__ = 'audit_logs'

    id = db.Column(db.Integer, primary_key=True)
    company_code = db.Column(db.String(50), nullable=True, index=True)
    user_id = db.Column(db.Integer, nullable=True, index=True)
    action = db.Column(db.String(100), nullable=False, index=True)
    resource_type = db.Column(db.String(20), nullable=True)
    resource_id = db.Column(db.Integer, nullable=True)
    details = db.Column(db.JSON, nullable=True)
    ip_address = db.Column(db.String(50), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    def to_dict(self):
        return {
            'id': self.id,
            'company_code': self.company_code,
            'user_id': self.user_id,
            'action': self.action,
            'resource_type': self.resource_type,
            'resource_id': self.resource_id,
            'details': self.details,
            'ip_address': self.ip_address,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
