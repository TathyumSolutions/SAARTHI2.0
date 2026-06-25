import json
import os
from pydantic import BaseModel, Field
from typing import List, Literal
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

# Import individual track execution services
from .databridge_services.langgraph_agent import run_data_bridge_agent
from app.services.llm_service import answer_from_docs
from app.services.api_services import fetch_and_translate_tools, ask_dynamic_model_with_tools
from app.services.automated_metamind import generate_router_config
from app.services.general_service import answer_general_knowledge

# ============================================================
# PATHS
# ============================================================
_SERVICE_DIR = os.path.dirname(os.path.abspath(__file__))
_GENERAL_CONFIG_PATH = os.path.join(_SERVICE_DIR, "general_knowledge_config.json")
_ROUTER_CONFIG_PATH  = os.path.join(_SERVICE_DIR, "metamind_router_config.json")


# ============================================================
# PYDANTIC SCHEMA
# ============================================================
class RouterDecisionSchema(BaseModel):
  selected_tracks: List[Literal["DB", "FILES", "API", "GENERAL"]] = Field(
      description=(
          "Ordered list of data source track keys needed to fulfill the user intent. "
          "Choose from: DB (structured tables), FILES (uploaded documents), "
          "API (live external tools), GENERAL (world knowledge / greetings / calculations)."
      )
  )


# ============================================================
# GENERAL-KNOWLEDGE CONFIG LOADER
# ============================================================
_general_cfg_cache: dict | None = None

def _load_general_config() -> dict:
  global _general_cfg_cache
  if _general_cfg_cache is not None:
      return _general_cfg_cache
  try:
      with open(_GENERAL_CONFIG_PATH, "r") as f:
          _general_cfg_cache = json.load(f)
      print("✅ [GENERAL CONFIG] Loaded general_knowledge_config.json")
  except Exception as e:
      print(f"⚠️ [GENERAL CONFIG] Could not load config: {e}. Using empty defaults.")
      _general_cfg_cache = {"general_knowledge_routing": {}}
  return _general_cfg_cache


# ============================================================
# HEURISTIC PARSING ENGINE
# ============================================================
def _flatten_patterns(cfg_section: dict) -> list[str]:
  """Recursively collect all string lists from a config section into one flat list."""
  result = []
  for value in cfg_section.values():
      if isinstance(value, list):
          result.extend([p.lower() for p in value if isinstance(p, str)])
      elif isinstance(value, dict):
          result.extend(_flatten_patterns(value))
  return result


def classify_query_heuristic(user_query: str) -> str | None:
  """
  Fast-track check. If the query hits general chitchat, greetings, or basic
  time/date triggers, send it directly to GENERAL.
  """
  cfg = _load_general_config().get("general_knowledge_routing", {})
  q = user_query.lower().strip()

  general_patterns = _flatten_patterns(cfg.get("strong_general_indicators", {}))
  for pat in general_patterns:
      if pat in q:
          return "GENERAL"

  return None  # Drop down to Layer 2 structured LLM routing


