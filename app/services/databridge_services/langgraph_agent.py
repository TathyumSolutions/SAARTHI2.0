"""
LangGraph Orchestrator - Connects all agents through StateGraph with Error Recovery
"""
from langgraph.graph import StateGraph, END
from .agent_state import DataBridgeState
from .agent_routers import validation_router, error_recovery_router, format_router
from app.services.stream_manager import stream_manager
import time
from app.services.model_selection_service import get_model_for_step

# Import all agents from the agents package
from .agents import (
    QuerySimplifierAgent,
    QuerySenseAgent,
    QueryValidatorAgent,
    SQLGeneratorAgent,
    QueryFormatterAgent,
    DataInsightGeneratorAgent,
    DataVisualizerAgent,
    ErrorDiagnosisAgent
)


# ===== Configuration =====
# Schema is no longer a static global file - each request builds it from
# the querying user's own router_configs row (see _build_schema_for_user
# below), matching the per-user/per-connection model used everywhere else.
EMPTY_SCHEMA = {"tables": {}}

LLM_BACKEND = {
    "type": "ollama",
    #"url": "http://ollama:11434/api/generate",
    "url": "http://ollama:11434/api/generate",
    "model": "llama3",
    "max_tokens": 1024,
    "temperature": 0.0,
    "timeout": 600,
    
}


# ===== Initialize Agents =====
# query_simplifier, query_sense, and query_validator are schema-dependent -
# a fresh instance is built per request (see run_data_bridge_agent, which
# stashes them under state["_agents"]) using the querying user's own
# introspected schema, instead of a single shared instance baked with one
# global schema at import time. Everything below is schema-independent and
# safe to share as a module-level singleton across requests.
sql_generator = SQLGeneratorAgent(llm_backend=LLM_BACKEND)

query_formatter = QueryFormatterAgent()

data_insight_generator = DataInsightGeneratorAgent()

data_visualizer = DataVisualizerAgent(
    llm_url=LLM_BACKEND["url"],
    model=LLM_BACKEND["model"],
    top_n=20
)

error_diagnosis = ErrorDiagnosisAgent()


# ===== Agent Node Functions =====
def simplifier_node(state: DataBridgeState) -> DataBridgeState:
    """QuerySimplifierAgent node"""
    session_id = state.get("session_id", 1)

    stream_manager.push_step(
        session_id,
        {"event": "start", "title": "Query Simplifier Agent", "description": "Processing...", "is_sql": True},
        is_sql=True
    )
    requested_main_model = state.get("requested_model_name") or state.get("model_name")
    user_id = state.get("user_id", 1)
    step_model = get_model_for_step("query_simplifier", requested_main_model=requested_main_model, user_id=user_id)
    query_simplifier = state["_agents"]["query_simplifier"]
    if step_model:
        state["model_name"] = step_model
        query_simplifier.model_name = step_model
    print(f"[ModelSelection] query_simplifier -> {step_model}")
    return query_simplifier.execute(state)
    



def query_sense_node(state: DataBridgeState) -> DataBridgeState:
    """QuerySenseAgent node"""
    session_id = state.get("session_id", 1)
    stream_manager.push_step(
        session_id,
        {"event": "start", "title": "Query Sense Agent", "description": "Processing...", "is_sql": True},
        is_sql=True
    )
    requested_main_model = state.get("requested_model_name") or state.get("model_name")
    user_id = state.get("user_id", 1)
    step_model = get_model_for_step("query_sense", requested_main_model=requested_main_model, user_id=user_id)
    query_sense = state["_agents"]["query_sense"]
    if step_model:
        state["model_name"] = step_model
        query_sense.ollama_model = step_model
    print(f"[ModelSelection] query_sense -> {step_model}")
    return query_sense.execute(state)
  


def validator_node(state: DataBridgeState) -> DataBridgeState:
    """QueryValidatorAgent node"""
    session_id = state.get("session_id", 1)
    stream_manager.push_step(
        session_id,
        {"event": "start", "title": "Query Validator Agent", "description": "Processing...", "is_sql": True},
        is_sql=True
    )
    requested_main_model = state.get("requested_model_name") or state.get("model_name")
    user_id = state.get("user_id", 1)
    step_model = get_model_for_step("query_validator", requested_main_model=requested_main_model, user_id=user_id)
    if step_model:
        state["model_name"] = step_model
    print(f"[ModelSelection] query_validator -> {step_model}")
    return state["_agents"]["query_validator"].execute(state)


