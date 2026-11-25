"""
LLM selection for the router's own calls (tool choice, result combiner,
multi-source synthesis).

These calls used to be hard-wired to OpenAI gpt-4o-mini with
`custom_key or OPENAI_API_KEY`, which broke in two ways:

* With a local (Ollama) model selected there is no custom key, so without
  OPENAI_API_KEY in .env every question failed before any agent ran -
  "Llama doesn't work" even though Ollama itself was fine.
* With a non-OpenAI cloud model selected (Claude, Gemini, a custom
  OpenAI-compatible endpoint) its key was sent to OpenAI -> 401.

Resolution order, for every router call:
1. A selected non-OpenAI cloud model (api://...) is used itself, with its
   own key/endpoint - honouring the user's choice.
2. Otherwise OpenAI gpt-4o-mini, if an OpenAI key can be found: the
   selected OpenAI model's own key, then OPENAI_API_KEY, then an OpenAI
   key saved on one of the *same company's* model configurations.
3. Otherwise (local model, no OpenAI key anywhere): the selected Ollama
   model. It cannot do tool calling, so routing uses a JSON prompt with a
   deterministic fallback (see route_with_local_model).
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from typing import Callable, List, Optional

import requests
from langchain_core.messages import BaseMessage

from app.models.model_config import ModelConfiguration
from app.services.llm_call_logger import record_ollama_call
from app.services.llm_providers import resolve_ollama_endpoint

OPENAI_ROUTER_MODEL = "gpt-4o-mini"
DEFAULT_LOCAL_MODEL = "llama2:7b"
LOCAL_TIMEOUT_SECONDS = 300

_OPENAI_MODEL_PATTERN = re.compile(r"^(gpt-|chatgpt|o1|o3|o4)|openai")


# ------------------------------------------------------------------
# Model / configuration helpers
# ------------------------------------------------------------------
def _bare(model_name: Optional[str]) -> str:
    return re.sub(r"^(ollama|api)://", "", str(model_name or "").strip()).lower()


def is_local_model(model_name: Optional[str]) -> bool:
    value = str(model_name or "").strip()
    if value.startswith("ollama://") or value == "llama3":
        return True
    try:
        from app.services.model_registry_service import MODELS_REGISTRY
        return MODELS_REGISTRY.get(value, {}).get("type") == "open_source"
    except Exception:
        return False


def is_openai_model(model_name: Optional[str]) -> bool:
    return not is_local_model(model_name) and bool(_OPENAI_MODEL_PATTERN.search(_bare(model_name)))


def _row_company(row: ModelConfiguration) -> str:
    settings = row.settings if isinstance(row.settings, dict) else {}
    return str(row.company_code or settings.get("company_code") or "").strip()


def _config_settings(model_name: str, company_code: Optional[str]) -> dict:
    """Settings of the configuration saved for `model_name`, preferring the
    caller's company (same rule as chat_routes.resolve_model_credentials)."""
    if not model_name:
        return {}
    rows = ModelConfiguration.query.filter_by(model=model_name).all()
    chosen = next((r for r in rows if company_code and _row_company(r) == company_code), None)
    chosen = chosen or (rows[0] if rows else None)
    return chosen.settings if chosen and isinstance(chosen.settings, dict) else {}


def _is_openai_endpoint(base_url: Optional[str]) -> bool:
    return not base_url or "api.openai.com" in str(base_url)


def resolve_openai_key(model_name: str, custom_key: str, company_code: Optional[str]) -> Optional[str]:
    """An OpenAI API key usable for gpt-4o-mini, or None."""
    if custom_key and is_openai_model(model_name):
        if _is_openai_endpoint(_config_settings(model_name, company_code).get("base_url")):
            return custom_key

    env_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if env_key:
        return env_key

    # Only ever borrow a key saved by the same company - never another tenant's.
    if company_code:
        for row in ModelConfiguration.query.filter(ModelConfiguration.name != "global_default").all():
            settings = row.settings if isinstance(row.settings, dict) else {}
            if (
                _row_company(row) == company_code
                and settings.get("custom_key")
                and is_openai_model(row.model)
                and _is_openai_endpoint(settings.get("base_url"))
            ):
                return settings["custom_key"]
    return None


# ------------------------------------------------------------------
# Router LLM
# ------------------------------------------------------------------
@dataclass(frozen=True)
class RouterModel:
    """What the router talks to. `chat_model` is None for a local Ollama
    model, which is called through its HTTP API instead."""
    label: str
    provider: str
    chat_model: object = None
    ollama_model: Optional[str] = None
    ollama_url: Optional[str] = None

    @property
    def supports_tools(self) -> bool:
        return self.chat_model is not None


