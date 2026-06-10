"""
Agent Nodes for LangGraph Workflow
Each node is a function that takes state and returns updated state
"""
from typing import Dict, Any
from agent_state import DataBridgeState
from agent_tools import (
    simplify_query_tool,
    analyze_query_intent_tool,
    validate_schema_references_tool,
    generate_sql_tool,
    validate_sql_syntax_tool,
    execute_query_tool,
    generate_insights_tool,
    generate_chart_configs_tool
)


def simplifier_agent(state: DataBridgeState) -> DataBridgeState:
    """Simplify user query"""
    print(f"\n🤖 [Agent] SimplifierAgent starting...")
    
    simplified = simplify_query_tool.invoke({"user_query": state["user_query"]})
    
    state["simplified_query"] = simplified
    state["current_step"] = "simplifier"
    print(f"✅ [Agent] SimplifierAgent completed\n")
    return state


def query_sense_agent(state: DataBridgeState) -> DataBridgeState:
    """Analyze query intent"""
    print(f"\n🤖 [Agent] QuerySenseAgent starting...")
    
    analysis = analyze_query_intent_tool.invoke({"simplified_query": state["simplified_query"]})
    
    state["query_sense_output"] = analysis
    state["current_step"] = "query_sense"
    print(f"✅ [Agent] QuerySenseAgent completed\n")
    return state


def validator_agent(state: DataBridgeState) -> DataBridgeState:
    """Validate schema references"""
    print(f"\n🤖 [Agent] ValidatorAgent starting...")
    
    validation = validate_schema_references_tool.invoke({"query_sense_output": state["query_sense_output"]})
    
    state["validation_result"] = validation
    state["current_step"] = "validator"
    print(f"✅ [Agent] ValidatorAgent completed\n")
    return state


def sql_generator_agent(state: DataBridgeState) -> DataBridgeState:
    """Generate SQL query"""
    print(f"\n🤖 [Agent] SQLGeneratorAgent starting...")
    
    result = generate_sql_tool.invoke({
        "user_query": state["user_query"],
        "query_sense_output": state["query_sense_output"],
        "simplified_query": state["simplified_query"]
    })
    state["generated_sql"] = result.get("generated_sql") 
    
    state["current_step"] = "sql_generator"
    print(f"✅ [Agent] SQLGeneratorAgent completed\n")
    return state

    #state["generated_sql"] = sql
    #state["current_step"] = "sql_generator"
    #print(f"✅ [Agent] SQLGeneratorAgent completed\n")
    #return state

def sql_validator_agent(state: DataBridgeState) -> DataBridgeState:
    """Validate generated SQL and clean markdown artifacts"""
    print(f"\n🤖 [Agent] SQLValidatorAgent starting...")
    
    # 1. Get the SQL from state
    sql_text = state.get("generated_sql", "")
    
    # 2. CLEANING: Strip out markdown formatting and backticks
    if isinstance(sql_text, str):
        # Remove markdown blocks and extra whitespace
        sql_text = sql_text.replace("```sql", "").replace("```", "").replace(";", "").strip()
        # Save the clean string back to state (adding a single semicolon for safety)
        state["generated_sql"] = sql_text + ";"
    
    # 3. Pass the CLEANED text to the validation tool
    validation = validate_sql_syntax_tool.invoke({"generated_sql": state["generated_sql"]})
    
    state["sql_validation"] = validation
    state["current_step"] = "sql_validator"
    
    # Increment retry count if validation failed
    if validation.get("status") != "passed":
        state["retry_count"] = state.get("retry_count", 0) + 1
    
    print(f"✅ [Agent] SQLValidatorAgent completed\n")
    return state

