"""
File Upload API Routes
Handles unstructured data file uploads with document code generation
"""
import os
from flask import Blueprint, request, jsonify, current_app, send_file, send_from_directory
from werkzeug.utils import secure_filename
from datetime import datetime
import json

upload_bp = Blueprint('upload_bp', __name__)

UPLOAD_FOLDER = os.path.join(os.getcwd(), 'uploads')
METADATA_FILE = os.path.join(UPLOAD_FOLDER, 'file_metadata.json')
ALLOWED_EXTENSIONS = set(['pdf', 'docx', 'txt', 'md', 'jpg', 'png', 'gif', 'svg', 'mp4', 'avi', 'mov', 'mkv', 'mp3', 'wav', 'flac', 'm4a', 'eml', 'msg', 'mbox'])

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def load_metadata():
    """Load file metadata from JSON file"""
    if os.path.exists(METADATA_FILE):
        try:
            with open(METADATA_FILE, 'r') as f:
                return json.load(f)
        except:
            return []
    return []

def save_metadata(metadata):
    """Save file metadata to JSON file"""
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)
    with open(METADATA_FILE, 'w') as f:
        json.dump(metadata, f, indent=2)

@upload_bp.route('/api/upload/unstructured', methods=['POST'])
def upload_unstructured():
    if 'files' not in request.files:
        return jsonify({'error': 'No files part'}), 400

    files = request.files.getlist('files')
    file_type = request.form.get('file_type')
    if not file_type:
        return jsonify({'error': 'No file type provided'}), 400

    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)

    # Load existing metadata
    metadata = load_metadata()

    uploaded_files = []
    for file in files:
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            
            # Generate unique filename if exists
            base_name, ext = os.path.splitext(filename)
            counter = 1
            while os.path.exists(os.path.join(UPLOAD_FOLDER, filename)):
                filename = f"{base_name}_{counter}{ext}"
                counter += 1
            
            save_path = os.path.join(UPLOAD_FOLDER, filename)
            file.save(save_path)
            file_size = os.path.getsize(save_path)
            now = datetime.now()
            date_str = now.strftime('%Y-%m-%d %H:%M')
            code_prefix = {
                'documents': 'DOC',
                'images': 'IMG',
                'videos': 'VID',
                'audio': 'AUD',
                'emails': 'EML'
            }.get(file_type, 'FILE')
            initials = filename[:3].upper()
            doc_code = f"{code_prefix}-{initials}-{now.strftime('%Y%m%d-%H%M%S')}"
            
            file_info = {
                'document_code': doc_code,
                'file_name': filename,
                'file_type': file_type,
                'file_size': file_size,
                'upload_date': date_str,
                'file_path': save_path
            }
            
            uploaded_files.append(file_info)
            metadata.append(file_info)
        else:
            return jsonify({'error': f'File type not allowed: {file.filename}'}), 400

    # Save updated metadata
    save_metadata(metadata)

    return jsonify({'files': uploaded_files}), 200

@upload_bp.route('/api/upload/files', methods=['GET'])
def get_uploaded_files():
    """Get list of all uploaded files"""
    metadata = load_metadata()
    return jsonify({'files': metadata}), 200

@upload_bp.route('/api/files/view/<document_code>', methods=['GET'])
def view_file(document_code):
    """View/download a file by document code"""
    metadata = load_metadata()
    
    file_info = None
    for item in metadata:
        if item['document_code'] == document_code:
            file_info = item
            break
    
    if not file_info:
        return jsonify({'error': 'File not found'}), 404
    
    file_path = file_info.get('file_path')
    if not file_path or not os.path.exists(file_path):
        return jsonify({'error': 'File not found on disk'}), 404
    
    return send_file(file_path, as_attachment=False)

@upload_bp.route('/api/files/<document_code>', methods=['DELETE'])
def delete_file(document_code):
    """Delete a file by document code"""
    metadata = load_metadata()
    
    file_info = None
    file_index = None
    for idx, item in enumerate(metadata):
        if item['document_code'] == document_code:
            file_info = item
            file_index = idx
            break
    
    if not file_info:
        return jsonify({'error': 'File not found'}), 404
    
    # Delete physical file
    file_path = file_info.get('file_path')
    if file_path and os.path.exists(file_path):
        try:
            os.remove(file_path)
        except Exception as e:
            return jsonify({'error': f'Failed to delete file: {str(e)}'}), 500
    
    # Remove from metadata
    metadata.pop(file_index)
    save_metadata(metadata)
    
    return jsonify({'message': 'File deleted successfully'}), 200
