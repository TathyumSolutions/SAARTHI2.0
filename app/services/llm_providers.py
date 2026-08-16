"""Shared resolver for the `api://<provider>/<model>` dynamic LLM syntax.

This block (match on "claude"/"gemini"/"deepseek"/else-openai in the model
id, build the matching LangChain chat model) was copy-pasted independently
across llm_service.py, spreadsheet_query_service.py, and every agent under
databridge_services/agents/. Centralizing it here removes that duplication
without changing any call site's behavior - each caller keeps its own
temperature, key-fallback, and unrecognized-provider handling by passing
those in explicitly.
"""
import os


def resolve_dynamic_llm(actual_model: str, custom_key: str, temperature: float = 0,
                         openai_fallback_key: str = None, strict: bool = True):
    """Builds a LangChain chat model for an `api://` model id with the
    prefix already stripped and lowercased by the caller.

    strict=True raises ValueError for a model id matching none of the known
    provider keywords (claude/gemini/deepseek/gpt/openai) - this is what
    every call site except spreadsheet_query_service does today.
    strict=False instead falls back to ChatOpenAI(model=actual_model, ...),
    matching spreadsheet_query_service._invoke_llm's existing behavior.
    """
    if "claude" in actual_model:
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=actual_model,
            temperature=temperature,
            anthropic_api_key=custom_key if custom_key else os.getenv("ANTHROPIC_API_KEY"),
        )

    if "gemini" in actual_model:
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=actual_model,
            temperature=temperature,
            google_api_key=custom_key if custom_key else os.getenv("GOOGLE_API_KEY"),
        )

    if "deepseek" in actual_model:
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=actual_model,
            temperature=temperature,
            openai_api_key=custom_key if custom_key else os.getenv("DEEPSEEK_API_KEY"),
            openai_api_base="https://api.deepseek.com/v1",
        )

    if strict:
        if "gpt" in actual_model or "openai" in actual_model:
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model=actual_model,
                temperature=temperature,
                openai_api_key=custom_key if custom_key else openai_fallback_key,
            )
        raise ValueError(
            f"Custom cloud provider mapping failed: Identifier '{actual_model}' "
            f"does not match any recognized provider keyword (claude, gemini, deepseek, gpt)."
        )

    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model=actual_model,
        temperature=temperature,
        openai_api_key=custom_key if custom_key else openai_fallback_key,
    )