def _cloud_chat_model(model_name: str, custom_key: str, company_code: Optional[str], temperature: float):
    bare = _bare(model_name)
    settings = _config_settings(model_name, company_code)
    key = custom_key or settings.get("custom_key") or ""
    base_url = settings.get("base_url")
    if base_url:
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=bare, temperature=temperature,
                          openai_api_key=key or "placeholder-key", openai_api_base=base_url)
    from app.services.llm_providers import resolve_dynamic_llm
    return resolve_dynamic_llm(bare, key, temperature=temperature, strict=False)


def select_router_model(model_name: str, custom_key: str, company_code: Optional[str],
                        temperature: float = 0.0) -> RouterModel:
    """Picks the LLM for a router-level call - see the module docstring."""
    if model_name and not is_local_model(model_name) and not is_openai_model(model_name):
        return RouterModel(
            label=_bare(model_name), provider="api",
            chat_model=_cloud_chat_model(model_name, custom_key, company_code, temperature),
        )

    openai_key = resolve_openai_key(model_name, custom_key, company_code)
    if openai_key:
        from langchain_openai import ChatOpenAI
        return RouterModel(
            label=OPENAI_ROUTER_MODEL, provider="openai",
            chat_model=ChatOpenAI(model=OPENAI_ROUTER_MODEL, temperature=temperature, openai_api_key=openai_key),
        )

    local = _bare(model_name) if is_local_model(model_name) and model_name != "llama3" else DEFAULT_LOCAL_MODEL
    base_url = _config_settings(model_name, company_code).get("base_url") if model_name else None
    return RouterModel(
        label=local, provider="ollama",
        ollama_model=local, ollama_url=resolve_ollama_endpoint(base_url, "generate"),
    )


def _messages_to_prompt(messages: List[BaseMessage]) -> str:
    return "\n\n".join(str(getattr(m, "content", m)) for m in messages)


def _ollama_generate(router_model: RouterModel, prompt: str, *, purpose: str,
                     json_mode: bool = False, temperature: float = 0.0, **log_ctx) -> str:
    payload = {
        "model": router_model.ollama_model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": temperature},
    }
    if json_mode:
        payload["format"] = "json"
    started = time.monotonic()
    response = requests.post(router_model.ollama_url, json=payload, timeout=LOCAL_TIMEOUT_SECONDS)
    response.raise_for_status()
    body = response.json()
    record_ollama_call(
        purpose=purpose, model_name=router_model.ollama_model, prompt_text=prompt,
        response_json=body, duration_ms=int((time.monotonic() - started) * 1000), **log_ctx,
    )
    return str(body.get("response", "")).strip()


def local_text(router_model: RouterModel, messages: List[BaseMessage], *, purpose: str,
               temperature: float = 0.0, **log_ctx) -> str:
    """Plain-text completion from a local (Ollama) router model - used for
    the combiner / synthesis steps when no tool-capable model is available."""
    return _ollama_generate(router_model, _messages_to_prompt(messages), purpose=purpose,
                            temperature=temperature, **log_ctx)


# ------------------------------------------------------------------
# Routing without tool calling (local models)
# ------------------------------------------------------------------
_LOCAL_ROUTE_TOOLS = {
    "query_database": "data from the connected database tables",
    "query_spreadsheet_data": "data from uploaded Excel/CSV tables",
    "search_documents": "content of uploaded documents / policies",
    "call_external_api": "a live registered external API tool",
    "answer_general_knowledge_tool": "greetings, definitions, general knowledge",
}


def _menu(router_config: dict) -> dict:
    return (router_config or {}).get("routing_menu", {}).get("datasources", {}) or {}


def _available_sources(router_config: dict) -> dict:
    menu = _menu(router_config)
    files_info = menu.get("FILES", {}).get("vector_store_info", {}) or {}
    return {
        "db_tables": list((menu.get("DB", {}).get("tables") or {}).keys()),
        "sheet_tables": list((menu.get("SPREADSHEET", {}).get("tables") or {}).keys()),
        "has_documents": (files_info.get("points_count", 0) or 0) > 0,
        "api_tools": [t.get("name") for t in (menu.get("API", {}).get("registered_tools") or []) if t.get("name")],
    }


def _words(text: str) -> set:
    return {w for w in re.split(r"[^a-z0-9]+", str(text).lower()) if len(w) > 2}


