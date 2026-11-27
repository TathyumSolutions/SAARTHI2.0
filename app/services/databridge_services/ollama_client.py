"""Shared settings and request helper for the data-bridge agents' local
Ollama (`ollama://<model>`) calls.

Each agent used to build its own /api/generate payload, and most of them
left out `num_ctx`. Ollama then used its default context window and quietly
dropped the start of any prompt longer than that. For QuerySense that start
holds the output-format rules, so a small model like Llama 2 7B saw only the
schema and the question and answered with made-up data rows instead of a
query plan. Timeouts were also set per call (120s for QuerySimplifier), so
a model still loading after a cold start timed out.

All values can be overridden through environment variables, so a larger
local model can be given a bigger window without code changes:

    OLLAMA_NUM_CTX              context window in tokens (default 4096,
                                Llama 2's maximum; Llama 3.1 / Qwen 2.5
                                accept 8192 and more)
    OLLAMA_REQUEST_TIMEOUT      seconds to wait for one request (default 600)
    OLLAMA_SCHEMA_MAX_TABLES    how many of the most relevant tables
                                QuerySense sends to a local model (default 6)
"""
import os
import time
from typing import Any, Dict, Optional, Tuple, Union

import requests

from app.services.llm_call_logger import record_llm_call


def _env_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, ""))
        return value if value > 0 else default
    except ValueError:
        return default


OLLAMA_NUM_CTX = _env_int("OLLAMA_NUM_CTX", 4096)
OLLAMA_REQUEST_TIMEOUT = _env_int("OLLAMA_REQUEST_TIMEOUT", 600)
OLLAMA_SCHEMA_MAX_TABLES = _env_int("OLLAMA_SCHEMA_MAX_TABLES", 6)


def ollama_options(temperature: float = 0.0) -> Dict[str, Any]:
    """The `options` block every data-bridge Ollama request should send."""
    return {"temperature": temperature, "num_ctx": OLLAMA_NUM_CTX}


def ollama_generate(
    url: str,
    model: str,
    prompt: str,
    *,
    purpose: str,
    temperature: float = 0.0,
    response_format: Optional[Union[str, Dict[str, Any]]] = None,
    user_id=None,
) -> Tuple[str, Dict[str, Any]]:
    """POSTs a non-streaming /api/generate request and returns
    (response_text, response_json). The call is logged through
    record_llm_call.

    response_format may be "json" or a JSON Schema dict (Ollama structured
    outputs, Ollama 0.5+). If the server rejects a schema with HTTP 400,
    which older Ollama versions do, the request is sent again with
    "json" so the caller still gets JSON back.
    """
    payload: Dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": ollama_options(temperature),
    }
    if response_format is not None:
        payload["format"] = response_format

    start = time.monotonic()
    resp = requests.post(url, json=payload, timeout=OLLAMA_REQUEST_TIMEOUT)
    if resp.status_code == 400 and isinstance(response_format, dict):
        print(f"⚠️ [Ollama] Server rejected a JSON-schema format for {purpose}; retrying with format='json'")
        payload["format"] = "json"
        resp = requests.post(url, json=payload, timeout=OLLAMA_REQUEST_TIMEOUT)
    resp.raise_for_status()

    resp_json = resp.json()
    text = (resp_json.get("response") or "").strip()
    record_llm_call(
        purpose=purpose, model_name=model, provider="ollama",
        prompt_text=prompt, response_text=text,
        prompt_tokens=resp_json.get("prompt_eval_count"),
        completion_tokens=resp_json.get("eval_count"),
        duration_ms=int((time.monotonic() - start) * 1000), user_id=user_id,
    )
    return text, resp_json
