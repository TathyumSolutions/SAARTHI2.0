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
import os  # 👈 Fixes the 'environ' underline
import psycopg2
from psycopg2.extras import RealDictCursor
from app.services.updated_router_services import RouterService

bp = Blueprint('chat', __name__, url_prefix='/api/chat')

def get_chats_db_connection():
    # Fallback default connection URI pointing to the postgres container if not set in environment
    base_uri = os.environ.get('ENVIRONMENT_DATABASE_URL') or "postgresql://saarthi:password@db:5432/saarthi_db"
    if "saarthi_db" in base_uri:
        chats_db_uri = base_uri.replace("saarthi_db", "saarthi_chats_db")
    else:
        chats_db_uri = "postgresql://saarthi:password@db:5432/saarthi_chats_db"
    return psycopg2.connect(chats_db_uri)

@bp.route('/sessions', methods=['GET'])
def get_chat_sessions():
    """
    Get all chat sessions from saarthi_chats_db ordered chronologically.
    Response: { "sessions": [{session_id, title, updated_at}] }
    """
    try:
        conn = get_chats_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT session_id, title, updated_at FROM chat_sessions ORDER BY updated_at DESC;")
        sessions = cursor.fetchall()
        cursor.close()
        conn.close()
        return jsonify({"sessions": sessions})
    except Exception as e:
        print(f"Error fetching audit sessions: {e}")
        return jsonify({"error": "Failed to load audit logs"}), 500

@bp.route('/sessions', methods=['POST'])
def create_chat_session():
    """
    Save or Update a chat session's visual layout HTML string inside saarthi_chats_db.
    Request body: { "session_id": "...", "title": "...", "chat_history": "..." }
    """
    data = request.get_json() or {}
    session_id = data.get('session_id')
    title = data.get('title', 'New Chat Session')
    chat_history = data.get('chat_history', '')

    if not session_id:
        return jsonify({"error": "Session ID token required"}), 400

    try:
        conn = get_chats_db_connection()
        cursor = conn.cursor()
        # Upsert query configuration: Update if session exists, else Insert new
        query = """
        INSERT INTO chat_sessions (session_id, title, chat_history, updated_at)
        VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
        ON CONFLICT (session_id) 
        DO UPDATE SET title = EXCLUDED.title, chat_history = EXCLUDED.chat_history, updated_at = CURRENT_TIMESTAMP;
        """
        cursor.execute(query, (session_id, title, chat_history))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"status": "success", "message": "Session saved persistently"})
    except Exception as e:
        print(f"Error saving chat history log: {e}")
        return jsonify({"error": "Failed to update persistent history trail"}), 500

@bp.route('/sessions/<string:session_id>', methods=['GET'])
def get_chat_session(session_id):
    """
    Get a specific chat session's layout logs to rebuild the workspace window.
    """
    try:
        conn = get_chats_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT session_id, title, chat_history FROM chat_sessions WHERE session_id = %s;", (session_id,))
        session = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if not session:
            return jsonify({"error": "Historical trail item not found"}), 404
        return jsonify({"session": session})
    except Exception as e:
        print(f"Error viewing single chat trace: {e}")
        return jsonify({"error": "Failed to open conversation node"}), 500

@bp.route('/sessions/<string:session_id>', methods=['DELETE'])
def delete_chat_session(session_id):
    """
    🗑️ Delete a chat session permanently from the Audit Trail database.
    """
    try:
        conn = get_chats_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM chat_sessions WHERE session_id = %s;", (session_id,))
        conn.commit()
        deleted_count = cursor.rowcount
        cursor.close()
        conn.close()
        
        if deleted_count == 0:
            return jsonify({"error": "Session not found"}), 404
            
        return jsonify({"status": "success", "message": "Session deleted from audit records"})
    except Exception as e:
        print(f"Error removing audit target frame: {e}")
        return jsonify({"error": "Failed to drop session tracking state"}), 500    

# @bp.route('/sessions', methods=['GET'])
# @jwt_required()
# def get_chat_sessions():
#     """
#     Get all chat sessions
#     Query params: workspace_id
#     Response: { "sessions": [{id, title, last_message_at, message_count}] }
#     """
#     # TODO: Implement get chat sessions logic
#     pass

# @bp.route('/sessions', methods=['POST'])
# @jwt_required()
# def create_chat_session():
#     """
#     Create new chat session
#     Request: { "title": "Sales Analysis", "workspace_id": 1 }
#     Response: { "session": {...} }
#     """
#     # TODO: Implement create session logic
#     pass

# @bp.route('/sessions/<int:session_id>', methods=['GET'])
# @jwt_required()
# def get_chat_session(session_id):
#     """
#     Get chat session with messages
#     Response: { "session": {...}, "messages": [...] }
#     """
#     # TODO: Implement get session details
#     pass

# @bp.route('/sessions/<int:session_id>', methods=['DELETE'])
# @jwt_required()
# def delete_chat_session(session_id):
#     """
#     Delete chat session
#     Response: { "message": "Session deleted" }
#     """
#     # TODO: Implement delete session logic
#     pass

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


    
 
    