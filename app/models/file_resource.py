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

    # User-editable description, shown alongside (and folded into) the
    # metamind-generated schema info - see automated_metamind.py's
    # introspect_qdrant(). Falls back to an auto-generated blurb when unset.
    description = db.Column(db.Text, nullable=True)

    # uploaded -> processing -> processed, or error (see error_message).
    status = db.Column(db.String(20), default='uploaded', nullable=False)
    error_message = db.Column(db.Text, nullable=True)

    # AI-generated summary of what metamind actually indexed for this file
    # (chunk counts/content breakdown) - kept separate from the user's own
    # `description` above. Written by automated_metamind.py's
    # introspect_qdrant() every time this file's chunks are (re)counted.
    metamind_summary = db.Column(db.Text, nullable=True)

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
            'description': self.description,
            'status': self.status,
            'error_message': self.error_message,
            'metamind_summary': self.metamind_summary,
            'company_code': self.company_code,
            'created_by_user_id': self.created_by_user_id,
            'upload_date': self.created_at.strftime('%Y-%m-%d %H:%M') if self.created_at else None,
        }
