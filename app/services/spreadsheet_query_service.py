"""
Answers questions against Excel/CSV-derived tables (spreadsheet_service.py)
- pandas DataFrames loaded from Parquet, never SQL, never a database.

Deliberately does NOT let the LLM write arbitrary pandas/Python code and
exec() it - that would reopen exactly the class of arbitrary-code-execution
risk the SQL guardrails (query_formatter_agent.py) were built to close off,
just moved to Python instead of SQL. Instead, the LLM produces a small,
strictly-validated JSON "query plan" - which table(s), what to filter, how
to join, how to group/aggregate - and a fixed, hand-written function
(_execute_plan) is the only thing that ever calls pandas. The LLM chooses
*what* to do; it never supplies *code* to run.
"""
import os
import re
import json
import time

import pandas as pd

from app.services.stream_manager import stream_manager
from app.services import spreadsheet_service
from app.models.model_config import ModelConfiguration

ALLOWED_FILTER_OPS = {"==", "!=", ">", "<", ">=", "<=", "in", "contains"}
ALLOWED_AGG_FUNCS = {"sum", "mean", "count", "min", "max", "median", "nunique"}
ALLOWED_JOIN_HOW = {"inner", "left", "right", "outer"}
MAX_ROW_LIMIT = 5000
DEFAULT_ROW_LIMIT = 500


class PlanValidationError(Exception):
    """Raised when the LLM's query plan references a table/column that
    doesn't exist, or uses an operation outside the allowed set. Always
    caught - never lets an invalid plan reach the executor."""


# Phrases that mean the user is asking about a table itself (what it is,
# what's in it) rather than asking a question that needs filtering/
# aggregating its rows. These go straight to the manifest metadata -
# "table"/"sheet"/"description"/"row_count"/"columns", i.e. the same
# meta-summary written to spreadsheet_metadata.json when the file was
# uploaded and summarized - instead of forcing the LLM to build a query
# plan against a question that isn't really a data query.
METADATA_QUESTION_PATTERNS = (
    "what do you know about", "what do you know regarding",
    "tell me about", "tell me more about",
    "describe", "give me an overview of", "overview of",
    "summary of", "summarize", "what is in", "what's in",
    "information about", "info about", "details about",
    "what data is in", "what columns are in", "what does",
)


def _find_metadata_match(user_query: str, available_tables: dict):
    """Returns the (table_name, info) pair the question is asking about,
    if this looks like a "what do you know about <upload>" question rather
    than a filter/aggregate question. None otherwise."""
    query_lower = (user_query or "").lower()
    if not any(pattern in query_lower for pattern in METADATA_QUESTION_PATTERNS):
        return None

    for table_name, info in available_tables.items():
        candidates = [table_name, info.get("sheet") or ""]
        for candidate in candidates:
            normalized = candidate.lower().replace("_", " ").strip()
            if normalized and normalized in query_lower:
                return table_name, info
    return None


def _build_metadata_answer(table_name: str, info: dict) -> str:
    """An analyst-style, to-the-point summary of an uploaded spreadsheet
    table, grounded in the metadata captured at upload time (description,
    columns, row count) - not invented by the LLM."""
    description = (info.get("description") or "").strip()
    columns = [c["name"] for c in info.get("columns", [])]
    row_count = info.get("row_count", 0)

    column_preview = ", ".join(columns[:6])
    if len(columns) > 6:
        column_preview += f", and {len(columns) - 6} more"

    lines = [f"**{table_name}** - {row_count:,} row(s), {len(columns)} column(s)."]
    if description:
        lines.append(description)
    if column_preview:
        lines.append(f"Columns: {column_preview}.")
    lines.append("Want more detail - e.g. sample rows, or a breakdown by a specific column?")
    return "\n".join(lines)


