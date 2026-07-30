"""
Validation Utilities
"""
import re
from app.utils.guardrails import is_safe_sql, sanitize_text

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validate_email(email):
    """Validate email format"""
    if not email or not isinstance(email, str):
        return False
    return bool(_EMAIL_RE.match(email.strip()))


def validate_sql(sql_query):
    """
    Validate that a SQL query is a single, read-only SELECT/WITH statement.
    Returns (is_valid, errors) where errors is a list of strings.
    """
    is_safe, reason = is_safe_sql(sql_query)
    return is_safe, ([] if is_safe else [reason])


def validate_database_config(config):
    """
    Validate database connection configuration.
    Returns (is_valid, errors) where errors is a list of strings.
    """
    errors = []
    if not isinstance(config, dict):
        return False, ["Configuration must be an object."]

    db_type = (config.get("type") or "").strip()
    if not db_type:
        errors.append("Database type is required.")

    for field in ("name", "username", "password"):
        value = config.get(field)
        if not value or (isinstance(value, str) and not value.strip()):
            errors.append(f"Missing required field: {field}")

    types_without_database_field = {"odbc", "others", "bigquery", "salesforce"}
    if db_type.lower() not in types_without_database_field:
        database = config.get("database")
        if not database or (isinstance(database, str) and not database.strip()):
            errors.append("Missing required field: database")

    port = config.get("port")
    if port is not None:
        try:
            port_int = int(port)
            if not (0 < port_int <= 65535):
                errors.append("Port must be between 1 and 65535.")
        except (TypeError, ValueError):
            errors.append("Port must be a number.")

    return (len(errors) == 0), errors


def sanitize_input(input_string):
    """Sanitize user input by stripping control characters and capping length."""
    return sanitize_text(input_string)
