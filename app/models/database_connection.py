"""
Database Connection Model
"""
from app import db
from datetime import datetime
from typing import Optional, Dict, Any

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
    
    def to_dict(self, include_password=False):
        """Convert to dictionary (exclude sensitive data)"""
        data = {
            'id': self.id,
            'name': self.name,
            'type': self.type,
            'host': self.host,
            'port': self.port,
            'database': self.database,
            'username': self.username,
            'workspace_id': self.workspace_id,
            'status': self.status,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'last_tested': self.last_tested
        }
        
        if include_password:
            data['password'] = self.password
        else:
            data['password'] = '********'
        
        # Include additional attributes
        for key, value in self.__dict__.items():
            if key not in data and not key.startswith('_'):
                data[key] = value
        
        return data
    
    def update(self, **kwargs):
        """Update connection fields"""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
        self.updated_at = datetime.now().isoformat()
    
    @classmethod
    def create(cls, **kwargs):
        """Create and save a new connection"""
        connection = cls(**kwargs)
        cls._connections.append(connection)
        return connection
    
    @classmethod
    def get_all(cls):
        """Get all connections"""
        return cls._connections
    
    @classmethod
    def get_by_id(cls, connection_id: int):
        """Get connection by ID"""
        return next((conn for conn in cls._connections if conn.id == connection_id), None)
    
    @classmethod
    def delete_by_id(cls, connection_id: int):
        """Delete connection by ID"""
        cls._connections = [conn for conn in cls._connections if conn.id != connection_id]
        return True