def _invoke_llm(model_name: str, custom_key: str, system_content: str, user_content: str) -> str:
    """Same multi-provider dispatch pattern used throughout the other
    tracks (general_service.py, llm_service.py) - kept local to this file
    rather than shared, to avoid touching those modules for this feature."""
    from langchain_core.messages import SystemMessage, HumanMessage

    messages = [SystemMessage(content=system_content), HumanMessage(content=user_content)]

    cfg = ModelConfiguration.query.filter_by(model=model_name).order_by(ModelConfiguration.id.desc()).first()
    cfg_settings = cfg.settings if cfg and isinstance(cfg.settings, dict) else {}
    model_base_url = cfg_settings.get("base_url") or ""
    if not custom_key and cfg_settings.get("custom_key"):
        custom_key = cfg_settings.get("custom_key")

    if model_name in ("gpt-4o", "gpt-4o-mini"):
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(model=model_name, temperature=0, openai_api_key=custom_key or os.getenv("OPENAI_API_KEY"))
        return llm.invoke(messages).content

    if str(model_name).startswith("api://"):
        actual_model = model_name.replace("api://", "").lower()
        if model_base_url:
            from langchain_openai import ChatOpenAI
            llm = ChatOpenAI(
                model=actual_model,
                temperature=0,
                openai_api_key=custom_key or os.getenv("OPENAI_API_KEY", "placeholder-key"),
                openai_api_base=model_base_url,
            )
        elif "claude" in actual_model:
            from langchain_anthropic import ChatAnthropic
            llm = ChatAnthropic(model=actual_model, temperature=0, anthropic_api_key=custom_key or os.getenv("ANTHROPIC_API_KEY"))
        elif "gemini" in actual_model:
            from langchain_google_genai import ChatGoogleGenerativeAI
            llm = ChatGoogleGenerativeAI(model=actual_model, temperature=0, google_api_key=custom_key or os.getenv("GOOGLE_API_KEY"))
        elif "deepseek" in actual_model:
            from langchain_openai import ChatOpenAI
            llm = ChatOpenAI(model=actual_model, temperature=0, openai_api_key=custom_key or os.getenv("DEEPSEEK_API_KEY"), openai_api_base="https://api.deepseek.com/v1")
        else:
            from langchain_openai import ChatOpenAI
            llm = ChatOpenAI(model=actual_model, temperature=0, openai_api_key=custom_key or os.getenv("OPENAI_API_KEY"))
        return llm.invoke(messages).content

    if str(model_name).startswith("ollama://") or model_name == "llama3":
        import requests
        actual_model = model_name.replace("ollama://", "") if str(model_name).startswith("ollama://") else "llama3"
        prompt = f"{system_content}\n\n{user_content}"
        ollama_url = model_base_url or "http://ollama:11434/api/generate"
        response = requests.post(
            ollama_url,
            json={"model": actual_model, "prompt": prompt, "stream": False, "options": {"temperature": 0}},
            timeout=120,
        )
        response.raise_for_status()
        return response.json().get("response", "")

    # Fallback: try OpenAI with whatever key is configured, same default
    # used elsewhere in the codebase when a model name doesn't match a
    # known pattern.
    from langchain_openai import ChatOpenAI
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, openai_api_key=custom_key or os.getenv("OPENAI_API_KEY"))
    return llm.invoke(messages).content


