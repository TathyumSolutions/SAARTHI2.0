# """
# LangGraph Tools - Converting existing agents into reusable tools
# """
# import json
# from typing import Dict, Any, List
# from langchain_core.tools import tool

# # Import existing components
# from query_simplifier import QuerySimplifier
# from query_sense import QuerySense
# from query_validator import QueryValidator
# from sql_generator import generate_sql_from_querysense
# from format_decider import FormatDecider
# from data_insight_generator import DataInsightGenerator
# from data_visualizer import DataVisualizerAgent


# # ===== Global Instances (initialized once) =====
# SCHEMA_PATH = "sap_schema_yash_comment-updated.json"
# with open(SCHEMA_PATH, "r") as f:
#     SCHEMA = json.load(f)

# LLM_BACKEND = {
#     "type": "ollama",
#     "url": "http://localhost:11434/api/generate",
#     # "model": "llama3:latest",
#     "model": "duckdb-nsql:7b",
#     "max_tokens": 1024,
#     "temperature": 0.0,
#     "timeout": 60
# }

# # Initialize agents
# simplifier = QuerySimplifier(
#     schema_path=SCHEMA_PATH,
#     model_name=LLM_BACKEND["model"],
#     url=LLM_BACKEND["url"]
# )
# query_sense = QuerySense(SCHEMA, ollama_model=LLM_BACKEND["model"])
# validator = QueryValidator(SCHEMA)
# format_decider = FormatDecider()
# insight_generator = DataInsightGenerator()
# visualizer = DataVisualizerAgent(
#     llm_url=LLM_BACKEND["url"],
#     model=LLM_BACKEND["model"],
#     top_n=20
# )


# # ===== Tool Definitions =====

# @tool
# def simplify_query_tool(user_query: str) -> str:
#     """
#     Simplify user query to extract core intent.
    
#     Args:
#         user_query: Raw user query string
        
#     Returns:
#         Simplified query string
#     """
#     print(f"🔧 [Tool] Simplifying query: {user_query[:50]}...")
#     simplified = simplifier.simplify(user_query)
#     print(f"✅ [Tool] Simplified to: {simplified}")
#     return simplified


# @tool
# def analyze_query_intent_tool(simplified_query: str) -> Dict[str, Any]:
#     """
#     Analyze query to extract tables, columns, filters, and aggregations.
    
#     Args:
#         simplified_query: Simplified query string
        
#     Returns:
#         Dictionary with query analysis (tables, columns, filters, etc.)
#     """
#     print(f"🔧 [Tool] Analyzing query intent: {simplified_query[:50]}...")
#     analysis = query_sense.analyze(simplified_query)
#     print(f"✅ [Tool] Found tables: {analysis.get('tables', [])}")
#     return analysis


# @tool
# def validate_schema_references_tool(query_sense_output: Dict[str, Any]) -> Dict[str, Any]:
#     """
#     Validate that detected tables and columns exist in the schema.
    
#     Args:
#         query_sense_output: Output from query sense analysis
        
#     Returns:
#         Validation result with status and message
#     """
#     print(f"🔧 [Tool] Validating schema references...")
#     validation = validator.validate(query_sense_output)
#     print(f"✅ [Tool] Validation status: {validation.get('status')}")
#     return validation


# @tool
# def generate_sql_tool(user_query: str, query_sense_output: Dict[str, Any], simplified_query: str) -> str:
#     """
#     Generate SQL query from query intent.
    
#     Args:
#         user_query: Original user query
#         query_sense_output: Query sense analysis
#         simplified_query: Simplified query
        
#     Returns:
#         Generated SQL string
#     """
#     print(f"🔧 [Tool] Generating SQL...")
#     sql = generate_sql_from_querysense(
#         user_query,
#         query_sense_output,
#         LLM_BACKEND,
#         simplified_query=simplified_query
#     )
#     print(f"✅ [Tool] Generated SQL: {sql[:100]}...")
#     return sql


# @tool
# def validate_sql_syntax_tool(generated_sql: str) -> Dict[str, Any]:
#     """
#     Validate SQL syntax and schema references.
    
#     Args:
#         generated_sql: SQL query to validate
        
#     Returns:
#         Validation result with status and message
#     """
#     print(f"🔧 [Tool] Validating SQL syntax...")
#     validation = validator.validate_generated_sql(generated_sql)
#     print(f"✅ [Tool] SQL validation status: {validation.get('status')}")
#     return validation


# @tool
# def execute_query_tool(generated_sql: str, user_query: str) -> Dict[str, Any]:
#     """
#     Execute SQL query on PostgreSQL database.
    
#     Args:
#         generated_sql: SQL query to execute
#         user_query: Original user query for context
        
#     Returns:
#         Query results with data, columns, row_count, etc.
#     """
#     print(f"🔧 [Tool] Executing SQL query...")
#     result = format_decider.execute_query(generated_sql, user_query)
#     print(f"✅ [Tool] Query executed: {result.get('row_count', 0)} rows")
#     return result


# @tool
# def generate_insights_tool(data: List[Dict[str, Any]], columns: List[str], user_query: str) -> Dict[str, Any]:
#     """
#     Generate insights from query results.
    
#     Args:
#         data: List of data records
#         columns: Column names
#         user_query: Original user query
        
#     Returns:
#         Dictionary with insights and visualization suggestions
#     """
#     print(f"🔧 [Tool] Generating insights for {len(data)} rows...")
#     insights = insight_generator.generate_insights(data, columns, user_query)
#     print(f"✅ [Tool] Generated {len(insights.get('insights', []))} insights")
#     return insights


