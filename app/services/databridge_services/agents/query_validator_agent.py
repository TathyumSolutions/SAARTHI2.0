"""
QueryValidatorAgent - Self-contained agent
Validates schema references and SQL syntax
"""
import re
from typing import Dict, Any, List

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

            # Detect invalid tables
            invalid_tables = [
                t for t in re.findall(r"from\s+([a-zA-Z_][a-zA-Z0-9_]*)", sql_query, re.IGNORECASE)
                if t.lower() not in all_table_names
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
