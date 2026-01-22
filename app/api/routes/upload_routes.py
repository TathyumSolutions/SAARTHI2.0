"""
File Upload API Routes
Handles unstructured data file uploads with document code generation
"""
from flask import Blueprint, request, jsonify, send_file
from werkzeug.utils import secure_filename
import os
from datetime import datetime
import json

bp = Blueprint('upload', __name__, url_prefix='/api/upload')

# Configuration
UPLOAD_FOLDER = '/home/claude/saarthi_enterprise_api/uploads'
ALLOWED_EXTENSIONS = {
    'documents': {'pdf', 'docx', 'doc', 'txt', 'md', 'rtf', 'odt'},
    'images': {'jpg', 'jpeg', 'png', 'gif', 'svg', 'bmp', 'webp'},
    'videos': {'mp4', 'avi', 'mov', 'mkv', 'wmv', 'flv', 'webm'},
    'audio': {'mp3', 'wav', 'flac', 'm4a', 'aac', 'ogg', 'wma'},
    'emails': {'eml', 'msg', 'mbox', 'pst'}
}
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB

# Create upload folder if it doesn't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# In-memory storage for uploaded files metadata (replace with database in production)
uploaded_files_db = []

def allowed_file(filename, file_type):
    """Check if file extension is allowed for the given type"""
    if '.' not in filename:
        return False
    ext = filename.rsplit('.', 1)[1].lower()
    return ext in ALLOWED_EXTENSIONS.get(file_type, set())

def generate_document_code(filename, file_type):
    """
    Generate unique document code
    Format: TYPE-INITIALS-YYYYMMDD-HHMMSS
    Example: DOC-SAM-20240122-143052
    """
    now = datetime.now()
    
    # Date and time components
    date_str = now.strftime('%Y%m%d')
    time_str = now.strftime('%H%M%S')
    
    # Get file initials (first 3 letters of filename without extension)
    name_without_ext = os.path.splitext(filename)[0]
    initials = ''.join(c for c in name_without_ext if c.isalnum())[:3].upper()
    if len(initials) < 3:
        initials = initials.ljust(3, 'X')
    
    # Type prefix
    type_prefixes = {
        'documents': 'DOC',
        'images': 'IMG',
        'videos': 'VID',
        'audio': 'AUD',
        'emails': 'EML'
    }
    type_prefix = type_prefixes.get(file_type, 'FILE')
    
    return f"{type_prefix}-{initials}-{date_str}-{time_str}"

@bp.route('/unstructured', methods=['POST'])
def upload_unstructured():
    """
    Upload unstructured data files
    Form data: files (multiple files), file_type (documents/images/videos/audio/emails)
    """
    try:
        # Check if files are present
        if 'files' not in request.files:
            return jsonify({'error': 'No files provided'}), 400
        
        # Get file type
        file_type = request.form.get('file_type')
        if not file_type or file_type not in ALLOWED_EXTENSIONS:
            return jsonify({'error': 'Invalid or missing file type'}), 400
        
        files = request.files.getlist('files')
        if not files or files[0].filename == '':
            return jsonify({'error': 'No files selected'}), 400
        
        uploaded_files = []
        errors = []
        
        for file in files:
            if file and file.filename:
                # Validate file type
                if not allowed_file(file.filename, file_type):
                    errors.append(f"{file.filename}: Invalid file type for {file_type}")
                    continue
                
                # Generate document code
                document_code = generate_document_code(file.filename, file_type)
                
                # Secure filename
                original_filename = file.filename
                filename = secure_filename(file.filename)
                
                # Create subdirectory for file type
                file_type_folder = os.path.join(UPLOAD_FOLDER, file_type)
                os.makedirs(file_type_folder, exist_ok=True)
                
                # Save with document code as filename
                file_extension = os.path.splitext(filename)[1]
                saved_filename = f"{document_code}{file_extension}"
                file_path = os.path.join(file_type_folder, saved_filename)
                
                # Save file
                file.save(file_path)
                file_size = os.path.getsize(file_path)
                
                # Store metadata
                file_metadata = {
                    'document_code': document_code,
                    'file_name': original_filename,
                    'saved_filename': saved_filename,
                    'file_type': file_type,
                    'file_size': file_size,
                    'file_path': file_path,
                    'upload_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'status': 'uploaded'
                }
                
                uploaded_files_db.append(file_metadata)
                uploaded_files.append(file_metadata)
        
        # Prepare response
        response = {
            'message': f'Successfully uploaded {len(uploaded_files)} file(s)',
            'files': uploaded_files,
            'errors': errors if errors else None
        }
        
        return jsonify(response), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@bp.route('/files', methods=['GET'])
