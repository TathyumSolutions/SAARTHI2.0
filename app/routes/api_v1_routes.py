from flask import Blueprint, request, jsonify
from app.services.updated_router_services import RouterService

bp = Blueprint('api_v1', __name__, url_prefix='/api/v1')
router_service = RouterService()

@bp.route('/chat', methods=['POST'])
def chat():
    """Chat endpoint
    ---
    summary: Chat query endpoint
    description: Handle a chat query and return LLM results, optional SQL, table data, chart metadata, insights, and reasoning steps.
    consumes:
      - application/json
    produces:
      - application/json
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required:
            - query
          properties:
            query:
              type: string
              description: Natural language question or prompt to send to the router service.
            model:
              type: string
              description: Optional model alias to use for the response.
              example: gpt-4o-mini
            session_id:
              type: integer
              description: Optional session ID for conversation context.
              example: 1
            chat_history:
              type: array
              description: Optional prior chat messages for context.
              items:
                type: object
        examples:
          application/json:
            query: "Show revenue by region for last quarter."
            model: "gpt-4o-mini"
            session_id: 123
            chat_history:
              - user: "What's revenue?"
                assistant: "Revenue is..."
    responses:
      200:
        description: Successful chat response
        schema:
          type: object
          properties:
            answer:
              type: string
            sql:
              type: string
            table:
              type: array
              items:
                type: object
            chart:
              type: object
            insights:
              type: array
              items:
                type: string
            steps:
              type: array
              items:
                type: string
        examples:
          application/json:
            answer: "Here is the result..."
            sql: "SELECT ..."
            table: []
            chart: {}
            insights: []
            steps: []
      400:
        description: Validation error when query is missing
        schema:
          type: object
          properties:
            error:
              type: string
        examples:
          application/json:
            error: "query is required"
      500:
        description: Internal server error
        schema:
          type: object
          properties:
            error:
              type: string
        examples:
          application/json:
            error: "An internal error occurred while processing the chat query."
    """
    data = request.get_json(silent=True) or {}
    query = data.get('query')
    if not query:
        return jsonify({"error": "query is required"}), 400

    model = data.get('model', 'gpt-4o-mini')
    session_id = data.get('session_id', 1)
    chat_history = data.get('chat_history')

    try:
        response = router_service.get_smart_response(
            query,
            model_name=model,
            session_id=session_id,
            chat_history=chat_history
        )

        return jsonify({
            "answer": response.get("answer"),
            "sql": response.get("sql"),
            "table": response.get("table", []),
            "chart": response.get("chart", {}),
            "insights": response.get("insights", []),
            "steps": response.get("steps", []),
        })
    except Exception as e:
        print(f"Error in /api/v1/chat: {e}")
        return jsonify({
            "error": "An internal error occurred while processing the chat query."
        }), 500
