"""
Ollama model-id check (app/services/ollama_service.py).

Regression: the Configure Model form built the id from the display name, so
"Llama 2 7B" was saved as "ollama://llama-2-7b" - a model Ollama does not
have - and showed up as a second, broken "Llama 2 7B".
"""
import os
import sys
from unittest.mock import MagicMock, patch

import requests

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app.services import ollama_service


def _tags_response(names):
    response = MagicMock()
    response.json.return_value = {"models": [{"name": n} for n in names]}
    return response


def test_lists_installed_models_from_the_tags_endpoint():
    with patch.object(ollama_service.requests, "get", return_value=_tags_response(["llama2:7b"])) as get:
        assert ollama_service.list_installed_models() == ["llama2:7b"]
    assert get.call_args.args[0] == "http://ollama:11434/api/tags"


def test_tags_url_follows_a_configured_endpoint():
    with patch.object(ollama_service.requests, "get", return_value=_tags_response([])) as get:
        ollama_service.list_installed_models("http://gpu-box:11434/api/generate")
    assert get.call_args.args[0] == "http://gpu-box:11434/api/tags"


def test_unreachable_ollama_is_none_not_empty():
    with patch.object(ollama_service.requests, "get", side_effect=requests.ConnectionError()):
        assert ollama_service.list_installed_models() is None


def test_name_built_from_display_name_is_rejected_with_installed_list():
    with patch.object(ollama_service, "list_installed_models", return_value=["llama2:7b"]):
        error = ollama_service.missing_model_error("ollama://llama-2-7b")
    assert "llama-2-7b" in error and "llama2:7b" in error


def test_installed_and_untagged_latest_models_pass():
    with patch.object(ollama_service, "list_installed_models", return_value=["llama2:7b", "mistral:latest"]):
        assert ollama_service.missing_model_error("ollama://llama2:7b") is None
        assert ollama_service.missing_model_error("ollama://mistral") is None


def test_cloud_models_and_unreachable_ollama_are_not_blocked():
    assert ollama_service.missing_model_error("api://gpt-4o") is None
    with patch.object(ollama_service, "list_installed_models", return_value=None):
        assert ollama_service.missing_model_error("ollama://anything") is None