def sql_generator_node(state: DataBridgeState) -> DataBridgeState:
    """SQLGeneratorAgent node"""
    session_id = state.get("session_id", 1)
    # This triggers the moment your terminal executes the generator block, before Ollama runs!
    stream_manager.push_step(
        session_id,
        {"event": "start", "title": "SQL Generator Agent", "description": "Processing...", "is_sql": True},
        is_sql=True
    )
    requested_main_model = state.get("requested_model_name") or state.get("model_name")
    user_id = state.get("user_id", 1)
    step_model = get_model_for_step("sql_generator", requested_main_model=requested_main_model, user_id=user_id)
    if step_model:
        state["model_name"] = step_model
        sql_generator.llm_backend["model"] = step_model
    print(f"[ModelSelection] sql_generator -> {step_model}")
    return sql_generator.execute(state)
   


def query_formatter_node(state: DataBridgeState) -> DataBridgeState:
    """QueryFormatterAgent node"""
    session_id = state.get("session_id", 1)
    stream_manager.push_step(
        session_id,
        {"event": "start", "title": "Query Formatter Agent", "description": "Processing...", "is_sql": True},
        is_sql=True
    )
    requested_main_model = state.get("requested_model_name") or state.get("model_name")
    user_id = state.get("user_id", 1)
    step_model = get_model_for_step("query_formatter", requested_main_model=requested_main_model, user_id=user_id)
    if step_model:
        state["model_name"] = step_model
    print(f"[ModelSelection] query_formatter -> {step_model}")
    return query_formatter.execute(state)


def insight_generator_node(state: DataBridgeState) -> DataBridgeState:
    """DataInsightGeneratorAgent node"""
    session_id = state.get("session_id", 1)
    stream_manager.push_step(
        session_id,
        {"event": "start", "title": "Data Insight Agent", "description": "Processing...", "is_sql": True},
        is_sql=True
    )

    requested_main_model = state.get("requested_model_name") or state.get("model_name")
    user_id = state.get("user_id", 1)
    step_model = get_model_for_step("data_insight_generator", requested_main_model=requested_main_model, user_id=user_id)
    if step_model:
        state["model_name"] = step_model
        data_insight_generator.model = step_model
    print(f"[ModelSelection] data_insight_generator -> {step_model}")
    return data_insight_generator.execute(state)


def visualizer_node(state: DataBridgeState) -> DataBridgeState:
    """DataVisualizerAgent node"""
    session_id = state.get("session_id", 1)
    stream_manager.push_step(
        session_id,
        {"event": "start", "title": "Data Visualizer Agent", "description": "Processing...", "is_sql": True},
        is_sql=True
    )
    requested_main_model = state.get("requested_model_name") or state.get("model_name")
    user_id = state.get("user_id", 1)
    step_model = get_model_for_step("data_visualizer", requested_main_model=requested_main_model, user_id=user_id)
    if step_model:
        state["model_name"] = step_model
        data_visualizer.model = step_model
    print(f"[ModelSelection] data_visualizer -> {step_model}")
    return data_visualizer.execute(state)


def error_diagnosis_node(state: DataBridgeState) -> DataBridgeState:
    """ErrorDiagnosisAgent node"""
    session_id = state.get("session_id", 1)
    stream_manager.push_step(
        session_id,
        {"event": "start", "title": "Error Diagnosis Agent", "description": "Processing...", "is_sql": True},
        is_sql=True
    )
    requested_main_model = state.get("requested_model_name") or state.get("model_name")
    user_id = state.get("user_id", 1)
    step_model = get_model_for_step("error_diagnosis", requested_main_model=requested_main_model, user_id=user_id)
    if step_model:
        state["model_name"] = step_model
    print(f"[ModelSelection] error_diagnosis -> {step_model}")
    return error_diagnosis.execute(state)


def response_builder_node(state: DataBridgeState) -> DataBridgeState:
    """Build final response"""
    print(f"\n🤖 [ResponseBuilder] Building final response...")
    session_id = state.get("session_id", 1)
    stream_manager.push_step(
        session_id,
        {"event": "start", "title": "Response Builder Agent", "description": "Processing...", "is_sql": True},
        is_sql=True
    )

    qs_output = state.get("query_sense_output", {})
    execution_steps = qs_output.get("steps", [])
    
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
        "chart_configs": state.get("chart_configs", {"bar": {}, "line": {}, "pie": {}, "recommended": "bar"}),
        "steps": execution_steps
    }
    
    state["response"] = response
    state["current_step"] = "response_builder"
    
    print(f"✅ [ResponseBuilder] Response built successfully\n")
    return state