def _matching_tables(question: str, tables: List[str]) -> List[str]:
    q_words = _words(question)
    return [t for t in tables if _words(t.replace("_", " ")) & q_words]


def _fallback_route(question: str, sources: dict) -> dict:
    """Deterministic routing when the local model gives no usable answer."""
    db_hits = _matching_tables(question, sources["db_tables"])
    sheet_hits = _matching_tables(question, sources["sheet_tables"])
    if db_hits:
        return {"name": "query_database", "args": {"question": question, "tables": db_hits}}
    if sheet_hits:
        return {"name": "query_spreadsheet_data", "args": {"question": question, "tables": sheet_hits}}
    if sources["db_tables"]:
        return {"name": "query_database", "args": {"question": question, "tables": []}}
    if sources["sheet_tables"]:
        return {"name": "query_spreadsheet_data", "args": {"question": question, "tables": []}}
    if sources["has_documents"]:
        return {"name": "search_documents", "args": {"question": question, "document_codes": []}}
    return {"name": "answer_general_knowledge_tool", "args": {"question": question}}


def _build_local_route_prompt(question: str, sources: dict) -> str:
    available = [name for name in _LOCAL_ROUTE_TOOLS if (
        name == "answer_general_knowledge_tool"
        or (name == "query_database" and sources["db_tables"])
        or (name == "query_spreadsheet_data" and sources["sheet_tables"])
        or (name == "search_documents" and sources["has_documents"])
        or (name == "call_external_api" and sources["api_tools"])
    )]
    lines = [f'- "{name}": {_LOCAL_ROUTE_TOOLS[name]}' for name in available]
    return (
        "Pick the ONE tool that answers the user's question. Reply with JSON only:\n"
        '{"tool": "<tool name>", "tables": ["<table>", ...], "api_tool": "<api tool name>"}\n\n'
        "Tools:\n" + "\n".join(lines) + "\n\n"
        f"Database tables: {', '.join(sources['db_tables'][:60]) or 'none'}\n"
        f"Spreadsheet tables: {', '.join(sources['sheet_tables'][:60]) or 'none'}\n"
        f"API tools: {', '.join(sources['api_tools'][:30]) or 'none'}\n\n"
        f"Question: {question}\nJSON:"
    )


def route_with_local_model(router_model: RouterModel, question: str, router_config: dict,
                           **log_ctx) -> List[dict]:
    """Tool calls (same shape as LangChain's) chosen by a local model that
    has no tool-calling support. Never raises: falls back to deterministic
    routing on any error or unusable answer."""
    sources = _available_sources(router_config)
    try:
        raw = _ollama_generate(router_model, _build_local_route_prompt(question, sources),
                               purpose="router.decision", json_mode=True, **log_ctx)
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        choice = json.loads(match.group(0)) if match else {}
    except Exception as exc:
        print(f"⚠️ [Router] Local routing via {router_model.ollama_model} failed, using fallback: {exc}")
        choice = {}

    tool = str(choice.get("tool") or "").strip()
    tables = [t for t in (choice.get("tables") or []) if isinstance(t, str)]
    if tool == "query_database" and sources["db_tables"]:
        valid = [t for t in tables if t in sources["db_tables"]]
        call = {"name": tool, "args": {"question": question, "tables": valid or _matching_tables(question, sources["db_tables"])}}
    elif tool == "query_spreadsheet_data" and sources["sheet_tables"]:
        valid = [t for t in tables if t in sources["sheet_tables"]]
        call = {"name": tool, "args": {"question": question, "tables": valid or _matching_tables(question, sources["sheet_tables"])}}
    elif tool == "search_documents" and sources["has_documents"]:
        call = {"name": tool, "args": {"question": question, "document_codes": []}}
    elif tool == "call_external_api" and sources["api_tools"]:
        api_tool = choice.get("api_tool") if choice.get("api_tool") in sources["api_tools"] else ""
        call = {"name": tool, "args": {"question": question, "tool_name": api_tool}}
    elif tool == "answer_general_knowledge_tool":
        call = {"name": tool, "args": {"question": question}}
    else:
        call = _fallback_route(question, sources)

    call["id"] = "local-route-0"
    print(f"🧭 [Router] Local model {router_model.ollama_model} routed to {call['name']}")
    return [call]


__all__ = [
    "RouterModel", "select_router_model", "local_text", "route_with_local_model",
    "resolve_openai_key", "is_local_model", "is_openai_model",
]
