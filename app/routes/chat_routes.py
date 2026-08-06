"""
Chat API Routes
Handles conversational interface for data queries
"""
from flask import Blueprint, request, jsonify
from flask import Response, stream_with_context
from flask_jwt_extended import jwt_required, get_jwt_identity, verify_jwt_in_request
import queue
import json
from app import db, limiter
from app.services.llm_service import LLMService
from flask import Response, stream_with_context, request
from app.services.stream_manager import stream_manager
from app.models.model_config import ModelConfiguration
from app.models.feedback import ResponseFeedback
from app.models.user import User
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


def get_auth_db_connection():
    base_uri = os.environ.get('ENVIRONMENT_DATABASE_URL') or "postgresql://saarthi:password@db:5432/saarthi_db"
    if "saarthi_db" in base_uri:
        auth_db_uri = base_uri.replace("saarthi_db", "saarthi_auth_db")
    else:
        auth_db_uri = "postgresql://saarthi:password@db:5432/saarthi_auth_db"
    return psycopg2.connect(auth_db_uri)


def _resolve_company_context():
    user_id = get_jwt_identity()
    fallback = {
        "company_code": "default_company",
        "company_name": None,
        "role": "user",
    }

    try:
        conn = get_auth_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT company_code, role, name FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone() or {}
        cur.close()
        conn.close()
        return {
            "company_code": str(row.get("company_code") or fallback["company_code"]).strip() or fallback["company_code"],
            "company_name": row.get("name") or fallback["company_name"],
            "role": str(row.get("role") or fallback["role"]).strip().lower() or fallback["role"],
        }
    except Exception:
        return fallback


def _resolve_feedback_user():
    """Resolve the current user from JWT if available; fallback to user 1."""
    try:
        verify_jwt_in_request(optional=True)
        jwt_identity = get_jwt_identity()
        if jwt_identity:
            user = User.query.get(int(jwt_identity))
            if user:
                return user
    except Exception:
        pass

    fallback_user = User.query.get(1)
    return fallback_user


def _resolve_router_snapshot(router_decision: str):
    try:
        config_path = os.path.join(
            os.path.dirname(__file__), '..', 'services', 'metamind_router_config.json'
        )
        with open(config_path, 'r', encoding='utf-8') as handle:
            full_config = json.load(handle)

        decision = (router_decision or '').upper()
        snapshot = full_config.get(decision)
        if snapshot is None:
            data_sources = full_config.get('routing_menu', {}).get('datasources', {})
            snapshot = data_sources.get(decision)
        return snapshot
    except Exception as exc:
        print(f"⚠️ Could not attach metamind info to feedback: {exc}")
        return None


@bp.route('/feedback', methods=['POST'])
@jwt_required()
def submit_feedback():
    data = request.get_json() or {}

    if data.get('feedback_type') not in ('like', 'dislike'):
        return jsonify({'error': 'feedback_type must be like or dislike'}), 400
    if not data.get('question') or not data.get('answer'):
        return jsonify({'error': 'question and answer are required'}), 400

    current_user = _resolve_feedback_user()
    if not current_user:
        return jsonify({'error': 'No authenticated user found for feedback'}), 401

    try:
        fb = ResponseFeedback(
            user_id=current_user.id,
            company_name=current_user.company_name,
            question=data.get('question'),
            answer=data.get('answer'),
            sql_query=data.get('sql_query'),
            router_decision=data.get('router_decision'),
            feedback_type=data.get('feedback_type'),
            remarks=data.get('remarks'),
            metamind_snapshot=_resolve_router_snapshot(data.get('router_decision'))
        )
        db.session.add(fb)
        db.session.commit()
        return jsonify({'status': 'success'}), 200
    except Exception as exc:
        db.session.rollback()
        print(f"Feedback save failed: {exc}")
        return jsonify({'error': 'Failed to save feedback'}), 500

@bp.route('/sessions', methods=['GET'])
@jwt_required()
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
@jwt_required()
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
@jwt_required()
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
@jwt_required()
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
@jwt_required()
@limiter.limit("20 per minute")
def send_message():
    """
    Send message in chat
    Request: { "session_id": 1, "message": "What is in the document?", "mode": "chat" ,model_name": "llama3" }
    """
    data = request.get_json()
    user_query = data.get('message')
    session_id = data.get('session_id', 1) # Default to 1 if not provided
    model_name = data.get('model_name')

    stream_manager.start_new_query(session_id)

    custom_key = data.get('custom_key', '')
    model_base_url = data.get('model_base_url', '')
    system_instructions = data.get('system_instructions', '')

    if not user_query:
        return jsonify({"error": "Message is required"}), 400
    
    if not model_name:
        return jsonify({"error": "No valid LLM model selected. Please select a model from the dropdown."}), 400
    
    company_ctx = _resolve_company_context()

    if model_name.startswith('api://') or model_name.startswith('ollama://'):
        # Querying the record to fetch credentials securely on the server
        config_rows = ModelConfiguration.query.filter_by(model=model_name).all()
        selected_config = None
        for row in config_rows:
            row_settings = row.settings if isinstance(row.settings, dict) else {}
            if str(row_settings.get('company_code') or '').strip() == company_ctx['company_code']:
                selected_config = row
                break
        if not selected_config and config_rows:
            selected_config = config_rows[0]

        if selected_config:
            db_settings = selected_config.settings or {}
            # If a custom key was saved, use it to override the default credentials pipeline
            if not custom_key and db_settings.get('custom_key'):
                custom_key = db_settings.get('custom_key')
                print(f"DEBUG: Successfully intercepted database router '{model_name}'. Injecting secure custom credentials token.")
            if not model_base_url and db_settings.get('base_url'):
                model_base_url = db_settings.get('base_url')

    try:
        # STEP 1: Get the answer from your RAG logic in LLMService
        # We will build 'answer_from_docs' in the next step
        #ai_response = llm_service.answer_from_docs(user_query)
        current_user = _resolve_feedback_user()
        user_id = current_user.id if current_user else 1
        company_name = current_user.company_name if current_user else None

        ai_response = router_service.get_smart_response(
            user_query,
            session_id=session_id,
            model_name=model_name,
            custom_key=custom_key,
            model_base_url=model_base_url,
            system_instructions=system_instructions,
            company_name=company_ctx.get('company_name') or company_name,
            user_id=user_id,
        )
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
@jwt_required(locations=["query_string"])
def stream_steps():
    session_id = str(request.args.get('session_id', '1'))

    def generate():
        q = stream_manager.listen(session_id)
        try:
            # Send a byte immediately so the browser's EventSource fires
            # `onopen` right away, instead of waiting on the first real step
            # (or up to 5s for a heartbeat). The frontend gates sending the
            # chat request on this connection actually being open, so any
            # delay here directly delays - and can bunch up - live steps.
            yield f"data: {json.dumps({'connected': True})}\n\n"

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


    
 
    