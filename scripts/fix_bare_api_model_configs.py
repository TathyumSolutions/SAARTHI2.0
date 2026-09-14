"""
One-time repair for ModelConfiguration rows saved with a bare provider-family
name instead of a real model id (e.g. model="api://gpt" instead of
"api://gpt-4o").

Before this fix, "AI & Models > Configure New Model" (saveModel() in
app/templates/index.html, POST /api/model-config/configurations) accepted
any free-text Model Name and slugified it into "api://<slug>" with no
validation. Typing "GPT" (rather than "GPT-4o") produced "api://gpt", which
resolve_dynamic_llm() (app/services/llm_providers.py) happily routes to
ChatOpenAI(model="gpt") - a model id OpenAI's API rejects with a 404 on
every single call. app/routes/model_config_routes.py now rejects these
bare names at save time via validate_dynamic_model_id(), but rows written
before that fix are still broken and need remapping once, here.

Every ModelConfiguration.model (and any ModelConfiguration.settings.
step_overrides value) that is "api://<bare provider family name>" is
remapped to that provider's default real model id. UserModelPipeline rows
are not touched: their main_model/step_models values are validated against
MODELS_REGISTRY (app/services/model_registry_service.py), whose keys are
never bare (e.g. "gpt-4o", not "gpt"), so they can't hold this class of bug.

Safe to re-run: rows that don't match a bare name are left untouched.

Usage:
    python scripts/fix_bare_api_model_configs.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models.model_config import ModelConfiguration

# provider-family name (after "api://") -> real default model id to remap to.
_DEFAULT_MODEL_FOR_BARE_NAME = {
    "gpt": "gpt-4o",
    "openai": "gpt-4o",
    "claude": "claude-3-5-sonnet",
    "anthropic": "claude-3-5-sonnet",
    "gemini": "gemini-1.5-pro",
    "google": "gemini-1.5-pro",
    "deepseek": "deepseek-chat",
}


def _remapped_model(model_value):
    """New "api://<real-model>" string if `model_value` is a bare
    provider-family name, else None."""
    value = str(model_value or "").strip()
    if not value.startswith("api://"):
        return None
    bare = value[len("api://"):].strip().lower()
    replacement = _DEFAULT_MODEL_FOR_BARE_NAME.get(bare)
    return f"api://{replacement}" if replacement else None


def fix():
    rows_fixed = 0
    overrides_fixed = 0

    for config in ModelConfiguration.query.all():
        changed = False

        new_model = _remapped_model(config.model)
        if new_model:
            print(f"  ModelConfiguration id={config.id} name={config.name!r}: "
                  f"{config.model!r} -> {new_model!r}")
            config.model = new_model
            changed = True

        settings = config.settings if isinstance(config.settings, dict) else None
        overrides = settings.get("step_overrides") if settings else None
        if isinstance(overrides, dict):
            for step, override_model in list(overrides.items()):
                new_override = _remapped_model(override_model)
                if new_override:
                    print(f"  ModelConfiguration id={config.id} step_overrides[{step!r}]: "
                          f"{override_model!r} -> {new_override!r}")
                    overrides[step] = new_override
                    overrides_fixed += 1
                    changed = True
            if overrides_fixed:
                # JSON column: reassign so SQLAlchemy detects the in-place mutation.
                config.settings = {**settings, "step_overrides": overrides}

        if changed:
            rows_fixed += 1
            db.session.add(config)

    if rows_fixed:
        db.session.commit()

    print(f"Fix complete: {rows_fixed} ModelConfiguration row(s) updated, "
          f"{overrides_fixed} step_overrides entr{'y' if overrides_fixed == 1 else 'ies'} remapped.")


if __name__ == "__main__":
    app = create_app(os.getenv("FLASK_ENV", "development"))
    with app.app_context():
        fix()
