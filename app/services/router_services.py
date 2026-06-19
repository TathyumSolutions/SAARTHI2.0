import json
import os
from pydantic import BaseModel, Field
from typing import List, Literal
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from .databridge_services.langgraph_agent import run_data_bridge_agent
from app.services.stream_manager import stream_manager
from app.services.llm_service import answer_from_docs

# 1. Import your dynamic API service workflows
from app.services.api_services import fetch_and_translate_tools, ask_dynamic_model_with_tools

# 1. THE PYDANTIC SCHEMA (Keep this lightweight for LangChain structured outputs)
class RouterDecisionSchema(BaseModel):
    selected_tracks: List[Literal["DB", "FILES", "API"]] = Field(
        description="Ordered sequence of data source track keys required to fulfill the user's intent."
    )

# 2. THE SERVICE WORKER CLASS (This is what you instantiate safely at the module level)
class RouterService:
    def __init__(self):
        # You can add initialization configs here if needed later
        pass

    def get_smart_response(self, user_query, model_name="gpt-4o-mini", session_id=1, custom_key=''):
        """
        Enhanced Orchestration Router utilizing Strict Structured Output and 
        Dynamic Postgres Tool Description Injection.
        """
        try:
            print("\n" + "=" * 60)
            print(f"🧠 SMART ROUTER PROCESSING QUERY: {user_query}")
            session_id = str(session_id)

            # ----------------------------------------------------
            # STEP 0: LOAD CONFIG & INJECT LIVE POSTGRES DESCRIPTIONS
            # ----------------------------------------------------
            # Absolute path resolution guarantees Docker finds the file smoothly
            current_dir = os.path.dirname(os.path.abspath(__file__))
            json_path = os.path.join(current_dir, "router_metamind.json")
            with open(json_path, "r") as f:
                router_config = json.load(f)

            #current_dir = os.path.dirname(os.path.abspath(__file__))  # points to app/services
            #project_root = os.path.dirname(os.path.dirname(current_dir))  # points to /app (container root)
            #json_path = os.path.join(project_root, "router_metamind.json")

            #with open(json_path, "r") as f:
            #    router_config = json.load(f)
                
            # Fetch active tools
            active_db_tools = fetch_and_translate_tools()
            
            # Build context list string
            live_tools_summary = ""
            for tool in active_db_tools:
                func_data = tool.get("function", {})
                live_tools_summary += f"\n- Tool: '{func_data.get('name')}' -> Dynamic Capability: {func_data.get('description')}"

            routing_blueprint = json.dumps(router_config["routing_menu"], indent=2)

            system_prompt = f"""
You are the enterprise orchestration router layer. Your job is: "Step 0: Identify right data source".
Analyze the user's query carefully and decide which data source(s) are required to satisfy the intent.

AVAILABLE ROUTING MENU CONFIGURATION:
{routing_blueprint}

LIVE REGISTERED TOOLS AVAILABLE FOR THE 'API' TRACK:
{live_tools_summary if live_tools_summary else "No active external tools registered currently."}

CRITICAL MATCHING INSTRUCTIONS:
If the user's request matches any description listed in the dynamic 'LIVE REGISTERED TOOLS AVAILABLE' block above, you MUST choose the "API" track.
"""

            # Securely instantiate OpenAI Chat Client
            openai_api_key = custom_key if custom_key else os.getenv("OPENAI_API_KEY")
            base_llm = ChatOpenAI(
                model="gpt-4o-mini", 
                temperature=0.0, 
                openai_api_key=openai_api_key
            )
            
            # CRITICAL FIX: Pass the dedicated Data Schema to LangChain
            structured_llm = base_llm.with_structured_output(RouterDecisionSchema)
            
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_query)
            ]
            
            # LangChain yields an instance of RouterDecisionSchema
            decision = structured_llm.invoke(messages)
            required_sources = decision.selected_tracks
            print(f"🧠 Router Step 0 Decision: {required_sources}")

            # ----------------------------------------------------
            # CONDITIONAL TRACK ROUTING 
            # ----------------------------------------------------
            accumulated_context = f"Initial Prompt Context: {user_query}\n"
            master_steps = []
            full_result = None  

            for source in required_sources:
                print(f"🧭 Route Triggered -> Executing Track: {source}")

                if source == "FILES":
                    rag_res = answer_from_docs(user_query, model_name=model_name, session_id=session_id, custom_key=custom_key)
                    master_steps.extend(rag_res.get("steps", []))
                    
                    if len(required_sources) == 1:
                        return {
                            "answer": rag_res.get("answer"),
                            "sql": None, "table": [], "chart": {}, "insights": [], "steps": master_steps
                        }
                    accumulated_context += f"\n[Context from Uploaded Files]: {rag_res.get('answer')}"

                elif source == "DB":
                    sql_query_context = f"{user_query}. Context insights: {accumulated_context}" if len(required_sources) > 1 else user_query
                    full_result = run_data_bridge_agent(sql_query_context, session_id=session_id, model_name=model_name, custom_key=custom_key)
                    
                    if len(required_sources) == 1:
                        return full_result["chat_ui"]
                    
                    accumulated_context += f"\n[Context from SQL Records]: {full_result['chat_ui'].get('answer')}"
                    master_steps.append("Successfully executed SQL Agent table records retrieval pass.")

                elif source == "API":
                    docker_ollama_config = {"url": "http://ollama:11434/api/chat", "temperature": 0}
                    
                    final_api_payload = ask_dynamic_model_with_tools(
                        user_message=accumulated_context, 
                        llm_tools_list=active_db_tools,
                        model_name=model_name,
                        session_id=session_id,
                        custom_key=custom_key,
                        ollama_config=docker_ollama_config,
                        display_query=user_query
                    )
                    
                    api_answer = final_api_payload.get("answer", str(final_api_payload)) if isinstance(final_api_payload, dict) else str(final_api_payload)
                    master_steps.extend(final_api_payload.get("steps", ["Successfully executed Dynamic API Tools execution pass."]))

                    if len(required_sources) == 1:
                        return {
                            "answer": api_answer,
                            "sql": None, "table": [], "chart": {}, "insights": [], "steps": master_steps
                        }
                    accumulated_context += f"\n[Context from API Integrations]: {api_answer}"

            # ----------------------------------------------------
            # FINAL MULTI-SOURCE RETURN MAPPING
            # ----------------------------------------------------
            if len(required_sources) > 1:
                return {
                    "answer": accumulated_context.replace("Initial Prompt Context:", "").strip(),
                    "sql": full_result["chat_ui"].get("sql") if ("DB" in required_sources and full_result) else None,
                    "table": full_result["chat_ui"].get("table", []) if ("DB" in required_sources and full_result) else [],
                    "chart": full_result["chat_ui"].get("chart", {}) if ("DB" in required_sources and full_result) else {},
                    "insights": full_result["chat_ui"].get("insights", []) if ("DB" in required_sources and full_result) else [],
                    "steps": master_steps
                }

        except Exception as e:
            import traceback
            print(f"❌ [CRITICAL PIPELINE FAILURE]: {str(e)}")
            traceback.print_exc()
            return {
                "answer": "The system encountered an error routing your request.",
                "sql": None, "table": [], "chart": {}, "insights": [], "steps": [f"Failed at master router step: {str(e)}"]
            }