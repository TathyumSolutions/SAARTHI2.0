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
