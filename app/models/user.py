"""
User Model - single source of truth for authentication and tenancy.

Replaces the old split between an unused SQLAlchemy `app_users` table and
the raw-SQL `users` table in a separate saarthi_auth_db - everything
(login, signup, resource ownership, resource mapping, feedback) now goes
through this one model in the core database.
"""
from app import db
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

ROLE_ADMIN = 'admin'
ROLE_USER = 'user'

STATUS_ACTIVE = 'active'
STATUS_PENDING = 'pending'
STATUS_REJECTED = 'rejected'


class User(db.Model):
    """
    A user's `company_code` is nullable: NULL means an individual account
    (always role=admin over themselves, nothing ever shared with anyone).
    A non-null company_code ties the user to a pre-provisioned Company -
    new signups against an existing company start as role=user,
    status=pending until an existing admin of that company approves them.
    """
    __bind_key__ = 'core'
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)

    company_code = db.Column(db.String(50), db.ForeignKey('companies.company_code'), nullable=True, index=True)
    role = db.Column(db.String(20), nullable=False, default=ROLE_ADMIN)  # 'admin' | 'user'
    status = db.Column(db.String(20), nullable=False, default=STATUS_ACTIVE)  # 'active' | 'pending' | 'rejected'

    email_verified = db.Column(db.Boolean, nullable=False, default=False)
    verification_token = db.Column(db.String(255), nullable=True)
    verification_token_expires = db.Column(db.DateTime, nullable=True)

    # Standing rules this user wants applied to every query they ask (e.g.
    # "for top N questions, rank by total sales amount unless told
    # otherwise") - loaded into the router/answer prompt on every request,
    # see get_smart_response()'s system_instructions handling in
    # router_service.py. Free text, no fixed schema.
    query_instructions = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = db.Column(db.DateTime, nullable=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password, method='scrypt')

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def is_admin_of_company(self, company_code):
        return self.role == ROLE_ADMIN and self.company_code == company_code

    def effective_query_instructions(self, per_message: str = "") -> str:
        """Combines this user's standing Settings-page instructions with
        any ad hoc instructions sent for a single message (e.g. the
        "Instructions.md" chat modal). The persisted default always
        applies to every query; per-message text, when present, is
        layered on top as an addition rather than a replacement, so the
        two mechanisms compose instead of one silently overriding the
        other."""
        parts = [p.strip() for p in (self.query_instructions, per_message) if p and p.strip()]
        return "\n\n".join(parts)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'email': self.email,
            'company_code': self.company_code,
            'role': self.role,
            'status': self.status,
            'email_verified': self.email_verified,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
