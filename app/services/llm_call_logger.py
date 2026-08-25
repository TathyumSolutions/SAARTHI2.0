"""
Central instrumentation for every LLM call in Saarthi - LangChain-backed
calls (OpenAI/Anthropic/Gemini/DeepSeek via ChatOpenAI/ChatAnthropic/etc.)
and raw Ollama HTTP calls alike are recorded into LLMCallLog so the
"LLM Calls" page (app/templates/llm_calls.html) can show a user-readable
log with per-call token counts and cost, grouped by "purpose" (the page's
sub-menus).

Entirely settings-driven via the `llm_logging` block in rag_config.yaml
(Settings > LLM Call Logging): flip `enabled: false` there and every
function below becomes a no-op immediately, with the DB never touched.
A logging failure (bad DB state, config typo, etc.) must never break the
actual LLM-backed feature riding alongside it, so every write here is
best-effort and swallows its own exceptions.
"""
import time
from contextlib import contextmanager

from app import db
from app.models.llm_call_log import LLMCallLog
from app.utils.llm_call_codes import generate_call_code
from .rag_config import load_rag_config


def _logging_config():
    return load_rag_config().get("llm_logging", {}) or {}


def is_logging_enabled() -> bool:
    return bool(_logging_config().get("enabled", True))


def _pricing_for(model_name):
    pricing = _logging_config().get("pricing", {}) or {}
    if not model_name:
        return pricing.get("default", {})
    if model_name in pricing:
        return pricing[model_name]
    lower = str(model_name).lower()
    for key, rates in pricing.items():
        if key != "default" and key.lower() in lower:
            return rates
    return pricing.get("default", {})


def compute_cost(model_name, prompt_tokens, completion_tokens):
    """USD cost for a call, from the settings-driven pricing table.
    Unknown models (including anything Ollama/local) fall back to the
    "default" pricing entry, which is 0 unless changed in Settings."""
    rates = _pricing_for(model_name)
    input_rate = float(rates.get("input_per_1k", 0) or 0)
    output_rate = float(rates.get("output_per_1k", 0) or 0)
    prompt_tokens = prompt_tokens or 0
    completion_tokens = completion_tokens or 0
    return round((prompt_tokens / 1000.0) * input_rate + (completion_tokens / 1000.0) * output_rate, 6)


def _truncate(text, limit):
    if text is None:
        return None
    text = str(text)
    return text if len(text) <= limit else text[:limit] + "... [truncated]"


def _messages_to_text(messages):
    """Best-effort flattening of a LangChain message list (or a plain
    string prompt) into readable text for the prompt preview column."""
    if messages is None:
        return None
    if isinstance(messages, str):
        return messages
    try:
        parts = []
        for m in messages:
            content = getattr(m, "content", m)
            role = getattr(m, "type", None) or m.__class__.__name__
            parts.append(f"[{role}] {content}")
        return "\n\n".join(parts)
    except TypeError:
        return str(messages)


def record_llm_call(*, purpose, model_name, provider=None, prompt_text=None, response_text=None,
                     prompt_tokens=None, completion_tokens=None, total_tokens=None,
                     duration_ms=None, status="success", error_message=None,
                     user_id=None, company_code=None, session_id=None, query_code=None):
    """Writes one LLMCallLog row. Never raises."""
    cfg = _logging_config()
    if not cfg.get("enabled", True):
        return None
    try:
        if total_tokens is None and (prompt_tokens is not None or completion_tokens is not None):
            total_tokens = (prompt_tokens or 0) + (completion_tokens or 0)
        cost = compute_cost(model_name, prompt_tokens, completion_tokens) if status == "success" else 0.0

        preview_limit = int(cfg.get("preview_max_chars", 2000) or 2000)
        log_prompts = cfg.get("log_prompts", True)

        entry = LLMCallLog(
            call_code=generate_call_code(),
            user_id=user_id,
            company_code=company_code,
            session_id=str(session_id) if session_id is not None else None,
            query_code=query_code,
            purpose=purpose,
            provider=provider,
            model=str(model_name) if model_name else "unknown",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost=cost,
            duration_ms=duration_ms,
            status=status,
            error_message=_truncate(error_message, 1000),
            prompt_preview=_truncate(prompt_text, preview_limit) if log_prompts else None,
            response_preview=_truncate(response_text, preview_limit) if log_prompts else None,
        )
        db.session.add(entry)
        db.session.commit()
        return entry
    except Exception as e:
        print(f"⚠️ [LLM-LOG] Failed to record LLM call log: {e}")
        try:
            db.session.rollback()
        except Exception:
            pass
        return None


