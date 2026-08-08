"""
File Upload API Routes
Handles unstructured data file uploads with document code generation
"""
import os
from flask import Blueprint, request, jsonify, send_file
from werkzeug.utils import secure_filename
from datetime import datetime
from flask_jwt_extended import jwt_required
from app import db, limiter
from app.models.file_resource import FileResource
from app.utils.auth_helpers import get_current_user
from app.services.audit_service import log_event

try:
    import magic
except ImportError:
    magic = None

upload_bp = Blueprint('upload_bp', __name__)

UPLOAD_FOLDER = os.path.join(os.getcwd(), 'uploads')
ALLOWED_EXTENSIONS = set(['pdf', 'docx', 'txt', 'md', 'jpg', 'png', 'gif', 'svg', 'mp4', 'avi', 'mov', 'mkv', 'mp3', 'wav', 'flac', 'm4a', 'eml', 'msg', 'mbox'])

# Regardless of what extension a file claims, its actual bytes should
# never sniff as one of these - executables and scripts disguised with a
# "safe" extension (e.g. a renamed .exe uploaded as "report.pdf"). This is
# deliberately a denylist of dangerous types rather than an allow-list of
# every legitimate MIME variant per extension: an allow-list would need
# exhaustive per-extension coverage (libmagic reports several valid
# variants for the same real format) and risks rejecting genuine files:
# a denylist targets the actual threat without that fragility.
_DANGEROUS_MIME_PREFIXES = (
    'application/x-executable',
    'application/x-dosexec',
    'application/x-sharedlib',
    'application/x-elf',
    'application/x-mach-binary',
    'application/x-msdownload',
    'text/x-shellscript',
    'text/x-python',
    'text/x-perl',
    'text/x-php',
)


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def sniff_dangerous_content(file_path):
    """Returns the sniffed MIME type if the file's actual bytes match a
    known-dangerous type, else None. Fails open (returns None) if magic
    isn't available or sniffing errors, rather than blocking uploads over
    an unrelated failure in the sniffing library itself."""
    if not magic:
        return None
    try:
        mime = magic.from_file(file_path, mime=True)
    except Exception as e:
        print(f"⚠️  Could not sniff content type for {file_path}: {e}")
        return None
    if mime and mime.startswith(_DANGEROUS_MIME_PREFIXES):
        return mime
    return None


@upload_bp.route('/api/upload/unstructured', methods=['POST'])
@jwt_required()
@limiter.limit("20 per minute")
def upload_unstructured():
    current_user = get_current_user()
    if not current_user:
        return jsonify({'error': 'Authentication required'}), 401

    if 'files' not in request.files:
        return jsonify({'error': 'No files part'}), 400

    files = request.files.getlist('files')
    file_type = request.form.get('file_type')
    description = (request.form.get('description') or '').strip() or None
    if not file_type:
        return jsonify({'error': 'No file type provided'}), 400

    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)

    uploaded_files = []
    for file in files:
        if not (file and allowed_file(file.filename)):
            return jsonify({'error': f'File type not allowed: {file.filename}'}), 400

        filename = secure_filename(file.filename)

        # Generate unique filename if exists
        base_name, ext = os.path.splitext(filename)
        counter = 1
        while os.path.exists(os.path.join(UPLOAD_FOLDER, filename)):
            filename = f"{base_name}_{counter}{ext}"
            counter += 1

        save_path = os.path.join(UPLOAD_FOLDER, filename)
        file.save(save_path)

        dangerous_mime = sniff_dangerous_content(save_path)
        if dangerous_mime:
            os.remove(save_path)
            print(f"⚠️  Rejected upload '{file.filename}': sniffed as {dangerous_mime}")
            return jsonify({'error': f"'{file.filename}' was rejected: its content doesn't match a safe file type."}), 400

        file_size = os.path.getsize(save_path)
        now = datetime.now()
        code_prefix = {
            'documents': 'DOC',
            'images': 'IMG',
            'videos': 'VID',
            'audio': 'AUD',
            'emails': 'EML'
        }.get(file_type, 'FILE')
        initials = filename[:3].upper()
        doc_code = f"{code_prefix}-{initials}-{now.strftime('%Y%m%d-%H%M%S')}"

        resource = FileResource(
            document_code=doc_code,
            file_name=filename,
            file_type=file_type,
            file_size=file_size,
            file_path=save_path,
            description=description,
            company_code=current_user.company_code,
            created_by_user_id=current_user.id,
        )
        db.session.add(resource)
        db.session.commit()

        log_event('file_uploaded', company_code=current_user.company_code, user_id=current_user.id,
                   resource_type='file', resource_id=resource.id, details={'file_name': filename})

        uploaded_files.append(resource.to_dict())

    return jsonify({'files': uploaded_files}), 200


@upload_bp.route('/api/upload/files', methods=['GET'])
@jwt_required()
def get_uploaded_files():
    """
    Files a non-admin user uploads are private to them - nothing is
    auto-shared. This lists files the current user created themselves,
    plus any files a company admin has explicitly granted them access to
    via Resource Mapping.
    """
    current_user = get_current_user()
    if not current_user:
        return jsonify({'error': 'Authentication required'}), 401

    own_files = FileResource.query.filter_by(created_by_user_id=current_user.id).all()

    from app.models.resource_mapping import ResourceMapping
    granted_ids = [
        m.resource_id for m in ResourceMapping.query.filter_by(
            resource_type='file', user_id=current_user.id
        ).all()
    ]
    granted_files = FileResource.query.filter(FileResource.id.in_(granted_ids)).all() if granted_ids else []

    seen_ids = set()
    files = []
    for f in own_files + granted_files:
        if f.id not in seen_ids:
            seen_ids.add(f.id)
            files.append(f.to_dict())

    return jsonify({'files': files}), 200


@upload_bp.route('/api/files/view/<document_code>', methods=['GET'])
@jwt_required()
def view_file(document_code):
    resource = FileResource.query.filter_by(document_code=document_code).first()
    if not resource:
        return jsonify({'error': 'File not found'}), 404

    if not resource.file_path or not os.path.exists(resource.file_path):
        return jsonify({'error': 'File not found on disk'}), 404

    return send_file(resource.file_path, as_attachment=False)


@upload_bp.route('/api/files/<document_code>', methods=['DELETE'])
@jwt_required()
def delete_file(document_code):
    current_user = get_current_user()
    if not current_user:
        return jsonify({'error': 'Authentication required'}), 401

    resource = FileResource.query.filter_by(document_code=document_code).first()
    if not resource:
        return jsonify({'error': 'File not found'}), 404

    if resource.created_by_user_id != current_user.id and current_user.role != 'admin':
        return jsonify({'error': 'Only the uploader or a company admin can delete this file'}), 403

    if resource.file_path and os.path.exists(resource.file_path):
        try:
            os.remove(resource.file_path)
        except Exception as e:
            return jsonify({'error': f'Failed to delete file: {str(e)}'}), 500

    db.session.delete(resource)
    db.session.commit()

    log_event('file_deleted', company_code=current_user.company_code, user_id=current_user.id,
               resource_type='file', resource_id=resource.id)

    return jsonify({'message': 'File deleted successfully'}), 200