#def sql_validator_agent(state: DataBridgeState) -> DataBridgeState:
  #  """Validate generated SQL"""
   # print(f"\n🤖 [Agent] SQLValidatorAgent starting...")
    
   # validation = validate_sql_syntax_tool.invoke({"generated_sql": state["generated_sql"]})
    
   # state["sql_validation"] = validation
    #state["current_step"] = "sql_validator"
    
    # Increment retry count if validation failed
   # if validation.get("status") != "passed":
    #    state["retry_count"] = state.get("retry_count", 0) + 1
    
    #print(f"✅ [Agent] SQLValidatorAgent completed\n")
    #return state


def query_executor_agent(state: DataBridgeState) -> DataBridgeState:
    """Execute SQL query"""
    print(f"\n🤖 [Agent] QueryExecutorAgent starting...")
    
    result = execute_query_tool.invoke({
        "generated_sql": state["generated_sql"],
        "user_query": state["user_query"]
    })
    
    state["query_results"] = result
    state["row_count"] = result.get("row_count", 0)
    state["columns"] = result.get("columns", [])
    state["data"] = result.get("data", [])
    state["format"] = result.get("format", "unknown")
    state["case"] = result.get("case")
    state["message"] = result.get("message", "")
    state["current_step"] = "query_executor"
    
    print(f"✅ [Agent] QueryExecutorAgent completed\n")
    return state


def insight_generator_agent(state: DataBridgeState) -> DataBridgeState:
    """Generate insights from data"""
    print(f"\n🤖 [Agent] InsightGeneratorAgent starting...")
    
    insights_data = generate_insights_tool.invoke({
        "data": state["data"],
        "columns": state["columns"],
        "user_query": state["user_query"]
    })
    
    state["insights"] = insights_data.get("insights", [])
    state["visualizations"] = insights_data.get("visualizations", [])
    state["current_step"] = "insight_generator"
    
    print(f"✅ [Agent] InsightGeneratorAgent completed\n")
    return state


def visualizer_agent(state: DataBridgeState) -> DataBridgeState:
    """Generate chart configurations"""
    print(f"\n🤖 [Agent] VisualizerAgent starting...")
    
    chart_configs = generate_chart_configs_tool.invoke({
        "data": state["data"],
        "columns": state["columns"],
        "user_query": state["user_query"]
    })
    
    state["chart_configs"] = chart_configs
    state["current_step"] = "visualizer"
    
    print(f"✅ [Agent] VisualizerAgent completed\n")
    return state


def response_builder_agent(state: DataBridgeState) -> DataBridgeState:
    """Build final response"""
    print(f"\n🤖 [Agent] ResponseBuilderAgent starting...")
    
    response = {
        "query": state["user_query"],
        "simplified_query": state.get("simplified_query"),
        "qs_output": state.get("query_sense_output"),
        "validation": state.get("sql_validation"),
        "sql": state.get("generated_sql"),
        "format": state.get("format", "unknown"),
        "case": state.get("case"),
        "message": state.get("message", ""),
        "columns": state.get("columns", []),
        "row_count": state.get("row_count", 0),
        "data": state.get("data", []),
        "insights": state.get("insights", []),
        "visualizations": state.get("visualizations", []),
        "chart_configs": state.get("chart_configs", {"bar": {}, "line": {}, "pie": {}, "recommended": "bar"})
    }
    
    state["response"] = response
    state["current_step"] = "response_builder"
    
    print(f"✅ [Agent] ResponseBuilderAgent completed\n")
    return state


def error_handler_agent(state: DataBridgeState) -> DataBridgeState:
    """Handle errors and build error response"""
    print(f"\n🤖 [Agent] ErrorHandlerAgent starting...")
    
    error_msg = state.get("error", "Unknown error occurred")
    current_step = state.get("current_step", "unknown")
    
    response = {
        "query": state["user_query"],
        "format": "error",
        "message": f"❌ Error at {current_step}: {error_msg}",
        "error": error_msg,
        "current_step": current_step
    }
    
    state["response"] = response
    state["current_step"] = "error_handler"
    
    print(f"✅ [Agent] ErrorHandlerAgent completed\n")
    return state