# @tool
# def generate_chart_configs_tool(data: List[Dict[str, Any]], columns: List[str], user_query: str) -> Dict[str, Any]:
#     """
#     Generate multiple chart configurations (bar, line, pie).
    
#     Args:
#         data: List of data records
#         columns: Column names
#         user_query: Original user query
        
#     Returns:
#         Dictionary with bar, line, pie chart configs and recommended type
#     """
#     print(f"🔧 [Tool] Generating chart configs...")
#     chart_configs = visualizer.generate_multiple_chart_configs(data, columns, user_query)
#     print(f"✅ [Tool] Generated chart configs: {list(chart_configs.keys())}")
#     return chart_configs


# # ===== Tool List for LangGraph =====
# ALL_TOOLS = [
#     simplify_query_tool,
#     analyze_query_intent_tool,
#     validate_schema_references_tool,
#     generate_sql_tool,
#     validate_sql_syntax_tool,
#     execute_query_tool,
#     generate_insights_tool,
#     generate_chart_configs_tool
# ]



"""
LangGraph Tools - wrapping new agent classes as LangChain tools
"""

import json
from typing import Dict, Any, List
from langchain_core.tools import tool
import os

# Import new agents (same ones used in LangGraph)
from agents import (
    QuerySimplifierAgent,
    QuerySenseAgent,
    QueryValidatorAgent,
    SQLGeneratorAgent,
    QueryFormatterAgent,
    DataInsightGeneratorAgent,
    DataVisualizerAgent
)

# ===== Shared Schema + LLM Config =====
current_dir = os.path.dirname(os.path.abspath(__file__))
SCHEMA_PATH = os.path.join(current_dir, "sap_schema_with_sap_comments.json")
#SCHEMA_PATH = "sap_schema_yash_comment-updated.json"
with open(SCHEMA_PATH, "r") as f:
    SCHEMA = json.load(f)

LLM_BACKEND = {
    "type": "ollama",
    #"url": "http://localhost:11434/api/generate",
    "url": "http://ollama:11434/api/generate",
    "model": "duckdb-nsql:7b",
    "max_tokens": 1024,
    "temperature": 0.0,
    "timeout": 300
}

# ===== Instantiate Agents Once =====
simplifier = QuerySimplifierAgent(
    schema_path=SCHEMA_PATH,
    model_name=LLM_BACKEND["model"],
    url=LLM_BACKEND["url"]
)

query_sense = QuerySenseAgent(
    schema=SCHEMA,
    ollama_model=LLM_BACKEND["model"],
    ollama_url=LLM_BACKEND["url"]
)

validator = QueryValidatorAgent(schema=SCHEMA)

sql_generator = SQLGeneratorAgent(llm_backend=LLM_BACKEND)

formatter = QueryFormatterAgent()

insight_generator = DataInsightGeneratorAgent()

visualizer = DataVisualizerAgent(
    llm_url=LLM_BACKEND["url"],
    model=LLM_BACKEND["model"],
    top_n=20
)

# ================================================================================
# TOOL WRAPPERS (operate on simplified LangGraph-like dictionaries)
# ================================================================================

@tool
def simplify_query_tool(user_query: str) -> Dict[str, Any]:
    """Tool wrapper for QuerySimplifierAgent"""
    state = {"user_query": user_query}
    result = simplifier.execute(state)
    return {
        "simplified_query": result.get("simplified_query")
    }

@tool
def analyze_query_intent_tool(simplified_query: str) -> Dict[str, Any]:
    """Tool wrapper for QuerySenseAgent"""
    state = {"simplified_query": simplified_query}
    result = query_sense.execute(state)
    return result.get("query_sense_output", {})

@tool
def validate_schema_references_tool(query_sense_output: Dict[str, Any]) -> Dict[str, Any]:
    """Tool wrapper for QueryValidatorAgent"""
    state = {"query_sense_output": query_sense_output}
    result = validator.execute(state)
    return result.get("sql_validation", {})

@tool
def generate_sql_tool(user_query: str, query_sense_output: Dict[str, Any], simplified_query: str) -> Dict[str, Any]:
    """Tool wrapper for SQLGeneratorAgent"""
    state = {
        "user_query": user_query,
        "query_sense_output": query_sense_output,
        "simplified_query": simplified_query
    }
    result = sql_generator.execute(state)
    return {"generated_sql": result.get("generated_sql")}

@tool
def format_decider_tool(generated_sql: str) -> Dict[str, Any]:
    """Tool wrapper for QueryFormatterAgent"""
    state = {"generated_sql": generated_sql}
    return formatter.execute(state)

@tool
def generate_insights_tool(data: List[Dict[str, Any]], columns: List[str], user_query: str) -> Dict[str, Any]:
    """Tool wrapper for DataInsightGeneratorAgent"""
    state = {"data": data, "columns": columns, "user_query": user_query}
    return insight_generator.execute(state)

@tool
def generate_chart_configs_tool(data: List[Dict[str, Any]], columns: List[str], user_query: str) -> Dict[str, Any]:
    """Tool wrapper for DataVisualizerAgent"""
    state = {"data": data, "columns": columns, "user_query": user_query}
    return visualizer.execute(state)

# Collect all tools
ALL_TOOLS = [
    simplify_query_tool,
    analyze_query_intent_tool,
    validate_schema_references_tool,
    generate_sql_tool,
    format_decider_tool,
    generate_insights_tool,
    generate_chart_configs_tool,
]
