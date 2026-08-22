"""
State definition for LangGraph Data Bridge Agent
"""
from typing import TypedDict, Optional, List, Dict, Any


class DataBridgeState(TypedDict):
    """
    State object that flows through the LangGraph workflow.
    Each agent node reads from and writes to this state.
    """
    # ===== Input =====
    user_query: str
    model_name: Optional[str]
    requested_model_name: Optional[str]
    session_id: Optional[str]
    user_id: Optional[int]
    custom_key: Optional[str]
    system_instructions: Optional[str]
    # Self-learning context built from past response_feedback (like/dislike)
    # rows on similar questions - see _build_feedback_context() in
    # router_service.py. Read by SQLGeneratorAgent to adjust the
    # generated SQL (filters/joins/aggregations/columns) when a past
    # DISLIKED remark is still relevant to this question.
    feedback_context: Optional[str]
    steps: Optional[List[str]]

    # ===== Internal (not persisted/streamed, request-scoped only) =====
    # Per-request agent instances built from the querying user's own
    # schema - see run_data_bridge_agent(). LangGraph only preserves keys
    # declared here across node invocations; anything else is silently
    # dropped from state before it reaches the next node.
    _agents: Optional[Dict[str, Any]]
    # Connection (host/port/dbname/user/password) to run generated SQL
    # against for this request - see resolve_query_execution_config() in
    # automated_metamind.py. None means "use QueryFormatterAgent's own
    # default", not "no database".
    db_config: Optional[Dict[str, Any]]


    # ===== Query Processing =====
    simplified_query: Optional[str]
    query_sense_output: Optional[Dict[str, Any]]
    validation_result: Optional[Dict[str, Any]]
    
    # ===== SQL Generation =====
    generated_sql: Optional[str]
    sql_validation: Optional[Dict[str, Any]]
    
    # ===== Data Execution =====
    query_results: Optional[Dict[str, Any]]
    row_count: int
    columns: Optional[List[str]]
    data: Optional[List[Dict[str, Any]]]
    
    # ===== Insights & Visualization =====
    insights: Optional[List[str]]
    visualizations: Optional[List[Dict[str, Any]]]
    chart_configs: Optional[Dict[str, Any]]
    
    # ===== Control Flow =====
    current_step: str
    error: Optional[str]
    retry_count: int
    max_retries: int
    
    # ===== Error Recovery =====
    error_step: Optional[str]  # Which step failed
    error_diagnosis: Optional[Dict[str, Any]]  # Diagnosis of the error
    error_feedback: Optional[str]  # Feedback for retry attempt
    step_retry_counts: Optional[Dict[str, int]]  # Retry count per step
    recovery_attempt: int  # Overall recovery attempt count
    
    # ===== Final Output =====
    response: Optional[Dict[str, Any]]
    format: Optional[str]
    case: Optional[str]
    message: Optional[str]
