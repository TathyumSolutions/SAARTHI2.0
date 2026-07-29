"""Model selection helpers for global and per-step pipeline model resolution."""

from __future__ import annotations

from typing import Dict, List, Optional

from app.models.model_config import ModelConfiguration


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


def get_available_models(user_id: int = 1) -> List[Dict[str, str]]:
    rows = ModelConfiguration.query.filter_by(user_id=user_id).all()

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


def get_model_for_step(step_name: str, requested_main_model: Optional[str] = None, user_id: int = 1) -> Optional[str]:
    config = get_global_default_config(user_id=user_id)

    selected_model = requested_main_model
    if config and config.model:
        selected_model = config.model

    if config and isinstance(config.settings, dict):
        overrides = config.settings.get("step_overrides", {})
        if isinstance(overrides, dict):
            override_model = overrides.get(step_name)
            if override_model:
                return override_model

    return selected_model


def get_recommended_preset_payload(preset_key: str, user_id: int = 1) -> Dict[str, object]:
    available = get_available_models(user_id=user_id)
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
