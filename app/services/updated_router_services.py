"""
Smart Router Service (v2 — tool-calling / agentic)
====================================================

Why this file was rewritten:

The old version (`RouterService.get_smart_response`, pre-rewrite) picked a
track using `.with_structured_output(RouterDecisionSchema)` against a fixed
list of 4 categories (DB, FILES, API, GENERAL). That's why a question like
"do you have a DB connection?" got force-fit into "DB" and triggered the
full 8-agent LangGraph pipeline — there was no category for questions about
the system's own configuration, only categories for actual data questions.

This version replaces that fixed classifier with real tool-calling
(`bind_tools`, the same pattern already used in api_services.py for the API
track). The model is handed a small toolbox — one of which,
`check_data_source_status`, answers configuration questions directly from
`metamind_router_config.json` with no further agent calls at all — and picks
whichever tool(s) actually fit the question. Adding a new capability later
means registering a new tool, not editing a classification prompt and hoping
the model respects a new rule buried in a paragraph.

The model is also now given real conversation context: the current query,
recent chat history, and the router config, assembled with a token budget so
none of it silently blows past the model's context window. The current
query is never trimmed — if something has to give, it's the oldest chat
history first, then the router config.
"""

import json
import os
from typing import List, Literal, Optional

from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_core.tools import tool

# Import individual track execution services (unchanged from before)
from .databridge_services.langgraph_agent import run_data_bridge_agent
from app.services.llm_service import answer_from_docs
from app.services.api_services import fetch_and_translate_tools, ask_dynamic_model_with_tools
from app.services.automated_metamind import generate_router_config
from app.services.general_service import answer_general_knowledge

# Token counting is best-effort: fall back to a rough estimate if tiktoken
# isn't installed, rather than hard-failing the whole router.
try:
    import tiktoken
    _ENCODING = tiktoken.get_encoding("cl100k_base")
except Exception:
    _ENCODING = None


