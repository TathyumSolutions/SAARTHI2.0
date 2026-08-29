"""Model selection helpers for global and per-step pipeline model resolution."""

from __future__ import annotations

from typing import Dict, List, Optional

from app.models.model_config import ModelConfiguration
from app.models.user_model_pipeline import UserModelPipeline
from app.services.model_registry_service import MODELS_REGISTRY


PIPELINE_STEPS = [
    {"key": "query_sense", "label": "Query Sense"},
    {"key": "query_simplifier", "label": "Query Simplifier"},
    {"key": "query_validator", "label": "Query Validator"},
    {"key": "sql_generator", "label": "SQL Generator"},
    {"key": "query_formatter", "label": "Query Formatter"},
    {"key": "data_insight_generator", "label": "Data Insight Generator"},
    {"key": "data_visualizer", "label": "Data Visualizer"},
    {"key": "error_diagnosis", "label": "Error Diagnosis"},
]

# Presets are intentionally model-agnostic selectors so owners can tune without hardcoding specific IDs.
RECOMMENDED_PRESET_DEFINITIONS = {
    "open_source": {
        "key": "open_source",
        "label": "Recommended for Open-Source Models",
        "selector": "open_source",
    },
    "paid_api": {
        "key": "paid_api",
        "label": "Recommended for Paid API LLMs",
        "selector": "paid_api",
    },
}


def _is_open_source_model(model_name: str, provider: str) -> bool:
    model = (model_name or "").lower()
    prov = (provider or "").lower()
    return (
        model.startswith("ollama://")
        or "ollama" in prov
        or any(token in model for token in ["llama", "mistral", "mixtral", "qwen", "gemma", "phi"])
    )


def _is_paid_api_model(model_name: str, provider: str) -> bool:
    model = (model_name or "").lower()
    prov = (provider or "").lower()
    return (
        model.startswith("api://")
        or any(token in prov for token in ["openai", "anthropic", "google", "deepseek", "api"])
        or any(token in model for token in ["gpt", "claude", "gemini", "deepseek"])
    )


def _row_company_code(row: ModelConfiguration) -> str:
    settings = row.settings if isinstance(row.settings, dict) else {}
    return str(settings.get("company_code") or "").strip()


def get_available_models(user_id: int = 1, company_code: Optional[str] = None) -> List[Dict[str, str]]:
    rows = ModelConfiguration.query.all()
    if company_code:
        rows = [row for row in rows if _row_company_code(row) == company_code]
    else:
        rows = [row for row in rows if row.user_id == user_id]

    seen = set()
    options: List[Dict[str, str]] = []
    for row in rows:
        if not row.model:
            continue
        key = (row.model, row.provider or "")
        if key in seen:
            continue
        seen.add(key)
        options.append(
            {
                "model": row.model,
                "provider": row.provider or "",
                "name": row.name or row.model,
            }
        )

    options.sort(key=lambda x: (x["provider"], x["model"]))
    return options


def get_global_default_config(user_id: int = 1) -> Optional[ModelConfiguration]:
    config = ModelConfiguration.query.filter_by(name="global_default", user_id=user_id).first()
    if config:
        return config
    # Fallback for legacy/global rows without scoped user ownership separation.
    return ModelConfiguration.query.filter_by(name="global_default").first()


def _bare_model_name(model_name: Optional[str]) -> str:
    """Compare UI model values with registry values without provider prefixes."""
    value = str(model_name or "").strip()
    for prefix in ("ollama://", "api://"):
        if value.startswith(prefix):
            return value[len(prefix):]
    return value


def _runtime_model_name(model_name: Optional[str]) -> Optional[str]:
    value = str(model_name or "").strip()
    if value in MODELS_REGISTRY and MODELS_REGISTRY[value].get("type") == "open_source":
        return f"ollama://{value}"
    return value or None


def get_model_for_step(step_name: str, requested_main_model: Optional[str] = None, user_id: int = 1) -> Optional[str]:
    user_pipeline = UserModelPipeline.query.filter_by(user_id=user_id).first()

    # A model selected directly in the chat bar is an explicit per-request
    # override. It takes precedence over both the saved main model and its
    # recommended per-step models.
    if (
        requested_main_model
        and user_pipeline
        and _bare_model_name(requested_main_model) != _bare_model_name(user_pipeline.main_model)
    ):
        return _runtime_model_name(requested_main_model)

    if user_pipeline:
        step_models = user_pipeline.step_models if isinstance(user_pipeline.step_models, dict) else {}
        override_model = step_models.get(step_name)
        if not override_model:
            label_by_key = {step["key"]: step["label"] for step in PIPELINE_STEPS}
            override_model = step_models.get(label_by_key.get(step_name, ""))
        if override_model:
            return _runtime_model_name(override_model)
        if user_pipeline.main_model:
            return _runtime_model_name(user_pipeline.main_model)

    config = get_global_default_config(user_id=user_id)

    selected_model = requested_main_model
    if config and config.model:
        selected_model = config.model

    if config and isinstance(config.settings, dict):
        overrides = config.settings.get("step_overrides", {})
        if isinstance(overrides, dict):
            override_model = overrides.get(step_name)
            if override_model:
                return _runtime_model_name(override_model)

    return _runtime_model_name(selected_model)


def get_recommended_preset_payload(preset_key: str, user_id: int = 1, company_code: Optional[str] = None) -> Dict[str, object]:
    available = get_available_models(user_id=user_id, company_code=company_code)
    if not available:
        return {
            "key": preset_key,
            "label": RECOMMENDED_PRESET_DEFINITIONS.get(preset_key, {}).get("label", preset_key),
            "main_model": "",
            "provider": "",
            "step_overrides": {},
            "configured": False,
            "message": "No configured models found. Add models first using existing model configuration flow.",
        }

    definition = RECOMMENDED_PRESET_DEFINITIONS.get(preset_key)
    if not definition:
        return {
            "key": preset_key,
            "label": preset_key,
            "main_model": "",
            "provider": "",
            "step_overrides": {},
            "configured": False,
            "message": "Unknown preset key",
        }

    selector = definition["selector"]
    if selector == "open_source":
        candidates = [m for m in available if _is_open_source_model(m["model"], m["provider"])]
    else:
        candidates = [m for m in available if _is_paid_api_model(m["model"], m["provider"])]

    if not candidates:
        return {
            "key": preset_key,
            "label": definition["label"],
            "main_model": "",
            "provider": "",
            "step_overrides": {},
            "configured": False,
            "message": "No matching models are currently configured for this preset.",
        }

    primary = candidates[0]
    main_model = primary["model"]
    provider = primary["provider"]

    step_overrides = {step["key"]: main_model for step in PIPELINE_STEPS}

    return {
        "key": preset_key,
        "label": definition["label"],
        "main_model": main_model,
        "provider": provider,
        "step_overrides": step_overrides,
        "configured": True,
        "message": "Preset resolved from currently configured models.",
    }
