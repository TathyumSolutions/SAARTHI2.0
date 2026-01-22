"""
Database Connection Model
"""
from app import db
from datetime import datetime

class DatabaseConnection(db.Model):
    """Database connection configuration"""
    __tablename__ = 'database_connections'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    type = db.Column(db.String(50), nullable=False)  # PostgreSQL, MySQL, MongoDB, etc.
    
    # Connection details (encrypted)
    host = db.Column(db.String(255))
    port = db.Column(db.Integer)
    database = db.Column(db.String(100))
    username = db.Column(db.String(100))
    password = db.Column(db.Text)  # Encrypted
    connection_string = db.Column(db.Text)  # For complex connections
    
    # Configuration
    config = db.Column(db.JSON, default={})
    status = db.Column(db.String(20), default='active')  # active, inactive, error
    
    # Relationships
    workspace_id = db.Column(db.Integer, db.ForeignKey('workspaces.id'), nullable=False)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_tested = db.Column(db.DateTime)
    
    def to_dict(self):
        """Convert to dictionary (exclude sensitive data)"""
        # TODO: Implement serialization
        pass
    
    def encrypt_password(self, password):
        """Encrypt password"""
        # TODO: Implement encryption
        pass
    
    def decrypt_password(self):
        """Decrypt password"""
        # TODO: Implement decryption
        pass
