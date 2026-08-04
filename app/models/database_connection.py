"""
Database Connection Model - a registered external database (real customer
systems like SAP, or the demo SAP database once it's registered like any
other external connection).
"""
from app import db
from datetime import datetime


class DatabaseConnection(db.Model):
    __bind_key__ = 'resources'
    __tablename__ = 'database_connections'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    type = db.Column(db.String(50), nullable=False)  # PostgreSQL, MySQL, SAP HANA, etc.

    # Connection details (password stored encrypted - see app/utils/crypto.py)
    host = db.Column(db.String(255))
    port = db.Column(db.Integer)
    database = db.Column(db.String(100))
    username = db.Column(db.String(100))
    password = db.Column(db.Text)
    connection_string = db.Column(db.Text)

    config = db.Column(db.JSON, default={})
    status = db.Column(db.String(20), default='active')  # active, inactive, error

    # Tenancy: which company this resource belongs to (NULL = individual
    # user's private resource, never visible to anyone else) and who
    # created it.
    company_code = db.Column(db.String(50), nullable=True, index=True)
    created_by_user_id = db.Column(db.Integer, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_tested = db.Column(db.DateTime)

    def to_dict(self, include_password=False):
        data = {
            'id': self.id,
            'name': self.name,
            'type': self.type,
            'host': self.host,
            'port': self.port,
            'database': self.database,
            'username': self.username,
            'status': self.status,
            'company_code': self.company_code,
            'created_by_user_id': self.created_by_user_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'last_tested': self.last_tested.isoformat() if self.last_tested else None,
        }
        data['password'] = self.password if include_password else '********'
        return data
