"""
Chat API Routes
Handles conversational interface for data queries
"""
from flask import Blueprint, request, jsonify
from flask import Response, stream_with_context
from flask_jwt_extended import jwt_required, get_jwt_identity
import queue
import json
from app.services.llm_service import LLMService
from flask import Response, stream_with_context, request
from app.services.stream_manager import stream_manager
from app.models.model_config import ModelConfiguration
from app.services.updated_router_services import RouterService

bp = Blueprint('chat', __name__, url_prefix='/api/chat')

@bp.route('/sessions', methods=['GET'])
@jwt_required()
def get_chat_sessions():
    """
    Get all chat sessions
    Query params: workspace_id
    Response: { "sessions": [{id, title, last_message_at, message_count}] }
    """
    # TODO: Implement get chat sessions logic
    pass

@bp.route('/sessions', methods=['POST'])
@jwt_required()
def create_chat_session():
    """
    Create new chat session
    Request: { "title": "Sales Analysis", "workspace_id": 1 }
    Response: { "session": {...} }
    """
    # TODO: Implement create session logic
    pass

@bp.route('/sessions/<int:session_id>', methods=['GET'])
@jwt_required()
def get_chat_session(session_id):
    """
    Get chat session with messages
    Response: { "session": {...}, "messages": [...] }
    """
    # TODO: Implement get session details
    pass

@bp.route('/sessions/<int:session_id>', methods=['DELETE'])
@jwt_required()
def delete_chat_session(session_id):
    """
    Delete chat session
    Response: { "message": "Session deleted" }
    """
    # TODO: Implement delete session logic
    pass

#@bp.route('/message', methods=['POST'])
#@jwt_required()
#def send_message():
#    """
#    Send message in chat
#    Request: { "session_id": 1, "message": "Show me revenue trends", "mode": "query/chat" }
#    Response: { "response": "...", "query_result": {...}, "suggestions": [...] }
#    """
    # Implement send message logic
#    pass

@bp.route('/sessions/<int:session_id>/messages', methods=['GET'])
@jwt_required()
def get_messages(session_id):
    """
    Get messages for session
    Query params: limit, offset
    Response: { "messages": [{id, role, content, timestamp, query_result}] }
    """
    # TODO: Implement get messages logic
    pass

@bp.route('/suggestions', methods=['POST'])
@jwt_required()
def get_suggestions():
    """
    Get query suggestions based on context
    Request: { "partial_query": "Show me", "database_id": 1 }
    Response: { "suggestions": ["Show me top customers", "Show me revenue trends"] }
    """
    # TODO: Implement get suggestions logic
    pass

@bp.route('/stream', methods=['POST'])
@jwt_required()
def stream_message():
    """
    Stream chat response (Server-Sent Events)
    Request: { "session_id": 1, "message": "..." }
    Response: SSE stream
    """
    # TODO: Implement streaming logic
    pass


llm_service = LLMService()
router_service = RouterService()

@bp.route('/message', methods=['POST'])
#@jwt_required() # This requires a valid login token from your frontend
def send_message():
    """
    Send message in chat
    Request: { "session_id": 1, "message": "What is in the document?", "mode": "chat" ,model_name": "llama3" }
    """
    data = request.get_json()
    user_query = data.get('message')
    session_id = data.get('session_id', 1) # Default to 1 if not provided
    model_name = data.get('model_name')

    custom_key = data.get('custom_key', '')
    system_instructions = data.get('system_instructions', '')

    if not user_query:
        return jsonify({"error": "Message is required"}), 400
    
    if not model_name:
        return jsonify({"error": "No valid LLM model selected. Please select a model from the dropdown."}), 400
    
    if model_name.startswith('api://') or model_name.startswith('ollama://'):
        # Querying the record to fetch credentials securely on the server
        config = ModelConfiguration.query.filter_by(model=model_name).first()
        if config:
            db_settings = config.settings or {}
            # If a custom key was saved, use it to override the default credentials pipeline
            if db_settings.get('custom_key'):
                custom_key = db_settings.get('custom_key')
                print(f"DEBUG: Successfully intercepted database router '{model_name}'. Injecting secure custom credentials token.")

    try:
        # STEP 1: Get the answer from your RAG logic in LLMService
        # We will build 'answer_from_docs' in the next step
        #ai_response = llm_service.answer_from_docs(user_query)
        ai_response = router_service.get_smart_response(user_query,session_id=session_id,model_name=model_name,custom_key=custom_key,system_instructions=system_instructions)
        print(f"DEBUG: AI Response from Service: {ai_response}")

        # STEP 2: Return the response in the format the frontend expects
        return jsonify({
            "status": "success",
            "response": ai_response,
            "session_id": session_id,
            "query_result": {}, # Placeholder for structured data if needed
            "suggestions": []
        })

    except Exception as e:
        print(f"Error in chat route: {str(e)}")
        return jsonify({"error": "The AI is having trouble processing that."}), 500
    

@bp.route('/stream_steps', methods=['GET'])
def stream_steps():
    session_id = str(request.args.get('session_id', '1'))

    def generate():
        q = stream_manager.listen(session_id)
        try:
            while True:
                try:
                    payload = q.get(timeout=5)
                    
                    # FIX: Always yield the payload to the browser FIRST
                    yield f"data: {json.dumps(payload)}\n\n"
                    
                    # Now it is safe to break; the browser already has the data
                    if payload.get("step") == "DONE":
                        break 
                except queue.Empty:
                    yield f"data: {json.dumps({'heartbeat': True})}\n\n"
        finally:
            stream_manager.stop_listening(session_id, q)
            print(f"DEBUG: Streaming session {session_id} closed.")
            
    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no'
        }
    )


    
 
    