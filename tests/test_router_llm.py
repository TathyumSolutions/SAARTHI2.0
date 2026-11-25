"""
Router-level LLM selection (app/services/router_llm.py).

Regression: the router's tool-choice call was hard-wired to OpenAI
gpt-4o-mini with `custom_key or OPENAI_API_KEY`, so with Llama selected and
no OPENAI_API_KEY in .env every question failed, and a non-OpenAI custom
key was sent to OpenAI.
"""
import os
import sys
from unittest.mock import patch

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app.services import router_llm

ROUTER_CONFIG = {"routing_menu": {"datasources": {
    "DB": {"tables": {"loans": {}, "customers": {}}},
    "SPREADSHEET": {"tables": {"agent_commission": {}}},
    "FILES": {"vector_store_info": {"points_count": 0}},
    "API": {"registered_tools": []},
}}}


def _select(model_name, custom_key="", env_key="", settings=None, company_rows=()):
    env = {k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"}
    if env_key:
        env["OPENAI_API_KEY"] = env_key
    with patch.dict(os.environ, env, clear=True), \
         patch.object(router_llm, "_config_settings", return_value=settings or {}), \
         patch.object(router_llm, "ModelConfiguration") as model_cfg, \
         patch("langchain_openai.ChatOpenAI") as chat_openai:
        model_cfg.query.filter.return_value.all.return_value = list(company_rows)
        model_cfg.name = "name"
        result = router_llm.select_router_model(model_name, custom_key, "C1")
        return result, chat_openai


def test_llama_without_any_openai_key_routes_locally_instead_of_failing():
    model, _ = _select("ollama://llama2:7b")
    assert not model.supports_tools
    assert model.ollama_model == "llama2:7b"
    assert model.ollama_url == "http://ollama:11434/api/generate"


def test_llama_with_env_openai_key_uses_gpt_4o_mini_router():
    model, chat_openai = _select("ollama://llama2:7b", env_key="sk-env")
    assert model.supports_tools and model.provider == "openai"
    assert chat_openai.call_args.kwargs["openai_api_key"] == "sk-env"


def test_selected_openai_model_uses_its_own_key():
    _, chat_openai = _select("api://gpt-4o", custom_key="sk-own", env_key="sk-env")
    assert chat_openai.call_args.kwargs["openai_api_key"] == "sk-own"


def test_non_openai_custom_key_is_never_sent_to_openai():
    with patch.object(router_llm, "_cloud_chat_model", return_value=object()) as cloud:
        model, chat_openai = _select("api://claude-3-5-sonnet", custom_key="sk-ant-xyz")
    assert model.provider == "api" and model.supports_tools
    assert cloud.call_args.args[:2] == ("api://claude-3-5-sonnet", "sk-ant-xyz")
    chat_openai.assert_not_called()


def test_local_route_uses_the_models_json_choice():
    model = router_llm.RouterModel(label="llama2:7b", provider="ollama",
                                   ollama_model="llama2:7b", ollama_url="http://x/api/generate")
    with patch.object(router_llm, "_ollama_generate",
                      return_value='{"tool": "query_database", "tables": ["loans", "made_up"]}'):
        calls = router_llm.route_with_local_model(model, "How many loans?", ROUTER_CONFIG)
    assert calls == [{"name": "query_database", "args": {"question": "How many loans?", "tables": ["loans"]},
                      "id": "local-route-0"}]


def test_local_route_falls_back_when_the_model_fails():
    model = router_llm.RouterModel(label="llama2:7b", provider="ollama",
                                   ollama_model="llama2:7b", ollama_url="http://x/api/generate")
    with patch.object(router_llm, "_ollama_generate", side_effect=RuntimeError("ollama down")):
        calls = router_llm.route_with_local_model(model, "agent commission rates", ROUTER_CONFIG)
    assert calls[0]["name"] == "query_spreadsheet_data"
    assert calls[0]["args"]["tables"] == ["agent_commission"]