def tracked_invoke(llm, messages, *, purpose, model_name, provider=None, **ctx):
    """Drop-in replacement for `llm.invoke(messages)` on any LangChain chat
    model - times the call, pulls token usage from the response's
    `usage_metadata` (populated by LangChain for OpenAI/Anthropic/Gemini
    chat models), logs it, and returns the response unchanged. Re-raises
    on failure after logging the error, so callers keep their existing
    try/except behavior."""
    start = time.monotonic()
    prompt_text = _messages_to_text(messages)
    try:
        response = llm.invoke(messages)
    except Exception as e:
        record_llm_call(
            purpose=purpose, model_name=model_name, provider=provider,
            prompt_text=prompt_text, duration_ms=int((time.monotonic() - start) * 1000),
            status="error", error_message=str(e), **ctx,
        )
        raise

    duration_ms = int((time.monotonic() - start) * 1000)
    usage = getattr(response, "usage_metadata", None) or {}
    prompt_tokens = usage.get("input_tokens")
    completion_tokens = usage.get("output_tokens")
    total_tokens = usage.get("total_tokens")
    response_text = getattr(response, "content", None)

    record_llm_call(
        purpose=purpose, model_name=model_name, provider=provider,
        prompt_text=prompt_text, response_text=response_text,
        prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
        total_tokens=total_tokens, duration_ms=duration_ms, status="success", **ctx,
    )
    return response


def record_ollama_call(*, purpose, model_name, prompt_text, response_json, duration_ms, **ctx):
    """Logs a raw (non-LangChain) Ollama /api/generate call. Ollama's JSON
    response includes prompt_eval_count/eval_count (input/output token
    counts) whenever the request was made with stream=False."""
    response_json = response_json or {}
    record_llm_call(
        purpose=purpose, model_name=model_name, provider="ollama",
        prompt_text=prompt_text, response_text=response_json.get("response"),
        prompt_tokens=response_json.get("prompt_eval_count"),
        completion_tokens=response_json.get("eval_count"),
        duration_ms=duration_ms, status="success", **ctx,
    )


@contextmanager
def track_ollama_call(*, purpose, model_name, prompt_text, **ctx):
    """Context manager wrapping a raw Ollama request when the call site's
    control flow makes a plain before/after `record_ollama_call` awkward
    (e.g. the response is used well after being received). Usage:

        with track_ollama_call(purpose="x", model_name=m, prompt_text=p) as log:
            resp = requests.post(url, json=payload, timeout=60)
            resp.raise_for_status()
            log["response_json"] = resp.json()
            answer = log["response_json"].get("response", "")

    Logs an error row (status="error") if the block raises, and a success
    row from `log["response_json"]` otherwise. Never re-raises anything of
    its own - the caller's exception (if any) propagates untouched.
    """
    start = time.monotonic()
    state = {"response_json": None}
    try:
        yield state
    except Exception as e:
        record_llm_call(
            purpose=purpose, model_name=model_name, provider="ollama",
            prompt_text=prompt_text, duration_ms=int((time.monotonic() - start) * 1000),
            status="error", error_message=str(e), **ctx,
        )
        raise
    else:
        record_ollama_call(
            purpose=purpose, model_name=model_name, prompt_text=prompt_text,
            response_json=state.get("response_json"),
            duration_ms=int((time.monotonic() - start) * 1000), **ctx,
        )
