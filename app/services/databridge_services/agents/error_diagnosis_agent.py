"""
ErrorDiagnosisAgent - Analyzes errors and suggests fixes
"""
from typing import Dict, Any
import re


class ErrorDiagnosisAgent:
    """
    Agent responsible for diagnosing errors and suggesting fixes.
    Analyzes the error context and provides actionable feedback for retry.
    """
    
    def __init__(self):
        pass
    
    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the agent: diagnose error and suggest fix.
        
        Args:
            state: Current state dictionary with error information
            
        Returns:
            Updated state with error_diagnosis and error_feedback
        """
        print(f"\n🔍 [ErrorDiagnosisAgent] Analyzing error...")
        
        error_step = state.get("current_step", "unknown")
        error_msg = state.get("error", "Unknown error")

        
        
        # Debug logging
        print(f"🔍 [ErrorDiagnosisAgent] Error step: {error_step}")
        print(f"🔍 [ErrorDiagnosisAgent] Error message: {error_msg}")
        
        # Diagnose based on step and error message
        diagnosis = self.diagnose_error(error_step, error_msg, state)
        
        state["error_step"] = error_step
        state["error_diagnosis"] = diagnosis
        state["error_feedback"] = diagnosis.get("feedback", "")
        state["current_step"] = "error_diagnosis"

        issue = diagnosis.get('issue', 'Unknown Issue')
        retry_step = diagnosis.get('retry_from_step', 'start')

        # This tells the user exactly what went wrong and where the system is looping back to
        #state["steps"].append(
        #    f"Self-Correction: ERROR detected in {error_step}. Issue: {issue}. Attempting automated fix and retrying from: {retry_step}."
        #)
        if "steps" not in state or not isinstance(state["steps"], list):
            state["steps"] = []
            
        state["steps"].append(
            f"ErrorDiagnosisAgent - SQL Execution Error Detected in [{error_step}]. Issue: {issue}. Retrying from: {retry_step}."
        )


        query_sense_output = state.get("query_sense_output", {})
        query_sense_output["steps"] = state["steps"]
        state["query_sense_output"] = query_sense_output
        
        print(f"📋 [ErrorDiagnosisAgent] Diagnosis: {diagnosis.get('issue')}")
        print(f"💡 [ErrorDiagnosisAgent] Suggested fix: {diagnosis.get('fix')}")
        print(f"🔄 [ErrorDiagnosisAgent] Retry from: {diagnosis.get('retry_from_step')}")
        
        return state
    
    def diagnose_error(self, error_step: str, error_msg: str, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Diagnose the error and suggest a fix.
        
        Returns:
            Dictionary with issue, fix, retry_from_step, and feedback
        """
        error_msg_lower = error_msg.lower() if error_msg else ""
        
        # SQL Generation Errors
        if error_step == "sql_generator":
            if "empty response" in error_msg_lower or "no sql generated" in error_msg_lower:
                return {
                    "issue": "LLM failed to generate SQL",
                    "fix": "Retry with more explicit instructions",
                    "retry_from_step": "sql_generator",
                    "feedback": f"Previous attempt failed: {error_msg}. Please generate valid SQL based on the query intent. Be explicit and use proper PostgreSQL syntax."
                }
            else:
                return {
                    "issue": "SQL generation error",
                    "fix": "Retry SQL generation",
                    "retry_from_step": "sql_generator",
                    "feedback": f"Error occurred: {error_msg}. Please try again with correct syntax."
                }
        
        # SQL Validation Errors
        elif error_step == "query_validator" and "sql" in error_msg_lower:
            if "does not exist" in error_msg_lower or "not found" in error_msg_lower:
                return {
                    "issue": "Table or column not found in schema",
                    "fix": "Regenerate SQL with correct schema references",
                    "retry_from_step": "sql_generator",
                    "feedback": f"SQL validation failed: {error_msg}. Check the schema carefully and use only existing tables and columns."
                }
            elif "syntax" in error_msg_lower:
                return {
                    "issue": "SQL syntax error",
                    "fix": "Fix SQL syntax",
                    "retry_from_step": "sql_generator",
                    "feedback": f"Syntax error: {error_msg}. Please generate syntactically correct PostgreSQL query."
                }
            elif "group by" in error_msg_lower:
                return {
                    "issue": "GROUP BY clause error",
                    "fix": "Include all non-aggregated columns in GROUP BY",
                    "retry_from_step": "sql_generator",
                    "feedback": f"GROUP BY error: {error_msg}. All non-aggregated columns must be in GROUP BY clause."
                }
            else:
                return {
                    "issue": "SQL validation failed",
                    "fix": "Regenerate SQL",
                    "retry_from_step": "sql_generator",
                    "feedback": f"Validation failed: {error_msg}. Please fix the SQL query."
                }
        
        # Query Execution Errors
        elif error_step == "query_formatter":
            if "no results" in error_msg_lower or "returned no results" in error_msg_lower or "may need adjustment" in error_msg_lower:
                # Get the generated SQL to analyze
                generated_sql = state.get("generated_sql", "")
                return {
                    "issue": "Query returned no results",
                    "fix": "Adjust query to be less restrictive or check data availability",
                    "retry_from_step": "sql_generator",
                    "feedback": f"Query returned 0 rows. The SQL may be too restrictive or the data doesn't exist. Previous SQL: {generated_sql[:200]}... Consider: 1) Removing or relaxing WHERE clauses, 2) Checking if tables have data, 3) Verifying JOIN conditions are correct."
                }
            elif "does not exist" in error_msg_lower:
                return {
                    "issue": "Runtime error - table/column not found",
                    "fix": "Regenerate SQL with correct schema",
                    "retry_from_step": "sql_generator",
                    "feedback": f"Execution failed: {error_msg}. The table or column does not exist. Check schema and regenerate SQL."
                }
            elif "permission" in error_msg_lower or "denied" in error_msg_lower:
                return {
                    "issue": "Permission denied",
                    "fix": "Cannot fix - permission issue",
                    "retry_from_step": "error_handler",
                    "feedback": "Database permission error. Cannot proceed."
                }
            elif "timeout" in error_msg_lower:
                return {
                    "issue": "Query timeout",
                    "fix": "Simplify query or add limits",
                    "retry_from_step": "sql_generator",
                    "feedback": f"Query timed out: {error_msg}. Please generate a simpler query or add LIMIT clause."
                }
            else:
                return {
                    "issue": "Query execution error",
                    "fix": "Regenerate SQL",
                    "retry_from_step": "sql_generator",
                    "feedback": f"Execution error: {error_msg}. Please regenerate the SQL query."
                }
        
        # Schema Validation Errors
        elif error_step == "query_validator":
            return {
                "issue": "Schema validation failed",
                "fix": "Re-analyze query with correct schema",
                "retry_from_step": "query_sense",
                "feedback": f"Schema validation failed: {error_msg}. Please re-analyze the query and use only valid tables and columns from the schema."
            }
        
        # Query Sense Errors
        elif error_step == "query_sense":
            return {
                "issue": "Query analysis failed",
                "fix": "Retry query analysis",
                "retry_from_step": "query_sense",
                "feedback": f"Query analysis failed: {error_msg}. Please try again."
            }
        
        # Default
        else:
            return {
                "issue": f"Error at {error_step}",
                "fix": "Retry from failed step",
                "retry_from_step": error_step,
                "feedback": f"Error: {error_msg}. Please retry."
            }