def get_uploaded_files():
    """
    Get list of all uploaded files
    Query params: file_type (optional), limit (optional)
    """
    try:
        file_type = request.args.get('file_type')
        limit = request.args.get('limit', type=int)
        
        # Filter by file type if specified
        files = uploaded_files_db
        if file_type:
            files = [f for f in files if f['file_type'] == file_type]
        
        # Sort by upload date (newest first)
        files = sorted(files, key=lambda x: x['upload_date'], reverse=True)
        
        # Apply limit if specified
        if limit:
            files = files[:limit]
        
        return jsonify({'files': files, 'total': len(uploaded_files_db)}), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@bp.route('/files/<document_code>', methods=['GET'])
def get_file_by_code(document_code):
    """Get file metadata by document code"""
    try:
        file_metadata = next((f for f in uploaded_files_db if f['document_code'] == document_code), None)
        
        if not file_metadata:
            return jsonify({'error': 'File not found'}), 404
        
        return jsonify({'file': file_metadata}), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@bp.route('/files/<document_code>', methods=['DELETE'])
def delete_file(document_code):
    """Delete file by document code"""
    try:
        # Find file metadata
        file_metadata = next((f for f in uploaded_files_db if f['document_code'] == document_code), None)
        
        if not file_metadata:
            return jsonify({'error': 'File not found'}), 404
        
        # Delete physical file
        if os.path.exists(file_metadata['file_path']):
            os.remove(file_metadata['file_path'])
        
        # Remove from database
        uploaded_files_db.remove(file_metadata)
        
        return jsonify({'message': 'File deleted successfully'}), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@bp.route('/files/view/<document_code>', methods=['GET'])
def view_file(document_code):
    """View/download file by document code"""
    try:
        # Find file metadata
        file_metadata = next((f for f in uploaded_files_db if f['document_code'] == document_code), None)
        
        if not file_metadata:
            return jsonify({'error': 'File not found'}), 404
        
        # Send file
        return send_file(
            file_metadata['file_path'],
            as_attachment=False,
            download_name=file_metadata['file_name']
        )
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@bp.route('/files/download/<document_code>', methods=['GET'])
def download_file(document_code):
    """Download file by document code"""
    try:
        # Find file metadata
        file_metadata = next((f for f in uploaded_files_db if f['document_code'] == document_code), None)
        
        if not file_metadata:
            return jsonify({'error': 'File not found'}), 404
        
        # Send file as attachment
        return send_file(
            file_metadata['file_path'],
            as_attachment=True,
            download_name=file_metadata['file_name']
        )
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@bp.route('/types', methods=['GET'])
def get_file_types():
    """Get supported file types and their allowed extensions"""
    return jsonify({
        'file_types': {
            'documents': {
                'label': 'Documents',
                'icon': '📄',
                'extensions': list(ALLOWED_EXTENSIONS['documents'])
            },
            'images': {
                'label': 'Images',
                'icon': '🖼️',
                'extensions': list(ALLOWED_EXTENSIONS['images'])
            },
            'videos': {
                'label': 'Videos',
                'icon': '🎥',
                'extensions': list(ALLOWED_EXTENSIONS['videos'])
            },
            'audio': {
                'label': 'Audio Files',
                'icon': '🎵',
                'extensions': list(ALLOWED_EXTENSIONS['audio'])
            },
            'emails': {
                'label': 'Email Archives',
                'icon': '📧',
                'extensions': list(ALLOWED_EXTENSIONS['emails'])
            }
        }
    }), 200
