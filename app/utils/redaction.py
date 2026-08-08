"""
Masks credential-looking values before text that may contain them - an API
tool's endpoint or description, most often - is shown to a user or handed
to a third-party LLM. Registered API tools are free text entered by users,
who sometimes paste a full request URL (api_key and all) into a field meant
for a human-readable description, so anywhere that field gets echoed back
needs to assume it might contain a live secret.
"""
import re

_SECRET_QUERY_PARAM_RE = re.compile(
    r"(?i)([?&](?:api[_-]?key|apikey|access[_-]?token|token|secret|password|auth|authorization)=)[^&\s]+"
)


def redact_secrets(text):
    """Masks api_key=/token=/secret=/password=/auth= query-string values in text."""
    if not text:
        return text
    return _SECRET_QUERY_PARAM_RE.sub(r"\1***REDACTED***", text)