# ============================================================
# ROUTER SERVICE ORCHESTRATOR CLASS
# ============================================================
class RouterService:

  def __init__(self):
      try:
          print("\n🔄 Running Router Schema Configuration Sync Check...")
          generate_router_config(force=False)
      except Exception as e:
          print(f"⚠️ [SCHEMA SYNC]: Failed to check structural drifts: {e}")

      # Prime the general config cache at application startup
      _load_general_config()

  def get_smart_response(
      self,
      user_query: str,
      model_name: str = "gpt-4o-mini",
      session_id=1,
      custom_key: str = "",
      system_instructions: str = ""
  ) -> dict:

      try:
          print("\n" + "=" * 60)
          print(f"🧠 SMART ROUTER PROCESSING QUERY: {user_query}")
          session_id = str(session_id)
          master_steps: list = []

          # ------------------------------------------------
          # LAYER 1: Fast heuristic check (Zero LLM Token Cost)
          # ------------------------------------------------
          heuristic_result = classify_query_heuristic(user_query)
          if heuristic_result == "GENERAL":
              print("🌐 [FAST PATH] Heuristic matched GENERAL knowledge pattern.")
              #return answer_general_knowledge(
              #    user_query, model_name, custom_key,
              #    system_instructions, master_steps
              #)
              fast_res = answer_general_knowledge(
                  user_query, model_name, custom_key,
                  system_instructions, master_steps
              )
              
              # 2. Map the chain of thought key explicitly right here
              if isinstance(fast_res, dict):
                  fast_res["chain_of_thought"] = fast_res.get("steps", [])

              return fast_res    


          

          # ------------------------------------------------
          # LAYER 2: Build Context & Schema Instructions for the LLM
          # ------------------------------------------------
          with open(_ROUTER_CONFIG_PATH, "r") as f:
              router_config = json.load(f)

          active_db_tools = fetch_and_translate_tools()
          live_tools_summary = "\n".join(
              f"- Tool: '{t.get('function', {}).get('name')}' "
              f"-> {t.get('function', {}).get('description')}"
              for t in active_db_tools
          ) or "No active external tools registered currently."

          routing_blueprint = json.dumps(router_config["routing_menu"], indent=2)

          system_prompt = f"""
You are the enterprise orchestration router layer. Your job is: "Step 0: Identify right data source".
Analyze the user query carefully and decide which data source(s) are required to satisfy the intent.

AVAILABLE ROUTING MENU CONFIGURATION:
{routing_blueprint}

LIVE REGISTERED TOOLS FOR THE 'API' TRACK:
{live_tools_summary}

ADDITIONAL TRACK — 'GENERAL':
Choose "GENERAL" when the query is about general world knowledge, public facts,
geography, science, history, greetings, calculations, or definitions that are
NOT found in the DB tables, uploaded FILES, or registered API tools above.

DECISION RULES (apply in order):
1. If query mentions DB table/column names or implies structured lookups → choose DB
2. If query uses count/sum/list/show on company transactional metrics → choose DB
3. If query asks about internal company-specific content, policies, or records → choose FILES
4. If query matches a registered live external API tool description → choose API
5. If query is a general question, world knowledge statement, math statement, or broad definition → choose GENERAL
6. When in doubt between DB and FILES → prefer FILES
7. Multiple sources allowed if the query genuinely requires context from both

Return ONLY the selected_tracks JSON array.
"""
          if system_instructions.strip():
              system_prompt += f"\n\nUSER CUSTOM FORMATTING INSTRUCTIONS:\n{system_instructions}"

          # ------------------------------------------------
          # LAYER 3: Structured LLM Route Target Selector
          # ------------------------------------------------
          openai_api_key = custom_key if custom_key else os.getenv("OPENAI_API_KEY")
          structured_llm = ChatOpenAI(
              model="gpt-4o-mini",
              temperature=0.0,
              openai_api_key=openai_api_key
          ).with_structured_output(RouterDecisionSchema)

          decision = structured_llm.invoke([
              SystemMessage(content=system_prompt),
              HumanMessage(content=user_query)
          ])
          required_sources = decision.selected_tracks
          print(f"🧠 Router Decision: {required_sources}")

          # ------------------------------------------------
          # LAYER 4: Sequential Execution Loop
          # ------------------------------------------------
          accumulated_context = f"Initial Prompt Context: {user_query}\n"
          full_result: dict | None = None

          for source in required_sources:
              print(f"🧭 Route Triggered -> Executing Track: {source}")

              # ---------- FILES TRACK ----------
              if source == "FILES":
                  rag_res = answer_from_docs(
                      user_query,
                      model_name=model_name,
                      session_id=session_id,
                      custom_key=custom_key
                  )
                  master_steps.extend(rag_res.get("rag_chain_of_thought", []))

                  if len(required_sources) == 1:
                      return {
                          "answer": rag_res.get("answer"),
                          "sql": None,
                          "table": [],
                          "chart": {},
                          "insights": [],
                          "steps": master_steps
                      }
                  accumulated_context += f"\n[Context from Uploaded Files]: {rag_res.get('answer')}"

              # ---------- DB TRACK ----------
              elif source == "DB":
                  sql_ctx = (
                      f"{user_query}. Context insights: {accumulated_context}"
                      if len(required_sources) > 1 else user_query
                  )
                  full_result = run_data_bridge_agent(
                      sql_ctx,
                      session_id=session_id,
                      model_name=model_name,
                      custom_key=custom_key
                  )

                  if len(required_sources) == 1:
                        res = full_result["chat_ui"]
                        res["chain_of_thought"] = res.get("steps", [])
                        return res

                  accumulated_context += f"\n[Context from SQL Records]: {full_result['chat_ui'].get('answer')}"

                  if isinstance(full_result, dict) and "chat_ui" in full_result:
                        master_steps.extend(full_result["chat_ui"].get("steps", []))
                  else:
                        master_steps.append("Successfully executed SQL Agent table records retrieval pass.")

                #   if len(required_sources) == 1:
                #       return full_result["chat_ui"]

                #   accumulated_context += f"\n[Context from SQL Records]: {full_result['chat_ui'].get('answer')}"
                #   master_steps.append("Successfully executed SQL Agent table records retrieval pass.")

              # ---------- API TRACK ----------
              elif source == "API":
                  final_api_payload = ask_dynamic_model_with_tools(
                      user_message=accumulated_context,
                      llm_tools_list=active_db_tools,
                      model_name=model_name,
                      session_id=session_id,
                      custom_key=custom_key,
                      ollama_config={"url": "http://ollama:11434/api/chat", "temperature": 0},
                      display_query=user_query
                  )
                  if isinstance(final_api_payload, dict):
                        api_steps = final_api_payload.get("steps", [])
                        master_steps.extend(api_steps)
                        api_answer = final_api_payload.get("answer", "")
                  else:
                        api_answer = str(final_api_payload)
                        master_steps.append("Successfully executed Dynamic API Tools execution pass.")


                #   api_answer = (
                #       final_api_payload.get("answer", str(final_api_payload))
                #       if isinstance(final_api_payload, dict) else str(final_api_payload)
                #   )
                #   master_steps.extend(
                #       final_api_payload.get("steps", ["Successfully executed Dynamic API Tools execution pass."])
                #   )

                  if len(required_sources) == 1:
                      return {
                          "answer": api_answer,
                          "sql": None,
                          "table": [],
                          "chart": {},
                          "insights": [],
                          "steps": master_steps
                      }
                  accumulated_context += f"\n[Context from API Integrations]: {api_answer}"

                   

              # ---------- GENERAL TRACK ----------
              elif source == "GENERAL":
                  gen_result = answer_general_knowledge(
                      user_query, model_name, custom_key,
                      system_instructions, master_steps
                  )
                  if len(required_sources) == 1:
                      return gen_result

                  accumulated_context += f"\n[Context from General Knowledge]: {gen_result.get('answer')}"
                  master_steps = gen_result.get("steps", master_steps)

          # ------------------------------------------------
          # LAYER 5: Combined Multi-Track Response Merging
          # ------------------------------------------------
          if len(required_sources) > 1:
              print("🔄 Synthesizing multi-source context into a unified final answer...")
              synthesis_prompt = f"""
You are the final answer synthesis layer for Saarthi AI.
Combine the collected tracking contexts below into a single, cohesive, fluid response for the user.
Do not mention technical terms like 'SQL Records', 'Uploaded Files', 'Database', or track names.
Provide a clean, natural enterprise assistant response.

{accumulated_context}
"""
              synthetic_response = ChatOpenAI(
                  model="gpt-4o-mini",
                  temperature=0.3,
                  openai_api_key=openai_api_key
              ).invoke([SystemMessage(content=synthesis_prompt)])
              final_answer = synthetic_response.content
          else:
              final_answer = accumulated_context.replace("Initial Prompt Context:", "").strip()

          has_db_records = ("DB" in required_sources and isinstance(full_result, dict) and "chat_ui" in full_result)

          return {
              "answer": final_answer,
              "sql": full_result["chat_ui"].get("sql") if has_db_records else None,
              "table": full_result["chat_ui"].get("table", []) if has_db_records else [],
              "chart": full_result["chat_ui"].get("chart", {}) if has_db_records else {},
              "insights": full_result["chat_ui"].get("insights", []) if has_db_records else [],
              "steps": master_steps
          }

      except Exception as e:
          import traceback
          print(f"❌ [CRITICAL PIPELINE FAILURE]: {e}")
          traceback.print_exc()
          return {
              "answer": "The system encountered an error routing your request.",
              "sql": None,
              "table": [],
              "chart": {},
              "insights": [],
              "steps": [f"Failed at master router step: {e}"]
          }