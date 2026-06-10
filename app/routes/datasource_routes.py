"""
Datasource API Routes
Handles data source connections (APIs, files, cloud storage)
"""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
import os
import json
from app.services.llm_service import LLMService

bp = Blueprint('datasource', __name__, url_prefix='/api/datasources')

@bp.route('/', methods=['GET'])
@jwt_required()
def get_datasources():
    """
    Get all configured data sources
    Query params: workspace_id, type
    Response: { "datasources": [{id, name, type, status, last_sync}] }
    """
    # TODO: Implement get datasources logic
    pass

@bp.route('/', methods=['POST'])
@jwt_required()
def create_datasource():
    """
    Create new data source connection
    Request: { "name": "Salesforce", "type": "api", "config": {...}, "workspace_id": 1 }
    Response: { "datasource": {...}, "message": "Datasource created" }
    """
    # TODO: Implement create datasource logic
    pass

@bp.route('/<int:datasource_id>', methods=['GET'])
@jwt_required()
def get_datasource(datasource_id):
    """
    Get specific datasource details
    Response: { "datasource": {...} }
    """
    # TODO: Implement get datasource details
    pass

@bp.route('/<int:datasource_id>', methods=['PUT'])
@jwt_required()
def update_datasource(datasource_id):
    """
    Update datasource configuration
    Request: { "name": "...", "config": {...} }
    Response: { "datasource": {...}, "message": "Datasource updated" }
    """
    # TODO: Implement update datasource logic
    pass

@bp.route('/<int:datasource_id>', methods=['DELETE'])
@jwt_required()
def delete_datasource(datasource_id):
    """
    Delete datasource
    Response: { "message": "Datasource deleted" }
    """
    # TODO: Implement delete datasource logic
    pass

@bp.route('/<int:datasource_id>/sync', methods=['POST'])
@jwt_required()
def sync_datasource(datasource_id):
    """
    Trigger data sync for datasource
    Response: { "status": "syncing", "job_id": "..." }
    """
    # TODO: Implement sync logic
    pass

@bp.route('/<int:datasource_id>/test', methods=['POST'])
@jwt_required()
def test_datasource(datasource_id):
    """
    Test datasource connection
    Response: { "status": "success/failed", "error": null }
    """
    # TODO: Implement test connection logic
    pass

@bp.route('/types', methods=['GET'])
def get_datasource_types():
    """
    Get supported datasource types
    Response: { "types": ["api", "file", "s3", "gcs", "azure_blob", "ftp"] }
    """
    # TODO: Implement get types logic
    pass

@bp.route('/upload', methods=['POST'])
@jwt_required()
def upload_file():
    """
    Upload file as datasource
    Form data: file, name, workspace_id
    Response: { "datasource": {...}, "message": "File uploaded" }
    """
    # TODO: Implement file upload logic
    pass

#@bp.route('/unstructured/process/<document_code>', methods=['POST'])
#def process_unstructured_file(document_code):
 #   try:
  #      print(f"\n[AI PIPELINE] Triggered for Document: {document_code}")
        
   #     return jsonify({
    #        "status": "success",
     #       "message": f"Python backend reached! Ready to process {document_code}."
     #   }), 200

    #except Exception as e:
    #    print(f"[ERROR] {str(e)}")
    #    return jsonify({"status": "error", "message": str(e)}), 500
llm_service = LLMService()

UPLOAD_FOLDER = os.path.join(os.getcwd(), 'uploads')
METADATA_FILE = os.path.join(UPLOAD_FOLDER, 'file_metadata.json')    

@bp.route('/unstructured/process/<document_code>', methods=['POST'])
def process_unstructured_file(document_code):
    try:
        # 1. Access the Metadata to find the physical file path
        if not os.path.exists(METADATA_FILE):
            return jsonify({"status": "error", "message": "Metadata file missing."}), 404

        with open(METADATA_FILE, 'r') as f:
            metadata = json.load(f)

        # Look up the specific document info using the code from the URL
        file_info = next((item for item in metadata if item['document_code'] == document_code), None)

        if not file_info:
            return jsonify({"status": "error", "message": f"Document code {document_code} not found."}), 404

        file_path = file_info.get('file_path')
        
        # 2. Trigger the AI Pipeline
        if file_path and os.path.exists(file_path):
            # PASSING document_code here is essential for the Vector DB
            result = llm_service.process_to_embeddings(file_path, document_code=document_code)
            
            if "error" in result:
                return jsonify({"status": "error", "message": result["error"]}), 500

            # 3. Return the results to the Frontend
            return jsonify({
                "status": "success",
                "message": result.get("message"), # Now returns the Vector DB success string
                "data": {
                    "filename": file_info.get('file_name'),
                    "chunk_count": result.get("chunk_count")
                }
            }), 200
        else:
            return jsonify({"status": "error", "message": "Physical file could not be located on disk."}), 404

    except Exception as e:
        # Catch-all for system errors
        return jsonify({"status": "error", "message": str(e)}), 500

# Minimal GET route to keep the blueprint valid