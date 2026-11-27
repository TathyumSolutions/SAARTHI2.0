"""
Per-step model and API key in the data-bridge pipeline.

Regression: with Llama selected in the chat bar (no API key) and the agents
set to GPT in LLM Mapping, every GPT step received Llama's empty key and
failed, so GPT could not be used again. Steps set to a bare "gpt-4o"
(presets, auto-fill) only ever used OPENAI_API_KEY from .env.
"""
import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app.services import model_selection_service as mss
from app.services.databridge_services import langgraph_agent

USER_ID = 7


def _config(model, key, user_id=USER_ID, company=""):
    return SimpleNamespace(
        name=model, model=model, user_id=user_id, company_code=company,
        settings={"custom_key": key, "company_code": company},
    )


def _credentials(step, requested, requested_key, rows, company="ACME"):
    model_config = MagicMock()
    model_config.query.filter.return_value.all.return_value = rows
    with patch.object(mss, "ModelConfiguration", model_config), \
         patch.object(mss, "_user_company_code", return_value=company):
        return mss.get_step_credentials(step, requested, requested_key, user_id=USER_ID)


# ------------------------------------------------------------ model ids

def test_bare_registry_api_model_runs_through_api_route():
    assert mss._runtime_model_name("gpt-4o") == "api://gpt-4o"
    assert mss._runtime_model_name("claude-3-5-haiku") == "api://claude-3-5-haiku"
    assert mss._runtime_model_name("llama2:7b") == "ollama://llama2:7b"
    assert mss._runtime_model_name("api://gpt-4o") == "api://gpt-4o"


# ------------------------------------------------------------ credentials

def test_step_on_chat_bar_model_keeps_request_key():
    assert _credentials("api://gpt-4o", "gpt-4o", "sk-chat", rows=[]) == "sk-chat"


def test_local_step_gets_no_key():
    assert _credentials("ollama://llama2:7b", "api://gpt-4o", "sk-chat", rows=[]) == ""


def test_gpt_step_under_llama_uses_gpt_configuration_key():
    rows = [_config("api://gpt-4o", "sk-gpt")]
    assert _credentials("api://gpt-4o", "ollama://llama2:7b", "", rows) == "sk-gpt"


def test_claude_step_under_gpt_does_not_get_openai_key():
    rows = [_config("api://claude-3-5-sonnet", "sk-ant")]
    assert _credentials("api://claude-3-5-sonnet", "api://gpt-4o", "sk-openai", rows) == "sk-ant"


def test_company_key_is_used_but_never_another_company_key():
    colleague = _config("api://gpt-4o", "sk-colleague", user_id=99, company="ACME")
    stranger = _config("api://gpt-4o", "sk-stranger", user_id=100, company="OTHER")
    assert _credentials("api://gpt-4o", "ollama://llama2:7b", "", [stranger, colleague]) == "sk-colleague"
    assert _credentials("api://gpt-4o", "ollama://llama2:7b", "", [stranger]) == ""


# ------------------------------------------------------------ graph nodes

def test_each_step_resolves_model_and_key_afresh():
    """GPT for SQL Generator only, Llama in the chat bar: the GPT step gets
    the GPT key, and the next step goes back to Llama with no key."""
    def model_for(step, requested_main_model=None, user_id=1):
        return "api://gpt-4o" if step == "sql_generator" else requested_main_model

    def creds(step_model, requested, requested_key, user_id=1):
        return "sk-gpt" if step_model == "api://gpt-4o" else requested_key

    state = {
        "model_name": "ollama://llama2:7b",
        "requested_model_name": "ollama://llama2:7b",
        "requested_custom_key": "",
        "custom_key": "",
        "user_id": USER_ID,
    }
    with patch.object(langgraph_agent, "get_model_for_step", side_effect=model_for), \
         patch.object(langgraph_agent, "get_step_credentials", side_effect=creds):
        langgraph_agent._use_step_model(state, "sql_generator")
        assert (state["model_name"], state["custom_key"]) == ("api://gpt-4o", "sk-gpt")

        langgraph_agent._use_step_model(state, "query_formatter")
        assert (state["model_name"], state["custom_key"]) == ("ollama://llama2:7b", "")


def test_step_without_a_resolved_model_falls_back_to_chat_bar_model():
    state = {
        "model_name": "api://gpt-4o",  # left over from an earlier step
        "requested_model_name": "ollama://llama2:7b",
        "requested_custom_key": "",
        "custom_key": "sk-gpt",
        "user_id": USER_ID,
    }
    with patch.object(langgraph_agent, "get_model_for_step", return_value=None), \
         patch.object(langgraph_agent, "get_step_credentials", return_value=""):
        assert langgraph_agent._use_step_model(state, "query_validator") == "ollama://llama2:7b"
    assert state["custom_key"] == ""
