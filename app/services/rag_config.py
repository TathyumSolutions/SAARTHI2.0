import os
from typing import Any, Dict

import yaml


def load_rag_config() -> Dict[str, Any]:
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rag_config.yaml")
    with open(config_path, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def get_rag_setting(path: str, default: Any = None) -> Any:
    config = load_rag_config()
    value: Any = config
    for part in path.split("."):
        if isinstance(value, dict) and part in value:
            value = value[part]
        else:
            return default
    return value
