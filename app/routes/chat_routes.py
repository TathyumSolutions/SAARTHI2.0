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
from app.models.query_log import QueryLog
from app.models.user import User
from app.models.chat import ChatSession
from app.services.updated_router_services import RouterService

bp = Blueprint('chat', __name__, url_prefix='/api/chat')


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


def _resolve_router_snapshot(router_decision: str, user_id: int):
    try:
        from app.services.automated_metamind import generate_router_config
        menu = generate_router_config(user_id)
        if not menu:
            return None

        decision = (router_decision or '').upper()
        data_sources = menu.get('routing_menu', {}).get('datasources', {})
        return data_sources.get(decision)
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
            company_code=current_user.company_code,
            question=data.get('question'),
            answer=data.get('answer'),
            sql_query=data.get('sql_query'),
            router_decision=data.get('router_decision'),
            feedback_type=data.get('feedback_type'),
            remarks=data.get('remarks'),
            metamind_snapshot=_resolve_router_snapshot(data.get('router_decision'), current_user.id)
        )
        db.session.add(fb)

        # Mirror the rating onto the Queries log row this answer came from
        # (if the caller sent one) - this is what lets the Queries section
        # filter by accepted/rejected, and what the self-learning reuse
        # match in updated_router_services.py looks for (only ever reuses
        # a query that was explicitly liked here).
        query_code = data.get('query_code')
        if query_code:
            logged_query = QueryLog.query.filter_by(query_code=query_code).first()
            if logged_query:
                logged_query.feedback_type = data.get('feedback_type')
                logged_query.remarks = data.get('remarks')

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
    Get the current user's chat sessions, ordered chronologically. Chat
    history is personal, not a shared company resource - each user only
    ever sees their own sessions here regardless of company.
    Response: { "sessions": [{session_id, title, updated_at}] }
    """
    current_user = _resolve_feedback_user()
    if not current_user:
        return jsonify({"error": "Authentication required"}), 401
    try:
        sessions = (
            ChatSession.query
            .filter_by(user_id=current_user.id)
            .order_by(ChatSession.updated_at.desc())
            .all()
        )
        return jsonify({"sessions": [
            {"session_id": s.session_id, "title": s.title, "updated_at": s.updated_at.isoformat() if s.updated_at else None}
            for s in sessions
        ]})
    except Exception as e:
        print(f"Error fetching chat sessions: {e}")
        return jsonify({"error": "Failed to load chat sessions"}), 500

@bp.route('/sessions', methods=['POST'])
@jwt_required()
def create_chat_session():
    """
    Save or update a chat session's visual layout HTML string.
    Request body: { "session_id": "...", "title": "...", "chat_history": "..." }
    """
    current_user = _resolve_feedback_user()
    if not current_user:
        return jsonify({"error": "Authentication required"}), 401

    data = request.get_json() or {}
    session_id = data.get('session_id')
    title = data.get('title', 'New Chat Session')
    chat_history = data.get('chat_history', '')

    if not session_id:
        return jsonify({"error": "Session ID token required"}), 400

    try:
        session = ChatSession.query.filter_by(session_id=session_id).first()
        if session and session.user_id != current_user.id:
            return jsonify({"error": "Session not found"}), 404

        if session:
            session.title = title
            session.chat_history = chat_history
        else:
            session = ChatSession(
                session_id=session_id,
                title=title,
                chat_history=chat_history,
                company_code=current_user.company_code,
                user_id=current_user.id,
            )
            db.session.add(session)
        db.session.commit()
        return jsonify({"status": "success", "message": "Session saved persistently"})
    except Exception as e:
        db.session.rollback()
        print(f"Error saving chat history log: {e}")
        return jsonify({"error": "Failed to update persistent history trail"}), 500

@bp.route('/sessions/<string:session_id>', methods=['GET'])
@jwt_required()
def get_chat_session(session_id):
    """
    Get a specific chat session's layout logs to rebuild the workspace window.
    """
    current_user = _resolve_feedback_user()
    if not current_user:
        return jsonify({"error": "Authentication required"}), 401
    try:
        session = ChatSession.query.filter_by(session_id=session_id).first()
        if not session or session.user_id != current_user.id:
            return jsonify({"error": "Historical trail item not found"}), 404
        return jsonify({"session": session.to_dict()})
    except Exception as e:
        print(f"Error viewing single chat trace: {e}")
        return jsonify({"error": "Failed to open conversation node"}), 500

@bp.route('/sessions/<string:session_id>', methods=['DELETE'])
@jwt_required()
def delete_chat_session(session_id):
    """
    Delete a chat session permanently.
    """
    current_user = _resolve_feedback_user()
    if not current_user:
        return jsonify({"error": "Authentication required"}), 401
    try:
        session = ChatSession.query.filter_by(session_id=session_id).first()
        if not session or session.user_id != current_user.id:
            return jsonify({"error": "Session not found"}), 404

        db.session.delete(session)
        db.session.commit()
        return jsonify({"status": "success", "message": "Session deleted from audit records"})
    except Exception as e:
        db.session.rollback()
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
        current_user = _resolve_feedback_user()
        user_id = current_user.id if current_user else 1
        company_code = current_user.company_code if current_user else None

        ai_response = router_service.get_smart_response(
            user_query,
            session_id=session_id,
            model_name=model_name,
            custom_key=custom_key,
            system_instructions=system_instructions,
            company_code=company_code,
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

    # The frontend opens this connection BEFORE sending the actual chat
    # request (it gates the POST on this stream's onopen firing), so this
    # is the true start of a new query - clearing history here, before
    # listen() below flushes whatever's currently buffered, is what stops
    # a fresh connection from immediately replaying the previous query's
    # steps. Clearing only in the /message handler (still done, as a
    # backstop for any caller that isn't this SSE flow) was always too
    # late: that runs only after this connection already flushed the old
    # history into the new listener's queue.
    stream_manager.start_new_query(session_id)

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


    
 
    