def _extract_json(text: str) -> dict:
    text = (text or "").strip()
    text = re.sub(r"^```(json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        raise PlanValidationError("The model did not return a query plan.")
    return json.loads(match.group(0))


def _build_plan_prompt(available_tables: dict) -> str:
    tables_desc = []
    for table_name, info in available_tables.items():
        cols = ", ".join(f"{c['name']} ({c['type']})" for c in info.get("columns", []))
        tables_desc.append(f"- {table_name}: {info.get('description', '')}\n  columns: {cols}")
    tables_block = "\n".join(tables_desc) if tables_desc else "(no tables available)"

    return f"""You turn a business question into a strict JSON query plan
against spreadsheet-derived tables. You never write code - only this JSON.

AVAILABLE TABLES:
{tables_block}

Return ONLY a JSON object with this shape (omit fields you don't need,
but "tables" is always required):
{{
  "tables": ["table_a"],
  "join": null or {{"left_table": "table_a", "right_table": "table_b", "left_on": "col", "right_on": "col", "how": "inner"}},
  "filters": [{{"table": "table_a", "column": "col", "op": "==", "value": "West"}}],
  "group_by": ["col1"],
  "aggregations": [{{"column": "col2", "func": "sum", "as": "total_col2"}}],
  "select_columns": ["col1", "col2"],
  "sort_by": {{"column": "total_col2", "ascending": false}},
  "limit": 100
}}

Rules:
- Only reference tables and columns listed above under AVAILABLE TABLES - never invent one.
- "op" must be one of: == != > < >= <= in contains
- "func" must be one of: sum mean count min max median nunique
- "how" must be one of: inner left right outer
- Use "join" only when the question needs data from two tables together.
- If the question doesn't need grouping/aggregation, omit those fields and use "select_columns" instead.
- Output ONLY the JSON object, nothing else.
"""


def _validate_plan(plan: dict, available_tables: dict) -> dict:
    if not isinstance(plan, dict):
        raise PlanValidationError("Query plan was not a JSON object.")

    tables = plan.get("tables")
    if not tables or not isinstance(tables, list):
        raise PlanValidationError("Query plan did not name any tables.")
    for t in tables:
        if t not in available_tables:
            raise PlanValidationError(f"Unknown table '{t}'.")

    def _known_columns(table_name):
        return {c["name"] for c in available_tables[table_name].get("columns", [])}

    all_columns = set()
    for t in tables:
        all_columns |= _known_columns(t)

    join = plan.get("join")
    if join:
        if join.get("left_table") not in tables or join.get("right_table") not in tables:
            raise PlanValidationError("Join references a table not in 'tables'.")
        if join.get("left_on") not in _known_columns(join["left_table"]):
            raise PlanValidationError(f"Join column '{join.get('left_on')}' not found in {join['left_table']}.")
        if join.get("right_on") not in _known_columns(join["right_table"]):
            raise PlanValidationError(f"Join column '{join.get('right_on')}' not found in {join['right_table']}.")
        how = join.get("how", "inner")
        if how not in ALLOWED_JOIN_HOW:
            raise PlanValidationError(f"Join type '{how}' is not allowed.")
        join["how"] = how

    for f in plan.get("filters") or []:
        if f.get("table") not in tables:
            raise PlanValidationError(f"Filter references table '{f.get('table')}' not in 'tables'.")
        if f.get("column") not in _known_columns(f["table"]):
            raise PlanValidationError(f"Filter column '{f.get('column')}' not found in {f['table']}.")
        if f.get("op") not in ALLOWED_FILTER_OPS:
            raise PlanValidationError(f"Filter operator '{f.get('op')}' is not allowed.")

    for g in plan.get("group_by") or []:
        if g not in all_columns:
            raise PlanValidationError(f"Group-by column '{g}' not found in the selected tables.")

    for agg in plan.get("aggregations") or []:
        if agg.get("column") not in all_columns:
            raise PlanValidationError(f"Aggregation column '{agg.get('column')}' not found.")
        if agg.get("func") not in ALLOWED_AGG_FUNCS:
            raise PlanValidationError(f"Aggregation function '{agg.get('func')}' is not allowed.")

    for c in plan.get("select_columns") or []:
        if c not in all_columns:
            raise PlanValidationError(f"Selected column '{c}' not found.")

    sort_by = plan.get("sort_by")
    if sort_by and sort_by.get("column") not in all_columns and sort_by.get("column") not in {
        agg.get("as") or f"{agg.get('column')}_{agg.get('func')}" for agg in (plan.get("aggregations") or [])
    }:
        raise PlanValidationError(f"Sort column '{sort_by.get('column')}' not found.")

    try:
        plan["limit"] = min(int(plan.get("limit") or DEFAULT_ROW_LIMIT), MAX_ROW_LIMIT)
    except (TypeError, ValueError):
        plan["limit"] = DEFAULT_ROW_LIMIT

    return plan


def _apply_filter(df: pd.DataFrame, column: str, op: str, value) -> pd.DataFrame:
    series = df[column]
    if op == "==":
        return df[series == value]
    if op == "!=":
        return df[series != value]
    if op == ">":
        return df[series > value]
    if op == "<":
        return df[series < value]
    if op == ">=":
        return df[series >= value]
    if op == "<=":
        return df[series <= value]
    if op == "in":
        values = value if isinstance(value, list) else [value]
        return df[series.isin(values)]
    if op == "contains":
        return df[series.astype(str).str.contains(str(value), case=False, na=False)]
    raise PlanValidationError(f"Unsupported filter operator '{op}'.")


def _execute_plan(plan: dict) -> pd.DataFrame:
    """The only function that ever touches pandas for this feature - every
    value it uses came from a plan that already passed _validate_plan."""
    tables = plan["tables"]
    frames = {t: spreadsheet_service.get_table_df(t) for t in tables}

    join = plan.get("join")
    if join:
        left = frames[join["left_table"]]
        right = frames[join["right_table"]]
        df = pd.merge(
            left, right,
            left_on=join["left_on"], right_on=join["right_on"],
            how=join["how"], suffixes=("", "_2")
        )
    else:
        df = frames[tables[0]]

    for f in plan.get("filters") or []:
        if f["column"] in df.columns:
            df = _apply_filter(df, f["column"], f["op"], f.get("value"))

    group_by = [g for g in (plan.get("group_by") or []) if g in df.columns]
    aggregations = plan.get("aggregations") or []
    if group_by and aggregations:
        agg_map = {}
        rename_map = {}
        for agg in aggregations:
            col = agg["column"]
            if col not in df.columns:
                continue
            agg_map[col] = agg["func"]
            rename_map[col] = agg.get("as") or f"{col}_{agg['func']}"
        df = df.groupby(group_by, as_index=False).agg(agg_map)
        df = df.rename(columns=rename_map)
    elif aggregations:
        # No group-by: a single aggregate row.
        result = {}
        for agg in aggregations:
            col = agg["column"]
            if col not in df.columns:
                continue
            result[agg.get("as") or f"{col}_{agg['func']}"] = [getattr(df[col], agg["func"])()]
        df = pd.DataFrame(result)
    else:
        select_columns = [c for c in (plan.get("select_columns") or []) if c in df.columns]
        if select_columns:
            df = df[select_columns]

    sort_by = plan.get("sort_by")
    if sort_by and sort_by.get("column") in df.columns:
        df = df.sort_values(by=sort_by["column"], ascending=bool(sort_by.get("ascending", True)))

    limit = plan.get("limit", DEFAULT_ROW_LIMIT)
    return df.head(limit)


def answer_from_spreadsheets(
    user_query: str,
    model_name: str,
    custom_key: str = "",
    system_instructions: str = "",
    session_id: str = "1",
) -> dict:
    session_id = str(session_id)
    master_steps = []

    def push_event(event_type, title, description):
        payload = {"event": event_type, "title": title, "description": description, "is_sql": False}
        if event_type == "start":
            master_steps.append(f"{title} - {description}")
        stream_manager.push_step(session_id, payload, is_sql=False)
        time.sleep(0.2)

    try:
        push_event("start", "Matching the Right Data Source", "Checking which uploaded spreadsheets are relevant.")
        available_tables = {t["table"]: t for t in spreadsheet_service.list_all_tables()}
        if not available_tables:
            push_event("complete", "Matching the Right Data Source", "No spreadsheet tables are available.")
            stream_manager.push_step(session_id, "DONE", is_sql=False)
            return {
                "answer": "No spreadsheet data has been uploaded yet.",
                "sql": None, "table": [], "chart": {}, "insights": [],
                "steps": master_steps,
            }
        push_event("complete", "Matching the Right Data Source", f"Found {len(available_tables)} spreadsheet table(s) to consider.")

        metadata_match = _find_metadata_match(user_query, available_tables)
        if metadata_match:
            table_name, info = metadata_match
            push_event("start", "Preparing Your Answer", f"Summarizing what's known about '{table_name}' from its upload metadata.")
            answer_text = _build_metadata_answer(table_name, info)
            push_event("complete", "Preparing Your Answer", "Answer generated from the spreadsheet's metadata summary.")
            stream_manager.push_step(session_id, "DONE", is_sql=False)
            return {
                "answer": answer_text,
                "sql": None, "table": [], "chart": {}, "insights": [],
                "steps": master_steps,
            }

        push_event("start", "Building the Data Query", "Working out how to filter, group, and join the relevant tables.")
        plan_prompt = _build_plan_prompt(available_tables)
        raw_plan = _invoke_llm(model_name, custom_key, plan_prompt, user_query)

        try:
            plan = _extract_json(raw_plan)
            plan = _validate_plan(plan, available_tables)
        except PlanValidationError as e:
            push_event("complete", "Building the Data Query", f"Could not build a valid query plan: {e}")
            stream_manager.push_step(session_id, "DONE", is_sql=False)
            return {
                "answer": "I couldn't work out how to answer that from the uploaded spreadsheets. Try rephrasing, or mentioning the sheet/column names involved.",
                "sql": None, "table": [], "chart": {}, "insights": [],
                "steps": master_steps,
            }
        push_event("complete", "Building the Data Query", "Prepared a plan: " + ", ".join(plan["tables"]) + ".")

        push_event("start", "Running the Query", "Applying filters, joins, and aggregations to your spreadsheet data.")
        try:
            result_df = _execute_plan(plan)
        except Exception as e:
            print(f"⚠️ [SPREADSHEET] Plan execution failed: {e}")
            push_event("complete", "Running the Query", "Something went wrong while running this against your spreadsheet data.")
            stream_manager.push_step(session_id, "DONE", is_sql=False)
            return {
                "answer": "Something went wrong while working through the uploaded spreadsheets for this question. Please try rephrasing it.",
                "sql": None, "table": [], "chart": {}, "insights": [],
                "steps": master_steps,
            }
        push_event("complete", "Running the Query", f"Retrieved {len(result_df)} row(s).")

        push_event("start", "Preparing Your Answer", f"Summarizing the result with {model_name}.")
        table_records = json.loads(result_df.to_json(orient="records", date_format="iso"))
        sample_text = result_df.head(10).to_string(index=False) if not result_df.empty else "(no rows)"
        answer_prompt = (
            f"Question: {user_query}\n\n"
            f"Result ({len(result_df)} row(s)):\n{sample_text}\n\n"
            "Answer the question the way an analyst would report it to a busy "
            "stakeholder: lead with the direct answer in 1-3 sentences, "
            "specific numbers where relevant, no filler or restating the "
            "question. Do not dump every row or every column of nuance up "
            "front. If there is more depth worth surfacing (breakdowns, "
            "outliers, caveats) that you're leaving out for brevity, end "
            "with a short offer such as 'Want more detail on this?' instead "
            "of including it all."
        )
        system_content = "You are Saarthi AI, acting as a data analyst for this enterprise."
        if system_instructions and system_instructions.strip():
            system_content += f"\n\n[CRITICAL PERSONA AND CUSTOM FORMATTING RULES]:\n{system_instructions}"
        try:
            final_answer = _invoke_llm(model_name, custom_key, system_content, answer_prompt).strip()
        except Exception as e:
            print(f"⚠️ [SPREADSHEET] Answer generation failed: {e}")
            final_answer = f"Found {len(result_df)} matching row(s) in your uploaded spreadsheets."
        push_event("complete", "Preparing Your Answer", f"Answer generated successfully through {model_name}.")

        stream_manager.push_step(session_id, "DONE", is_sql=False)
        return {
            "answer": final_answer,
            "sql": None,
            "table": table_records,
            "chart": {},
            "insights": [],
            "steps": master_steps,
        }

    except Exception as e:
        print(f"⚠️ [SPREADSHEET] Unexpected error: {e}")
        stream_manager.push_step(session_id, "DONE", is_sql=False)
        return {
            "answer": "Something went wrong while checking your uploaded spreadsheets. Please try again.",
            "sql": None, "table": [], "chart": {}, "insights": [],
            "steps": master_steps,
        }
