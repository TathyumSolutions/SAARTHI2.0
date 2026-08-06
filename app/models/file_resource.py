"""
File Resource Model - metadata for an uploaded unstructured-data file.
Replaces the old flat uploads/file_metadata.json file, which had no
tenant tagging at all and no query/index capability.
"""
from app import db
from datetime import datetime


class FileResource(db.Model):
    __bind_key__ = 'resources'
    __tablename__ = 'files'

    id = db.Column(db.Integer, primary_key=True)
    document_code = db.Column(db.String(100), unique=True, nullable=False, index=True)
    file_name = db.Column(db.String(255), nullable=False)
    file_type = db.Column(db.String(50))
    file_size = db.Column(db.Integer)
    file_path = db.Column(db.Text, nullable=False)

    company_code = db.Column(db.String(50), nullable=True, index=True)
    created_by_user_id = db.Column(db.Integer, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'document_code': self.document_code,
            'file_name': self.file_name,
            'file_type': self.file_type,
            'file_size': self.file_size,
            'file_path': self.file_path,
            'company_code': self.company_code,
            'created_by_user_id': self.created_by_user_id,
            'upload_date': self.created_at.strftime('%Y-%m-%d %H:%M') if self.created_at else None,
        }
