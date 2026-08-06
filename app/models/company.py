"""
Company Model - the tenant boundary for the SaaS system.

Companies are pre-provisioned by a superadmin (see app/routes/platform_routes.py)
before anyone can sign up under their company_code - signup against an
unknown code is rejected outright, it never auto-creates a company.
"""
from app import db
from datetime import datetime


class Company(db.Model):
    __bind_key__ = 'core'
    __tablename__ = 'companies'

    company_code = db.Column(db.String(50), primary_key=True)
    company_name = db.Column(db.String(150), nullable=False)
    created_by_email = db.Column(db.String(120), nullable=True)
    # If set, the first person to sign up with this company_code whose
    # email matches (case-insensitive) becomes that company's admin
    # immediately instead of landing in the pending-approval queue -
    # this is how a superadmin designates a company's founding admin at
    # provisioning time, before that person has necessarily signed up yet.
    initial_admin_email = db.Column(db.String(120), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'company_code': self.company_code,
            'company_name': self.company_name,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
