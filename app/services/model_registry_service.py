"""
Model Registry and Recommendations Service
Contains all available models with their metadata and recommendations
"""
from typing import Dict, List, Optional

# Complete Model Registry with metadata
MODELS_REGISTRY = {
    # ============ OPEN SOURCE MODELS ============
    "llama2:7b": {
        "name": "llama2:7b",
        "type": "open_source",
        "provider": "ollama",
        "display_name": "Llama 2 7B",
        "overall_score": 0.88,
        "speed": 1.5,           # seconds per query
        "memory": 3.8,          # GB
        "quality": 0.91,        # accuracy score 0-1
        "cost_per_query": 0.0,  # $/query
        "best_for": {
            "Query Sense": 1,           # Priority 1 (highest)
            "Query Validator": 1,
            "Query Formatter": 2,       # Priority 2
            "Data Visualizer": 2
        }
    },
    
    "llama3:8b": {
        "name": "llama3:8b",
        "type": "open_source",
        "provider": "ollama",
        "display_name": "Llama 3 8B",
        "overall_score": 0.89,
        "speed": 3.5,
        "memory": 4.3,
        "quality": 0.89,
        "cost_per_query": 0.0,
        "best_for": {
            "Query Simplifier": 1,
            "Data Insight Generator": 1,
            "Error Diagnosis": 1
        }
    },
    
    "mistral:7b": {
        "name": "mistral:7b",
        "type": "open_source",
        "provider": "ollama",
        "display_name": "Mistral 7B",
        "overall_score": 0.87,
        "speed": 0.9,
        "memory": 3.8,
        "quality": 0.90,
        "cost_per_query": 0.0,
        "best_for": {
            "Query Formatter": 1,
            "Data Visualizer": 1,
            "Query Sense": 2
        }
    },
    
    "codellama:7b": {
        "name": "codellama:7b",
        "type": "open_source",
        "provider": "ollama",
        "display_name": "CodeLlama 7B",
        "overall_score": 0.86,
        "speed": 2.5,
        "memory": 3.8,
        "quality": 0.87,
        "cost_per_query": 0.0,
        "best_for": {
            "SQL Generator": 1,
            "Query Validator": 2,
            "Error Diagnosis": 2
        }
    },
    
    # ============ API-BASED MODELS - OpenAI ============
    "gpt-4o": {
        "name": "gpt-4o",
        "type": "api",
        "provider": "openai",
        "display_name": "GPT-4o",
        "overall_score": 0.95,
        "speed": 0.7,
        "memory": 0.0,
        "quality": 0.95,
        "cost_per_query": 0.015,  # Average
        "best_for": {
            "SQL Generator": 1,
            "Query Validator": 1,
            "Query Formatter": 1,
            "Error Diagnosis": 2
        }
    },
    
    "gpt-4o-mini": {
        "name": "gpt-4o-mini",
        "type": "api",
        "provider": "openai",
        "display_name": "GPT-4o Mini",
        "overall_score": 0.92,
        "speed": 0.2,
        "memory": 0.0,
        "quality": 0.92,
        "cost_per_query": 0.0008,
        "best_for": {
            "Query Sense": 1,
            "Query Formatter": 2,
            "Data Visualizer": 2
        }
    },
    
    # ============ API-BASED MODELS - Anthropic ============
    "claude-3-5-sonnet": {
        "name": "claude-3-5-sonnet",
        "type": "api",
        "provider": "anthropic",
        "display_name": "Claude 3.5 Sonnet",
        "overall_score": 0.94,
        "speed": 0.8,
        "memory": 0.0,
        "quality": 0.96,
        "cost_per_query": 0.015,  # Average
        "best_for": {
            "Query Simplifier": 1,
            "Data Insight Generator": 1,
            "Error Diagnosis": 1
        }
    },
    
    "claude-3-5-haiku": {
        "name": "claude-3-5-haiku",
        "type": "api",
        "provider": "anthropic",
        "display_name": "Claude 3.5 Haiku",
        "overall_score": 0.91,
        "speed": 0.3,
        "memory": 0.0,
        "quality": 0.90,
        "cost_per_query": 0.003,
        "best_for": {
            "Query Simplifier": 2,
            "Query Validator": 2
        }
    }
}

# Pipeline steps configuration
PIPELINE_STEPS = [
    "Query Sense",
    "Query Simplifier",
    "Query Validator",
    "SQL Generator",
    "Query Formatter",
    "Data Insight Generator",
    "Data Visualizer",
    "Error Diagnosis"
]

# Recommendation presets
PRESET_RECOMMENDATIONS = {
    "oss": {
        "Query Sense": "llama2:7b",
        "Query Simplifier": "llama3:8b",
        "Query Validator": "llama2:7b",
        "SQL Generator": "codellama:7b",
        "Query Formatter": "mistral:7b",
        "Data Insight Generator": "llama3:8b",
        "Data Visualizer": "mistral:7b",
        "Error Diagnosis": "llama3:8b"
    },
    "api": {
        "Query Sense": "gpt-4o-mini",
        "Query Simplifier": "claude-3-5-sonnet",
        "Query Validator": "gpt-4o",
        "SQL Generator": "gpt-4o",
        "Query Formatter": "gpt-4o-mini",
        "Data Insight Generator": "claude-3-5-sonnet",
        "Data Visualizer": "gpt-4o-mini",
        "Error Diagnosis": "claude-3-5-sonnet"
    },
    "hybrid": {  # Balanced option
        "Query Sense": "llama2:7b",
        "Query Simplifier": "claude-3-5-haiku",
        "Query Validator": "llama2:7b",
        "SQL Generator": "gpt-4o",
        "Query Formatter": "mistral:7b",
        "Data Insight Generator": "claude-3-5-sonnet",
        "Data Visualizer": "mistral:7b",
        "Error Diagnosis": "claude-3-5-sonnet"
    }
}


def get_all_models_sorted() -> List[Dict]:
    """
    Get all models sorted by overall score (best to least)
    """
    models = list(MODELS_REGISTRY.values())
    models.sort(key=lambda x: x['overall_score'], reverse=True)
    return models


def get_models_by_type(model_type: str) -> List[Dict]:
    """
    Get models filtered by type (oss or api)
    Returns sorted by overall_score
    """
    models = [m for m in MODELS_REGISTRY.values() if m['type'] == model_type]
    models.sort(key=lambda x: x['overall_score'], reverse=True)
    return models


def get_recommendations_for_preset(preset_type: str) -> Dict[str, str]:
    """
    Get model recommendations for a preset type (oss, api, or hybrid)
    Returns dict: {step_name -> recommended_model_name}
    """
    return PRESET_RECOMMENDATIONS.get(preset_type, PRESET_RECOMMENDATIONS.get('hybrid'))


def get_best_model_for_step(step_name: str, model_type: str) -> Optional[str]:
    """
    Get the best recommended model for a specific step and type
    """
    models = get_models_by_type(model_type)
    
    for model in models:
        if step_name in model.get('best_for', {}):
            return model['name']
    
    # Fallback to any model if no specific recommendation
    return models[0]['name'] if models else None


def get_model_info(model_name: str) -> Optional[Dict]:
    """Get metadata for a specific model"""
    return MODELS_REGISTRY.get(model_name)


def model_exists(model_name: str) -> bool:
    """Check if model exists in registry"""
    return model_name in MODELS_REGISTRY
