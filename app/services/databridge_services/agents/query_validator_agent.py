"""
QueryValidatorAgent - Self-contained agent
Validates schema references and SQL syntax
"""
import re
from typing import Dict, Any, List


def _is_function_call_from(sql_query: str, from_pos: int) -> bool:
    """
    True if the FROM keyword at from_pos is a keyword-argument separator
    inside a scalar function call (e.g. EXTRACT(MONTH FROM CURRENT_DATE),
    TRIM(chars FROM string), SUBSTRING(str FROM n)) rather than the start
    of a real table clause. Walks left from from_pos to the nearest
    unmatched '(': if a SELECT appears between that '(' and FROM, it's a
    genuine subquery table clause; otherwise it's a function argument.
    """
    depth = 0
    i = from_pos - 1
    while i >= 0:
        ch = sql_query[i]
        if ch == ")":
            depth += 1
        elif ch == "(":
            if depth == 0:
                between = sql_query[i + 1:from_pos]
                return not re.search(r"\bselect\b", between, re.IGNORECASE)
            depth -= 1
        i -= 1
    return False


def _find_invalid_qualified_columns(sql_query: str, schema_tables: Dict[str, Any]) -> List[str]:
    """
    Flags `alias.column` / `table.column` references where the column
    doesn't exist on the table they're qualified against (e.g.
    "kna1.region" when kna1 has no region column). This is a much more
    reliable signal than checking bare identifiers - a qualified
    reference unambiguously names both a table/alias and a column, so
    there's no risk of mistaking a SQL keyword or an output alias for an
    invalid column the way unqualified-token scanning would.
    """
    lower_tables = {name.lower(): name for name in schema_tables.keys()}

    # Map every alias introduced by "FROM x [AS] y" / "JOIN x [AS] y" back
    # to its real table name, so "vr.material_id" resolves via vr -> vbak_region.
    alias_to_table = {}
    for m in re.finditer(
        r"\b(?:from|join)\s+([a-zA-Z_][a-zA-Z0-9_]*)(?:\s+(?:as\s+)?([a-zA-Z_][a-zA-Z0-9_]*))?",
        sql_query, re.IGNORECASE
    ):
        table_token, alias_token = m.group(1), m.group(2)
        if table_token.lower() not in lower_tables:
            continue
        real_table = lower_tables[table_token.lower()]
        alias_to_table[table_token.lower()] = real_table
        if alias_token and alias_token.lower() not in (
            "on", "where", "and", "or", "group", "order", "limit", "inner", "left",
            "right", "outer", "join"
        ):
            alias_to_table[alias_token.lower()] = real_table

    invalid = []
    for qualifier, column in re.findall(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z_][a-zA-Z0-9_]*)\b", sql_query):
        real_table = alias_to_table.get(qualifier.lower())
        if not real_table:
            continue  # not a known table/alias - could be a schema-qualified name we don't track, don't guess
        table_columns = schema_tables[real_table].get("columns", {})
        if column.lower() not in (c.lower() for c in table_columns.keys()):
            invalid.append(f"{qualifier}.{column}")
    return invalid


# Identifiers that legitimately precede a comparison operator without being
# a column reference - SQL keywords/builtins that can sit on the left of
# =, >, LIKE, etc. in constructs this codebase's generator actually emits.
_PREDICATE_KEYWORDS = {
    "current_date", "current_timestamp", "current_time", "now", "true", "false",
    "null", "interval", "case", "when", "exists", "not", "distinct",
}


def _find_invalid_bare_predicate_columns(sql_query: str, schema_tables: Dict[str, Any]) -> List[str]:
    """
    Flags bare (unqualified) identifiers used as the left-hand side of a
    filter predicate (=, <>, >, <, LIKE, IN, IS, BETWEEN) that don't match
    any known column anywhere in the schema - e.g. "region = 'Europe'"
    inside "SELECT country FROM kna1 WHERE region = 'Europe'" when no
    table in the schema has a region column.

    Deliberately checked against the schema's full column set rather than
    scoped to the one table in play (that would need real SQL parsing) -
    still catches genuinely invented column names without false-positiving
    on legitimate columns used unqualified in a single-table query.
    """
    known_columns = set()
    known_tables = {name.lower() for name in schema_tables.keys()}
    for table_info in schema_tables.values():
        known_columns.update(c.lower() for c in table_info.get("columns", {}).keys())

    invalid = []
    for m in re.finditer(
        r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s*(?:=|<>|!=|>=|<=|<|>|\bLIKE\b|\bILIKE\b|\bIN\b|\bIS\b|\bBETWEEN\b)",
        sql_query, re.IGNORECASE
    ):
        token = m.group(1)
        low = token.lower()
        if low in known_columns or low in known_tables or low in _PREDICATE_KEYWORDS:
            continue
        invalid.append(token)
    return invalid


