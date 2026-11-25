"""
What the Ollama server actually has installed.

Used to stop a configuration being saved with a model id Ollama does not
have (e.g. "ollama://llama-2-7b", built from the display name "Llama 2 7B",
when the installed model is "llama2:7b") - such a model fails on every
question with "model not found".
"""
from __future__ import annotations

import os
from typing import List, Optional

import requests

from app.services.llm_providers import DEFAULT_OLLAMA_HOST, resolve_ollama_endpoint

_TAGS_TIMEOUT_SECONDS = 3


def _tags_url(base_url: Optional[str]) -> str:
    default_host = os.getenv("OLLAMA_HOST_URL", DEFAULT_OLLAMA_HOST)
    chat_url = resolve_ollama_endpoint(base_url, "chat", default_host=default_host)
    return chat_url[: -len("/chat")] + "/tags"


def list_installed_models(base_url: Optional[str] = None) -> Optional[List[str]]:
    """Installed model names (e.g. ["llama2:7b"]), or None if Ollama
    cannot be reached - callers must not treat "unreachable" as "empty"."""
    try:
        response = requests.get(_tags_url(base_url), timeout=_TAGS_TIMEOUT_SECONDS)
        response.raise_for_status()
        return sorted(m.get("name") for m in response.json().get("models", []) if m.get("name"))
    except (requests.RequestException, ValueError):
        return None


def is_installed(model: str, installed: List[str]) -> bool:
    """Ollama treats an untagged name as ":latest"."""
    name = str(model or "").strip()
    return name in installed or (":" not in name and f"{name}:latest" in installed)


def missing_model_error(model_id: str, base_url: Optional[str] = None) -> Optional[str]:
    """Error message if `model_id` is an ollama:// model Ollama does not
    have; None if it is installed, not an Ollama model, or Ollama is
    unreachable (saving is then allowed - it cannot be checked)."""
    value = str(model_id or "").strip()
    if not value.startswith("ollama://"):
        return None
    installed = list_installed_models(base_url)
    if installed is None:
        return None
    name = value[len("ollama://"):]
    if is_installed(name, installed):
        return None
    available = ", ".join(installed) or "none - pull one with `docker compose exec ollama ollama pull llama2:7b`"
    return f"Ollama has no model named '{name}'. Installed models: {available}."
