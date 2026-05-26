"""
Router functions for conditional edges in LangGraph
"""
from typing import Literal
from .agent_state import DataBridgeState


def validation_router(state: DataBridgeState) -> Literal["sql_generator", "query_formatter", "error_diagnosis", "error_handler"]:
    """
    Unified router for both schema and SQL validation.
    Checks if we have generated_sql to determine which validation to route on.
    
    Returns:
        "sql_generator" if schema validation passed (first time)
        "query_formatter" if SQL validation passed
        "sql_generator" if SQL validation failed but retries remain (retry loop)
        "error_diagnosis" if error needs diagnosis
        "error_handler" if validation failed
    """
    # Check if we have SQL generated (means this is SQL validation)
    if state.get("generated_sql") is not None:
        # SQL Validation routing
        validation = state.get("sql_validation")
        
        # Handle case where sql_validation is None
        if validation is None:
            print("⚠️ [Router] SQL validation is None, treating as failed")
            validation = {"status": "failed", "message": "SQL validation not performed"}
        # 1. This handles the case-sensitivity (Passed vs passed)
        status = str(validation.get("status", "failed")).lower().strip()
        
        retry_count = state.get("retry_count", 0)
        max_retries = state.get("max_retries", 2)
        
        # 2. This checks for any "success" keyword
        if status in ["passed", "success", "valid"]:
            print("🔀 [Router] SQL validation passed → Query Formatter")
            return "query_formatter"


        #status = validation.get("status", "failed")
        #retry_count = state.get("retry_count", 0)
        #max_retries = state.get("max_retries", 2)
        
        #if status == "passed":
           # print("🔀 [Router] SQL validation passed → Query Formatter")
            #return "query_formatter"
        elif retry_count < max_retries:
            print(f"🔀 [Router] SQL validation failed (retry {retry_count}/{max_retries}) → Error Diagnosis")
            state["error"] = validation.get("message", "SQL validation failed")
            return "error_diagnosis"
        else:
            print(f"🔀 [Router] SQL validation failed (max retries reached) → Error Handler")
            state["error"] = validation.get("message", "SQL validation failed after max retries")
            return "error_handler"
    else:
        # Check if SQL generation failed (generated_sql is explicitly None with error)
        if state.get("error") and state.get("current_step") == "sql_generator":
            print("🔀 [Router] SQL generation failed → Error Diagnosis")
            return "error_diagnosis"
        
        # Schema Validation routing
        validation = state.get("validation_result", {})
        status = validation.get("status", "failed")
        
        if status == "passed":
            print("🔀 [Router] Schema validation passed → SQL Generator")
            return "sql_generator"
        else:
            print("🔀 [Router] Schema validation failed → Error Diagnosis")
            state["error"] = validation.get("message", "Schema validation failed")
            return "error_diagnosis"


def error_recovery_router(state: DataBridgeState) -> Literal["sql_generator", "query_sense", "query_formatter", "error_handler"]:
    """
    Route based on error diagnosis to retry from appropriate step.
    
    Returns:
        Step name to retry from, or "error_handler" if max retries reached
    """
    diagnosis = state.get("error_diagnosis", {})
    retry_from_step = diagnosis.get("retry_from_step", "error_handler")
    error_step = state.get("error_step", "unknown")
    
    # Track retry count for this specific step
    step_retry_counts = state.get("step_retry_counts", {})
    current_retry_count = step_retry_counts.get(error_step, 0)
    max_step_retries = 2
    
    # Increment retry count for this step
    step_retry_counts[error_step] = current_retry_count + 1
    state["step_retry_counts"] = step_retry_counts
    
    # Increment overall recovery attempt
    state["recovery_attempt"] = state.get("recovery_attempt", 0) + 1
    
    # Check if we've exceeded retries for this step
    if current_retry_count >= max_step_retries:
        print(f"🔀 [RecoveryRouter] Max retries ({max_step_retries}) reached for {error_step} → Error Handler")
        return "error_handler"
    
    # Check if diagnosis suggests giving up
    if retry_from_step == "error_handler":
        print(f"🔀 [RecoveryRouter] Diagnosis suggests no recovery possible → Error Handler")
        return "error_handler"
    
    print(f"🔀 [RecoveryRouter] Retry attempt {current_retry_count + 1}/{max_step_retries} → {retry_from_step}")
    return retry_from_step


def format_router(state: DataBridgeState) -> Literal["insight_generator", "response_builder", "error_diagnosis", "error_handler"]:
    """
    Route based on query results.
    
    Returns:
        "error_diagnosis" if error needs diagnosis
        "error_handler" if execution error
        "response_builder" if KPI format or small data (including 0 rows)
        "insight_generator" if table/chart format (larger data)
    """
    row_count = state.get("row_count", 0)
    format_type = state.get("format", "unknown")
    
    if format_type == "error":
        error_msg = state.get("message", "Query execution failed")
        print(f"🔀 [Router] Query execution error → Error Diagnosis")
        state["error"] = error_msg
        return "error_diagnosis"
    elif row_count == 0:
        # 0 rows is a valid result, not an error
        print(f"🔀 [Router] Query returned 0 rows (valid result) → Response Builder")
        # Set a friendly message
        state["message"] = "Query executed successfully but returned no results. The data may not exist or filters are too restrictive."
        return "response_builder"
    elif row_count < 4 or format_type == "kpi":
        print(f"🔀 [Router] Small result ({row_count} rows) → Insight Generator")
        return "insight_generator"
    else:
        print(f"🔀 [Router] Large result ({row_count} rows) → Insight Generator")
        return "insight_generator"
