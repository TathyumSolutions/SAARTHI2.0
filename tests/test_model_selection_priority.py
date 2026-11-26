"""
The model picked in the chat bar must be the one the SQL pipeline runs.

Regression: a user with no saved LLM Mapping (no UserModelPipeline row) had
every step resolved from the seeded global default (ollama://llama2:7b),
so selecting GPT still ran the whole pipeline on Llama.
"""
import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app.services import model_selection_service as mss

GLOBAL_DEFAULT = SimpleNamespace(model="ollama://llama2:7b", settings={"step_overrides": {}})


def _resolve(step, requested, pipeline=None, global_default=GLOBAL_DEFAULT):
    query = MagicMock()
    query.filter_by.return_value.first.return_value = pipeline
    with patch.object(mss, "UserModelPipeline", SimpleNamespace(query=query)), \
         patch.object(mss, "get_global_default_config", return_value=global_default):
        return mss.get_model_for_step(step, requested_main_model=requested, user_id=7)


def test_selected_gpt_wins_over_llama_global_default_without_llm_mapping():
    assert _resolve("sql_generator", "api://gpt-4o") == "api://gpt-4o"


def test_global_step_overrides_do_not_replace_the_selected_model():
    default = SimpleNamespace(model="ollama://llama2:7b",
                              settings={"step_overrides": {"sql_generator": "ollama://llama2:7b"}})
    assert _resolve("sql_generator", "api://gpt-4o", global_default=default) == "api://gpt-4o"


def test_selected_model_differing_from_llm_mapping_main_model_wins():
    pipeline = SimpleNamespace(main_model="llama2:7b", step_models={"SQL Generator": "llama2:7b"})
    assert _resolve("sql_generator", "api://gpt-4o", pipeline) == "api://gpt-4o"


def test_llm_mapping_step_models_apply_when_its_main_model_is_selected():
    pipeline = SimpleNamespace(main_model="api://gpt-4o", step_models={"SQL Generator": "api://gpt-4o-mini"})
    assert _resolve("sql_generator", "api://gpt-4o", pipeline) == "api://gpt-4o-mini"
    assert _resolve("query_sense", "api://gpt-4o", pipeline) == "api://gpt-4o"


def test_registry_llama_is_routed_through_ollama():
    assert _resolve("sql_generator", "llama2:7b") == "ollama://llama2:7b"


def test_no_selection_falls_back_to_global_default():
    assert _resolve("sql_generator", None) == "ollama://llama2:7b"