def error_handler_node(state: DataBridgeState) -> DataBridgeState:
    """Handle errors"""
    print(f"\n🤖 [ErrorHandler] Handling error...")
    
    error_msg = state.get("error", "Unknown error occurred")
    current_step = state.get("current_step", "unknown")
    recovery_attempts = state.get("recovery_attempt", 0)
    
    response = {
        "query": state["user_query"],
        "format": "error",
        "message": f"❌ Error at {current_step}: {error_msg}",
        "error": error_msg,
        "current_step": current_step,
        "recovery_attempts": recovery_attempts
    }
    
    state["response"] = response
    state["current_step"] = "error_handler"
    
    print(f"✅ [ErrorHandler] Error handled (after {recovery_attempts} recovery attempts)\n")
    return state


# ===== Build StateGraph =====
def create_data_bridge_graph():
    """Create and compile the LangGraph StateGraph with Error Recovery"""
    workflow = StateGraph(DataBridgeState)
    
    # Add nodes
    workflow.add_node("simplifier", simplifier_node)
    workflow.add_node("query_sense", query_sense_node)
    workflow.add_node("validator", validator_node)
    workflow.add_node("sql_generator", sql_generator_node)
    workflow.add_node("query_formatter", query_formatter_node)
    workflow.add_node("insight_generator", insight_generator_node)
    workflow.add_node("visualizer", visualizer_node)
    workflow.add_node("error_diagnosis", error_diagnosis_node)
    workflow.add_node("response_builder", response_builder_node)
    workflow.add_node("error_handler", error_handler_node)
    
    # Set entry point
    workflow.set_entry_point("simplifier")
    
    # Add edges
    workflow.add_edge("simplifier", "query_sense")
    workflow.add_edge("query_sense", "validator")
    
    # Conditional: validator → sql_generator, query_formatter, error_diagnosis, or error_handler
    workflow.add_conditional_edges(
        "validator",
        validation_router,
        {
            "sql_generator": "sql_generator",
            "query_formatter": "query_formatter",
            "error_diagnosis": "error_diagnosis",
            "error_handler": "error_handler"
        }
    )
    
    # sql_generator → validator (for SQL validation)
    workflow.add_edge("sql_generator", "validator")
    
    # Conditional: query_formatter → insight_generator, response_builder, error_diagnosis, or error_handler
    workflow.add_conditional_edges(
        "query_formatter",
        format_router,
        {
            "insight_generator": "insight_generator",
            "response_builder": "response_builder",
            "error_diagnosis": "error_diagnosis",
            "error_handler": "error_handler"
        }
    )
    
    # Conditional: error_diagnosis → retry from appropriate step or error_handler
    workflow.add_conditional_edges(
        "error_diagnosis",
        error_recovery_router,
        {
            "sql_generator": "sql_generator",
            "query_sense": "query_sense",
            "query_formatter": "query_formatter",
            "error_handler": "error_handler"
        }
    )
    
    # insight_generator → visualizer
    workflow.add_edge("insight_generator", "visualizer")
    
    # visualizer → response_builder
    workflow.add_edge("visualizer", "response_builder")
    
    # response_builder → END
    workflow.add_edge("response_builder", END)
    
    # error_handler → END
    workflow.add_edge("error_handler", END)
    
    # Compile
    app = workflow.compile()
    print("✅ LangGraph StateGraph compiled with Error Recovery!")
    return app


# Create compiled graph
langgraph_app = create_data_bridge_graph()