def _count_tokens(text: str) -> int:
    if not text:
        return 0
    if _ENCODING is not None:
        return len(_ENCODING.encode(text))
    return max(1, len(text) // 4)  # ~4 chars/token, rough fallback


# ============================================================
# PATHS
# ============================================================
_SERVICE_DIR = os.path.dirname(os.path.abspath(__file__))
_GENERAL_CONFIG_PATH = os.path.join(_SERVICE_DIR, "general_knowledge_config.json")
_ROUTER_CONFIG_PATH = os.path.join(_SERVICE_DIR, "metamind_router_config.json")

# Router-context token budget. gpt-4o-mini's real window is much larger than
# this — this cap exists to keep every routing call cheap and fast, not
# because the model can't technically fit more. Raise it if you find the
# router genuinely needs more history to make good decisions.
ROUTER_CONTEXT_TOKEN_BUDGET = 6000
_HISTORY_SHARE = 0.4   # of the remaining budget, after the current query
_MIN_CONFIG_BUDGET = 300


# ============================================================
# GENERAL-KNOWLEDGE CONFIG LOADER (unchanged)
# ============================================================
_general_cfg_cache: Optional[dict] = None


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


def _flatten_patterns(cfg_section: dict) -> list[str]:
    result = []
    for value in cfg_section.values():
        if isinstance(value, list):
            result.extend([p.lower() for p in value if isinstance(p, str)])
        elif isinstance(value, dict):
            result.extend(_flatten_patterns(value))
    return result


def classify_query_heuristic(user_query: str) -> str | None:
    """
    Layer 1 — free keyword check for greetings/small talk/date-time questions.
    Unrelated to the DB-misrouting bug (its patterns never matched status
    questions in the first place) — kept as-is, it's a real cost saver.
    """
    cfg = _load_general_config().get("general_knowledge_routing", {})
    q = user_query.lower().strip()
    for pat in _flatten_patterns(cfg.get("strong_general_indicators", {})):
        if pat in q:
            return "GENERAL"
    return None


# ============================================================
# ROUTER CONFIG LOADING + TRIMMING
# ============================================================
def _load_router_config() -> dict:
    """Always reads fresh from disk — freshness of this file is handled by
    generate_router_config() elsewhere; this function just reflects whatever
    is currently on disk at call time."""
    with open(_ROUTER_CONFIG_PATH, "r") as f:
        return json.load(f)


def _trim_router_config(config: dict, max_tables: int, max_cols: int,
                         max_tools: int, max_examples: int) -> dict:
    """Returns a shallow, trimmed copy for prompt display only — never
    written back to disk. Caps list/dict sizes so the config can't blow the
    token budget on a schema with hundreds of tables or tools."""
    menu = config.get("routing_menu", {})
    ds = menu.get("datasources", {})
    trimmed_ds = {}

    db = ds.get("DB", {})
    tables = db.get("tables", {})
    trimmed_tables = {}
    for i, (tname, tinfo) in enumerate(tables.items()):
        if i >= max_tables:
            trimmed_tables["__truncated__"] = f"...and {len(tables) - max_tables} more tables not shown"
            break
        trimmed_tables[tname] = {
            "description": tinfo.get("description", ""),
            "columns": (tinfo.get("columns", []) or [])[:max_cols],
        }
    trimmed_ds["DB"] = {
        "description": db.get("description", ""),
        "example_queries": (db.get("example_queries", []) or [])[:max_examples],
        "tables": trimmed_tables,
    }

    files = ds.get("FILES", {})
    trimmed_ds["FILES"] = {
        "description": files.get("description", ""),
        "example_queries": (files.get("example_queries", []) or [])[:max_examples],
        "vector_store_info": files.get("vector_store_info", {}),
    }

    api = ds.get("API", {})
    tools_list = api.get("registered_tools", []) or []
    trimmed_ds["API"] = {
        "description": api.get("description", ""),
        "example_queries": (api.get("example_queries", []) or [])[:max_examples],
        "registered_tools": tools_list[:max_tools],
    }

    return {"routing_menu": {"instructions": menu.get("instructions", ""), "datasources": trimmed_ds}}


def _fit_router_config_to_budget(config: dict, token_budget: int) -> str:
    """Tries progressively smaller caps until the JSON fits the budget;
    falls back to a hard character truncate as an absolute last resort."""
    attempts = [(25, 12, 25, 3), (10, 8, 10, 2), (5, 5, 5, 1), (2, 3, 2, 1)]
    last_str = "{}"
    for max_tables, max_cols, max_tools, max_examples in attempts:
        trimmed = _trim_router_config(config, max_tables, max_cols, max_tools, max_examples)
        s = json.dumps(trimmed, indent=2)
        last_str = s
        if _count_tokens(s) <= token_budget:
            return s
    # Still too big — hard truncate.
    approx_chars = max(token_budget * 4, 200)
    return last_str[:approx_chars] + "\n...(truncated to fit context budget)"


def _normalize_chat_history(chat_history) -> list[dict]:
    """Accepts a list of {"role": "user"|"assistant", "content": str} dicts,
    a plain string (treated as one prior turn), or None."""
    if not chat_history:
        return []
    if isinstance(chat_history, str):
        return [{"role": "user", "content": chat_history}]
    normalized = []
    for turn in chat_history:
        role = turn.get("role", "user")
        content = turn.get("content", "")
        if content:
            normalized.append({"role": role, "content": content})
    return normalized


def _build_router_messages(user_query: str, chat_history, router_config: dict,
                            live_tools_summary: str, system_instructions: str) -> list:
    """
    Assembles the message list for the routing LLM call under a fixed token
    budget. Priority order when something has to be cut:
      1. current query        — never trimmed
      2. recent chat history  — oldest turns dropped first
      3. router config JSON   — capped, then hard-truncated if still too big
    """
    query_tokens = _count_tokens(user_query)
    remaining = max(ROUTER_CONTEXT_TOKEN_BUDGET - query_tokens - 400, _MIN_CONFIG_BUDGET)  # 400 ~ instructions/tool schema overhead

    history_budget = int(remaining * _HISTORY_SHARE)
    config_budget = remaining - history_budget

    # Keep most recent history first, drop oldest turns that don't fit.
    normalized = _normalize_chat_history(chat_history)
    trimmed_history = []
    running = 0
    for turn in reversed(normalized):
        t_tokens = _count_tokens(turn["content"])
        if running + t_tokens > history_budget:
            break
        trimmed_history.insert(0, turn)
        running += t_tokens

    # Whatever history didn't use, the config gets to keep.
    config_budget += (history_budget - running)
    config_str = _fit_router_config_to_budget(router_config, config_budget)

    system_prompt = f"""You are the enterprise orchestration router for Saarthi AI.

CURRENT QUESTION (this is what you are answering — always prioritize this):
{user_query}

Decide which tool(s), if any, are needed to answer it. You may call more than
one tool if the question genuinely needs context from multiple sources.

TOOLS AVAILABLE:
- check_data_source_status: ONLY for questions about the system's own setup
  or configuration — "do you have a DB connection?", "are any documents
  uploaded?", "what data sources are available?", "is X connected?". This
  never touches real data and never runs other agents — use it whenever the
  question is about availability/configuration rather than about the data
  itself.
- query_database: for questions needing real rows/counts/sums/filters from
  connected structured tables.
- search_documents: for questions about internal company documents, policies,
  or uploaded files.
- call_external_api: for questions matching a live registered external tool.
- answer_general_knowledge: for world knowledge, definitions, greetings, or
  anything not covered by the company's own data sources.

If none of the tools fit, just answer directly in plain text.

LIVE REGISTERED TOOLS FOR THE 'API' TRACK:
{live_tools_summary}

CURRENT DATA SOURCE CONFIGURATION (router_metamind.json — may be trimmed for length):
{config_str}
"""
    if system_instructions and system_instructions.strip():
        system_prompt += f"\n\nUSER CUSTOM FORMATTING INSTRUCTIONS:\n{system_instructions}"

    messages = [SystemMessage(content=system_prompt)]
    for turn in trimmed_history:
        if turn["role"] == "assistant":
            messages.append(AIMessage(content=turn["content"]))
        else:
            messages.append(HumanMessage(content=turn["content"]))
    messages.append(HumanMessage(content=user_query))
    return messages


# ============================================================
# TOOL SCHEMAS
# (bodies are placeholders — bind_tools only needs these for their name,
#  description, and argument schema; actual execution happens in
#  TOOL_DISPATCH below, where real closures like model_name/session_id
#  are available.)
# ============================================================
@tool
def check_data_source_status(track: Literal["DB", "FILES", "API", "ANY"]) -> str:
    """Answer a question about whether a data source is configured/available
    (e.g. 'do you have a DB connection?'). Reads configuration only — never
    runs the DB, FILES, or API agent pipelines."""
    raise NotImplementedError("dispatched manually, see TOOL_DISPATCH")


@tool
def query_database(question: str) -> str:
    """Answer a question that needs real data from connected structured
    database tables (counts, sums, filters, lookups)."""
    raise NotImplementedError("dispatched manually, see TOOL_DISPATCH")


@tool
def search_documents(question: str) -> str:
    """Answer a question about internal company documents, policies, or
    uploaded files."""
    raise NotImplementedError("dispatched manually, see TOOL_DISPATCH")


@tool
def call_external_api(question: str) -> str:
    """Answer a question by calling a live registered external API tool."""
    raise NotImplementedError("dispatched manually, see TOOL_DISPATCH")


@tool
def answer_general_knowledge_tool(question: str) -> str:
    """Answer general world-knowledge questions, greetings, definitions, or
    anything not covered by the company's own data sources."""
    raise NotImplementedError("dispatched manually, see TOOL_DISPATCH")


_ALL_TOOLS = [
    check_data_source_status,
    query_database,
    search_documents,
    call_external_api,
    answer_general_knowledge_tool,
]


# ============================================================
# STATUS CHECK — the fix for the misrouting bug
# ============================================================
def _answer_status_check(args: dict, router_config: dict) -> dict:
    menu = router_config.get("routing_menu", {}).get("datasources", {})

    db_tables = menu.get("DB", {}).get("tables", {}) or {}
    files_info = menu.get("FILES", {}).get("vector_store_info", {}) or {}
    api_tools = menu.get("API", {}).get("registered_tools", []) or []

    available = {
        "DB": bool(db_tables),
        "FILES": (files_info.get("points_count", 0) or 0) > 0,
        "API": bool(api_tools),
    }

    track = (args.get("track") or "ANY").upper()
    if track in available:
        yes_no = "Yes" if available[track] else "No"
        detail = {
            "DB": f"{len(db_tables)} table(s) available." if available["DB"] else "No tables configured.",
            "FILES": f"{files_info.get('points_count', 0)} document chunk(s) indexed." if available["FILES"] else "No documents uploaded yet.",
            "API": f"{len(api_tools)} tool(s) registered." if available["API"] else "No external tools registered.",
        }[track]
        answer = f"{yes_no} — {detail}"
    else:
        parts = [f"{k}: {'available' if v else 'not available'}" for k, v in available.items()]
        answer = "Current data source status — " + ", ".join(parts) + "."

    return {
        "answer": answer,
        "steps": ["Checked data source configuration directly (metamind_router_config.json) — no agents were run."],
        "sql": None, "table": [], "chart": {}, "insights": [],
    }


# ============================================================
# TRACK DISPATCH (same underlying services as before, called manually)
# ============================================================
def _run_db_track(question: str, ctx: dict) -> dict:
    full_result = run_data_bridge_agent(
        question, session_id=ctx["session_id"],
        model_name=ctx["model_name"], custom_key=ctx["custom_key"]
    )
    chat_ui = full_result.get("chat_ui", {}) if isinstance(full_result, dict) else {}
    return {
        "answer": chat_ui.get("answer"),
        "steps": chat_ui.get("steps", []),
        "sql": chat_ui.get("sql"), "table": chat_ui.get("table", []),
        "chart": chat_ui.get("chart", {}), "insights": chat_ui.get("insights", []),
    }


def _run_files_track(question: str, ctx: dict) -> dict:
    rag_res = answer_from_docs(
        question, model_name=ctx["model_name"],
        session_id=ctx["session_id"], custom_key=ctx["custom_key"]
    )
    return {
        "answer": rag_res.get("answer"),
        "steps": rag_res.get("rag_chain_of_thought", []),
        "sql": None, "table": [], "chart": {}, "insights": [],
    }


def _run_api_track(question: str, ctx: dict) -> dict:
    payload = ask_dynamic_model_with_tools(
        user_message=question, llm_tools_list=ctx["active_db_tools"],
        model_name=ctx["model_name"], session_id=ctx["session_id"],
        custom_key=ctx["custom_key"],
        ollama_config={"url": "http://ollama:11434/api/chat", "temperature": 0},
        display_query=question,
    )
    if isinstance(payload, dict):
        return {
            "answer": payload.get("answer", ""),
            "steps": payload.get("steps", []),
            "sql": None, "table": [], "chart": {}, "insights": [],
        }
    return {"answer": str(payload), "steps": ["Successfully executed Dynamic API Tools execution pass."],
            "sql": None, "table": [], "chart": {}, "insights": []}


def _run_general_track(question: str, ctx: dict) -> dict:
    gen_result = answer_general_knowledge(
        question, ctx["model_name"], ctx["custom_key"], ctx["system_instructions"], []
    )
    return {
        "answer": gen_result.get("answer"),
        "steps": gen_result.get("steps", []),
        "sql": None, "table": [], "chart": {}, "insights": [],
    }


TOOL_DISPATCH = {
    "query_database": lambda args, ctx: _run_db_track(args.get("question", ctx["user_query"]), ctx),
    "search_documents": lambda args, ctx: _run_files_track(args.get("question", ctx["user_query"]), ctx),
    "call_external_api": lambda args, ctx: _run_api_track(args.get("question", ctx["user_query"]), ctx),
    "answer_general_knowledge_tool": lambda args, ctx: _run_general_track(args.get("question", ctx["user_query"]), ctx),
    "check_data_source_status": lambda args, ctx: _answer_status_check(args, ctx["router_config"]),
}


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
        _load_general_config()

    def get_smart_response(
        self,
        user_query: str,
        model_name: str = "gpt-4o-mini",
        session_id=1,
        custom_key: str = "",
        system_instructions: str = "",
        chat_history: Optional[list] = None,
    ) -> dict:

        try:
            print("\n" + "=" * 60)
            print(f"🧠 SMART ROUTER PROCESSING QUERY: {user_query}")
            session_id = str(session_id)

            # ------------------------------------------------
            # LAYER 1: Fast heuristic check (Zero LLM Token Cost)
            # ------------------------------------------------
            if classify_query_heuristic(user_query) == "GENERAL":
                print("🌐 [FAST PATH] Heuristic matched GENERAL knowledge pattern.")
                fast_res = answer_general_knowledge(
                    user_query, model_name, custom_key, system_instructions, []
                )
                if isinstance(fast_res, dict):
                    fast_res["chain_of_thought"] = fast_res.get("steps", [])
                return fast_res

            # ------------------------------------------------
            # LAYER 2: Load config + tools, build token-budgeted messages
            # ------------------------------------------------
            router_config = _load_router_config()
            active_db_tools = fetch_and_translate_tools()
            live_tools_summary = "\n".join(
                f"- Tool: '{t.get('function', {}).get('name')}' -> {t.get('function', {}).get('description')}"
                for t in active_db_tools
            ) or "No active external tools registered currently."

            messages = _build_router_messages(
                user_query, chat_history, router_config, live_tools_summary, system_instructions
            )

            # ------------------------------------------------
            # LAYER 3: Tool-calling router decision
            # ------------------------------------------------
            openai_api_key = custom_key if custom_key else os.getenv("OPENAI_API_KEY")
            router_llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.0, openai_api_key=openai_api_key)
            response = router_llm.bind_tools(_ALL_TOOLS).invoke(messages)
            tool_calls = getattr(response, "tool_calls", None) or []
            print(f"🧠 Router selected tools: {[c['name'] for c in tool_calls]}")

            # No tool needed — model judged it answerable directly.
            if not tool_calls:
                return {
                    "answer": response.content,
                    "sql": None, "table": [], "chart": {}, "insights": [],
                    "steps": ["Router answered directly, no data source tool needed."],
                }

            ctx = {
                "user_query": user_query, "model_name": model_name, "session_id": session_id,
                "custom_key": custom_key, "system_instructions": system_instructions,
                "active_db_tools": active_db_tools, "router_config": router_config,
            }

            # ------------------------------------------------
            # LAYER 4: Execute selected tool(s)
            # ------------------------------------------------
            results = []
            master_steps: list = []
            for call in tool_calls:
                name = call["name"]
                args = call.get("args", {}) or {}
                worker = TOOL_DISPATCH.get(name)
                if not worker:
                    continue
                print(f"🧭 Route Triggered -> Executing Tool: {name}")
                result = worker(args, ctx)
                master_steps.extend(result.get("steps", []))
                results.append((name, result))

            if not results:
                return {
                    "answer": "The system encountered an error routing your request.",
                    "sql": None, "table": [], "chart": {}, "insights": [],
                    "steps": ["No dispatchable tool matched the router's selection."],
                }

            # Single tool selected — return its result directly, unmodified.
            if len(results) == 1:
                _, result = results[0]
                result["chain_of_thought"] = master_steps
                result["steps"] = master_steps
                return result

            # ------------------------------------------------
            # LAYER 5: Multi-tool synthesis
            # ------------------------------------------------
            accumulated_context = "\n".join(
                f"[Context from {name}]: {result.get('answer')}" for name, result in results
            )
            synthesis_prompt = f"""You are the final answer synthesis layer for Saarthi AI.
Combine the collected contexts below into a single, cohesive, fluid response for the user.
Do not mention technical terms like 'SQL Records', 'Uploaded Files', 'Database', or tool names.
Provide a clean, natural enterprise assistant response.

{accumulated_context}
"""
            synthetic_response = ChatOpenAI(
                model="gpt-4o-mini", temperature=0.3, openai_api_key=openai_api_key
            ).invoke([SystemMessage(content=synthesis_prompt)])

            db_result = next((r for n, r in results if n == "query_database"), {})
            return {
                "answer": synthetic_response.content,
                "sql": db_result.get("sql"), "table": db_result.get("table", []),
                "chart": db_result.get("chart", {}), "insights": db_result.get("insights", []),
                "steps": master_steps,
                "chain_of_thought": master_steps,
            }

        except Exception as e:
            import traceback
            print(f"❌ [CRITICAL PIPELINE FAILURE]: {e}")
            traceback.print_exc()
            return {
                "answer": "The system encountered an error routing your request.",
                "sql": None, "table": [], "chart": {}, "insights": [],
                "steps": [f"Failed at master router step: {e}"],
            }