class QueryValidatorAgent:
    """
    Agent responsible for validation.
    Validates schema references and SQL syntax.
    """

    def __init__(self, schema: Dict[str, Any]):
        self.schema = schema
        self.state = {}

    # --------------------------
    # Schema validation
    # --------------------------
    def validate_schema(self, queriesense_output: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate tables and columns from QuerySense output against schema.
        """
        missing_tables = []
        missing_columns = []

        schema_tables = self.schema.get("tables", {})

        # --- Check tables ---
        for table in queriesense_output.get("tables", []):
            if table not in schema_tables:
                missing_tables.append(table)

        # --- Check columns ---
        for col in queriesense_output.get("columns", []):
            found = False
            for table_name, table_info in schema_tables.items():
                table_columns = table_info.get("columns", {})
                if col.lower() in (c.lower() for c in table_columns.keys()):
                    found = True
                    break
            if not found:
                missing_columns.append(col)

        # --- Build validation result ---
        if missing_tables or missing_columns:
            result = {
                "status": "failed",
                "message": "⚠️ Data Insufficient",
                "missing_tables": missing_tables,
                "missing_columns": missing_columns
            }
        else:
            result = {
                "status": "passed",
                "message": "✅ Validation successful",
                "query": queriesense_output.get("query", "")
            }

        self.state["validation_result"] = result
        return result

    # --------------------------
    # SQL validation
    # --------------------------
    def validate_generated_sql(self, sql_query: str) -> Dict[str, Any]:
        """
        Post-generation validation:
        Ensure all tables and columns in generated SQL exist in schema.
        Returns a validation result dict.
        """
        try:
            schema_tables = self.schema.get("tables", {})
            all_table_names = [t.lower() for t in schema_tables.keys()]
            all_column_names = []

            for table_info in schema_tables.values():
                all_column_names.extend([c.lower() for c in table_info.get("columns", {}).keys()])

            # Extract possible identifiers from SQL
            tokens = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", sql_query)

            used_tables = [t for t in tokens if t.lower() in all_table_names]
            used_columns = [c for c in tokens if c.lower() in all_column_names]

            # Detect invalid tables (skipping FROM used as a function
            # keyword-argument separator, e.g. EXTRACT(MONTH FROM
            # CURRENT_DATE) or TRIM(chars FROM string) - that's not a
            # table reference and shouldn't be validated as one)
            invalid_tables = [
                m.group(1)
                for m in re.finditer(r"from\s+([a-zA-Z_][a-zA-Z0-9_]*)", sql_query, re.IGNORECASE)
                if m.group(1).lower() not in all_table_names
                and not _is_function_call_from(sql_query, m.start())
            ]

            # Detect invalid columns
            invalid_columns = []
            for token in tokens:
                if (
                    token.lower() not in all_table_names
                    and token.lower() not in all_column_names
                    and token.lower() not in [
                        "select", "from", "where", "join", "on", "and", "or", "sum",
                        "count", "avg", "min", "max", "as", "group", "by", "distinct",
                        "inner", "left", "right", "outer", "order", "limit", "case",
                        "when", "then", "else", "end"
                    ]
                ):
                    invalid_columns.append(token)

            if invalid_tables:
                return {
                    "status": "failed",
                    "message": f"⚠️ Invalid tables in SQL: {', '.join(set(invalid_tables))}",
                    "invalid_tables": list(set(invalid_tables))
                }

            if not used_tables:
                return {
                    "status": "failed",
                    "message": "⚠️ No valid tables found in generated SQL."
                }

            # Qualified references (alias.column) are an unambiguous signal -
            # unlike the noisy bare-token scan below, a single invented
            # qualified column (e.g. a hallucinated "kna1.region") is enough
            # to fail validation outright, rather than only tripping on
            # implausibly large amounts of garbage.
            invalid_predicate_cols = set(_find_invalid_qualified_columns(sql_query, schema_tables))
            invalid_predicate_cols.update(_find_invalid_bare_predicate_columns(sql_query, schema_tables))
            if invalid_predicate_cols:
                return {
                    "status": "failed",
                    "message": f"⚠️ Invalid columns in SQL: {', '.join(sorted(invalid_predicate_cols))}",
                    "invalid_columns": sorted(invalid_predicate_cols)
                }

            if invalid_columns and len(invalid_columns) > len(all_table_names) + len(all_column_names) + 10:
                return {
                    "status": "failed",
                    "message": f"⚠️ SQL may contain invalid identifiers: {', '.join(invalid_columns[:5])}"
                }

            return {"status": "passed", "message": "✅ Generated SQL validated successfully."}

        except Exception as e:
            return {"status": "failed", "message": f"❌ SQL validation error: {str(e)}"}

    # --------------------------
    # Execute agent
    # --------------------------
    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the agent: validate schema references or SQL.
        """
        print(f"\n🤖 [QueryValidatorAgent] Starting...")
        if "steps" not in state or state["steps"] is None:
            state["steps"] = []

        if state.get("generated_sql"):
            validation = self.validate_generated_sql(state["generated_sql"])
            state["sql_validation"] = validation
            if validation.get("status") != "passed":
                state["retry_count"] = state.get("retry_count", 0) + 1
            state["steps"].append(
                f"SQL Schema Validation: {validation.get('status').upper()}. Verified that the generated query matches the database structure."
            )    
            print(f"✅ [QueryValidatorAgent] SQL validation: {validation.get('status')}")
        else:
            query_sense_output = state.get("query_sense_output", {})
            validation = self.validate_schema(query_sense_output)
            state["validation_result"] = validation
            state["steps"].append(
                f"Initial Schema Validation: {validation.get('status').upper()}. Confirmed all identified tables and columns exist in the system."
            )
            print(f"✅ [QueryValidatorAgent] Schema validation: {validation.get('status')}")
        query_sense_output = state.get("query_sense_output", {})
        query_sense_output["steps"] = state["steps"]
        state["query_sense_output"] = query_sense_output

        state["current_step"] = "query_validator"
        return state