def _build_schema_for_user(user_id: int) -> dict:
    """
    This user's own introspected DB schema (from their router_configs row,
    populated by generate_router_config()/introspect_databridge_db() - the
    same data the "Process" button on a database connection builds),
    converted into the shape the SQL agents below expect. Falls back to an
    empty schema (never raises) if this user has no router config yet, or
    it has no DB datasource - same "degrade gracefully" behavior as the
    rest of the router.
    """
    try:
        from app.models.router_config import RouterConfig
        from app.services.automated_metamind import to_sql_agent_schema

        row = RouterConfig.query.filter_by(user_id=user_id).first()
        if not row or not row.config:
            return dict(EMPTY_SCHEMA)
        db_tables = row.config.get("routing_menu", {}).get("datasources", {}).get("DB", {}).get("tables", {})
        return to_sql_agent_schema(db_tables)
    except Exception as e:
        print(f"⚠️ [SCHEMA] Could not load schema for user {user_id}: {e}")
        return dict(EMPTY_SCHEMA)


def run_data_bridge_agent(user_query: str, max_retries: int = 2,session_id: int = 1,model_name: str = None,custom_key: str = "",system_instructions: str = "", user_id: int = 1) -> dict:
    """Run the Data Bridge agent with error recovery"""
    print(f"\n{'='*80}")
    print(f"🚀 Starting LangGraph Data Bridge Agent with Error Recovery")
    print(f"{'='*80}\n")
    print("RUN_DATA_BRIDGE MODEL =", model_name)
    if model_name:
        LLM_BACKEND["model"] = model_name

    # Fresh, request-scoped instances built from this user's own schema -
    # not shared module-level singletons, so concurrent requests from
    # different users never see each other's schema.
    schema = _build_schema_for_user(user_id)
    agents = {
        "query_simplifier": QuerySimplifierAgent(schema=schema, model_name=LLM_BACKEND["model"], url=LLM_BACKEND["url"]),
        "query_sense": QuerySenseAgent(schema=schema, ollama_model=LLM_BACKEND["model"], ollama_url=LLM_BACKEND["url"]),
        "query_validator": QueryValidatorAgent(schema=schema),
    }

    stream_manager.push_step(
        session_id, 
        {
            "event": "start",
            "title": "Pipeline Entry",
            "description": f"User Request Received - Analyzing raw input parameter...",
            "is_sql": True
        }, 
        is_sql=True
    )
    time.sleep(0.2)
    stream_manager.push_step(
        session_id, 
        {
            "event": "complete",
            "title": "Pipeline Entry",
            "description": f"Input parameter successfully verified: '{user_query}'",
            "is_sql": True
        }, 
        is_sql=True
    )

    #initial_log = f"User Request Recieved - Analyzing raw input parameter: '{user_query}'"
    #stream_manager.push_step(session_id, initial_log, is_sql=False)

    initial_state = {
        "user_query": user_query,
        "model_name": model_name,
        "requested_model_name": model_name,
        "user_id": user_id,
        "custom_key": custom_key,
        "system_instructions": system_instructions,
        "_agents": agents,
        "steps": [],
        "simplified_query": None,
        "query_sense_output": None,
        "validation_result": None,
        "generated_sql": None,
        "sql_validation": None,
        "query_results": None,
        "row_count": 0,
        "columns": None,
        "data": None,
        "insights": None,
        "visualizations": None,
        "chart_configs": None,
        "current_step": "start",
        "error": None,
        "retry_count": 0,
        "max_retries": max_retries,
        "error_step": None,
        "error_diagnosis": None,
        "error_feedback": None,
        "step_retry_counts": {},
        "recovery_attempt": 0,
        "response": None,
        "format": None,
        "case": None,
        "message": None
    }
    
    streamed_steps = set()
    # Create a base dictionary to collect the live updates from the stream
    final_state = dict(initial_state)
    has_sql_executed = False
    #last_node_name = None

    # We change nothing inside your agents; we just watch the graph transition nodes live
    for chunk in langgraph_app.stream(initial_state):
        for node_name, state_update in chunk.items():
            #if last_node_name and last_node_name != node_name:
            #    stream_manager.push_step(session_id, "DONE", is_sql=is_current_step_sql)
            #    time.sleep(0.05)

            final_state.update(state_update)
            
            chk_key = node_name.lower()

            is_current_step_sql = True
            
            # 1. DYNAMIC IS_SQL DETECTOR
            #is_current_step_sql = "generator" in chk_key or "validator" in chk_key or "formatter" in chk_key
            #if is_current_step_sql:
            has_sql_executed = True
            
            # 2. DYNAMIC NODE ROUTER (Keep your exact same matching blocks here)
            if "simplifier" in chk_key:
                node_title = "Query Simplifier Agent"
                val = final_state.get("simplified_query")
                desc = f"Refined raw query intent: '{val}'" if val else "Optimizing execution parameters..."
                
            elif "sense" in chk_key:
                node_title = "Query Sense Agent"
                qs_data = final_state.get("query_sense_output") or {}
                tables = qs_data.get("tables")
                desc = f"Mapped database schema entities for tables: {tables}" if tables else "Identifying target database entities..."

    
            elif "validator" in chk_key:
                node_title = "Query Validator Agent"
                
                # Checks both state options so it never blindly prints "Processing"
                val_status = final_state.get("sql_validation") or final_state.get("validation_result") or "passed"
                
                desc = f"Cross-referenced data columns against active schema constraints. Status: {val_status}."     
                
                
            elif "generator" in chk_key and "insight" not in chk_key:
                node_title = "SQL Generator Agent"
                sql_val = final_state.get("generated_sql")
                desc = f"Generated structured query syntax: {sql_val}" if sql_val else "Compiling relational SQL query tokens..."
                
            elif "formatter" in chk_key:
                node_title = "Query Formatter Agent"
                rows = final_state.get("row_count", 0)
                desc = f"Sanitized layout keywords and executed query. Retrieved {rows} rows." if rows else "Sanitizing structural keywords and executing query..."
                
            elif "insight" in chk_key:
                node_title = "Data Insight Agent"
                insights_list = final_state.get("insights") or []
                count = len(insights_list)
                desc = f"Evaluated raw record structures and compiled {count} statistical trends." if count else "Analyzing dataset for key statistical trends..."
                
            elif "visualizer" in chk_key:
                node_title = "Data Visualizer Agent"
                chart_cfg = final_state.get("chart_configs") or {}
                recommended = chart_cfg.get("recommended")
                if recommended:
                    chart_name = f"{str(recommended).strip().title()} Chart"
                    desc = f"Assembled data matrix configurations for the target {chart_name}."
                else:
                    desc = "Assembling dashboard visualization matrices..."
                
            elif "builder" in chk_key or "response" in chk_key:
                node_title = "Response Builder Agent"
                desc = "Finalizing data delivery packets and rendering application layout interface."
                
            elif "diagnosis" in chk_key:
                node_title = "Error Diagnosis Agent"
                raw_err = final_state.get("error_message") or "An unexpected pipeline interruption occurred."
                desc = f"🚨 Pipeline Halt Detected. Analyzing solution for execution error: {raw_err}"
                
            else:
                node_title = f"{node_name.replace('_', ' ').title()} Agent"
                desc = "Synchronized transactional state pipeline updates."

            #last_node_name = node_name
            #step_key = f"{node_name}_started"
            run_id = len(streamed_steps)
            step_key = f"{node_name}_{run_id}_completed"
            #step_key = f"{node_name}_completed"

            # =========================================
            # STEP START EVENT
            # =========================================

            if step_key not in streamed_steps:
                stream_manager.push_step(
                    session_id,
                    {
                        "event": "complete",
                        "title": node_title,
                        "description": desc,
                        "is_sql": is_current_step_sql
                    },
                    is_sql=is_current_step_sql
                )
                streamed_steps.add(step_key)
                
                # Creates a clean pacing transition break on the frontend before the next node starts
                time.sleep(0.4)
            # Gives the UI time to register the new card framework
               

    # 1. Extract the clean result built by your ResponseBuilder node
    # This contains only the 'message', 'data', and 'chart_configs'
    time.sleep(0.15)  
    stream_manager.push_step(session_id, "DONE", is_sql=has_sql_executed)
    user_facing_response = final_state.get("response", {})

    print(f"\n{'='*80}")
    print(f"✅ LangGraph Data Bridge Agent Completed")
    print(f"   Recovery Attempts: {final_state.get('recovery_attempt', 0)}")
    print(f"{'='*80}\n")
    
    # 2. Return the split structure
    return {
        "chat_ui": {
            "answer": user_facing_response.get("message", "No analysis found."),
            "table": user_facing_response.get("data", []),
            "insights": user_facing_response.get("insights", []),
            "chart": user_facing_response.get("chart_configs", {}),
            "sql": final_state.get("generated_sql", "-- No SQL Generated --"),
            #"steps": final_state.get("steps", []),
            "steps": list(streamed_steps)
        },
        "cot_logs": final_state  # This is the "Everything" for your CoT section
    }
    
