"""
QuerySenseAgent - Analyzes query intent to extract tables, columns, and filters
Compatible with LangGraph DataBridgeState
"""
import re
import json
import time
from datetime import datetime
from typing import Dict, Any, List
#import ollama
import requests
import os
from langchain_openai import ChatOpenAI
from app.services.llm_call_logger import tracked_invoke
from app.services.databridge_services.ollama_client import (
    OLLAMA_SCHEMA_MAX_TABLES,
    ollama_generate,
)

# JSON Schema for the plan, sent to Ollama as `format` (structured outputs).
# The model can then only return an object with these keys. Without it,
# Llama 2 7B answered "Count of machines grouped by status" with invented
# rows ({"machines": [{"machine_id": 1, ...}]}) instead of a plan.
PLAN_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "tables": {"type": "array", "items": {"type": "string"}},
        "columns": {"type": "array", "items": {"type": "string"}},
        "intent": {
            "type": "string",
            "enum": ["SELECTION", "AGGREGATION", "GROUPED_ANALYSIS", "DISTINCT_SELECTION"],
        },
        "aggregations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "function": {"type": "string", "enum": ["sum", "min", "max", "avg", "count", "count_distinct"]},
                    "column": {"type": "string"},
                },
                "required": ["function", "column"],
            },
        },
        "group_by": {"type": "array", "items": {"type": "string"}},
        "joins": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"left": {"type": "string"}, "right": {"type": "string"}},
                "required": ["left", "right"],
            },
        },
        "filters": {"type": "array", "items": {"type": "string"}},
        "order_by": {"type": "array", "items": {"type": "string"}},
        "limit": {"type": "integer"},
        "assumption_note": {"type": "string"},
    },
    "required": ["tables", "columns", "intent", "aggregations", "group_by", "joins",
                 "filters", "order_by", "limit", "assumption_note"],
}


_MAX_CATEGORY_VALUES = 8
_MAX_CATEGORY_VALUE_LEN = 40


def _category_values(props: dict) -> List[str]:
    """Distinct example values of a category (dimension) column, for the
    planner to match qualifying words like "breakdowns" against. Other
    columns (ids, measures, dates, free text) return nothing - their
    samples don't help pick a filter and only cost prompt space."""
    if props.get("role") != "dimension":
        return []
    seen, values = set(), []
    for raw in props.get("example_values") or []:
        if raw is None:
            continue
        value = str(raw).strip()
        if not value or value in seen or len(value) > _MAX_CATEGORY_VALUE_LEN:
            continue
        seen.add(value)
        values.append(value)
        if len(values) >= _MAX_CATEGORY_VALUES:
            break
    return values


def _table_named_in(table: str, query_words: set) -> bool:
    """True when every word of a table name appears in the question, e.g.
    "production_orders" in "open production orders by plant"."""
    parts = re.findall(r"[a-z]{3,}", table.lower())
    return bool(parts) and all(p in query_words or p.rstrip("s") in query_words for p in parts)


def _is_local_model(target_model) -> bool:
    value = str(target_model or "")
    return value.startswith("ollama://") or value == "llama3"


def _query_words(text: str) -> set:
    """Lower-case words of 3+ letters, each also in a naive singular form
    ("machines" -> "machine"), for matching against table/column names."""
    words = set()
    for w in re.findall(r"[a-z]{3,}", (text or "").lower()):
        words.add(w)
        if w.endswith("ies") and len(w) > 4:
            words.add(w[:-3] + "y")
        elif w.endswith("s") and len(w) > 3:
            words.add(w[:-1])
    return words

class QuerySenseAgent:
    """
    Agent responsible for analyzing query intent.
    Extracts tables, columns, filters, aggregations from user query.
    Self-contained and compatible with LangGraph DataBridgeState.
    """

    class QuerySense:
        """Internal QuerySense logic"""

        def __init__(self, schema: Dict[str, Any], ollama_model: str = "llama3", ollama_url: str = "http://ollama:11434/api/generate"):
            self.schema = schema or {"tables": {}}
            self.model = ollama_model
            self.url = ollama_url
            self.state: Dict[str, Any] = {}
            self.openai_key = os.getenv("OPENAI_API_KEY")
            self.custom_key = ""

        # -------------------- SCHEMA HELPERS -------------------------
        #def _table_exists(self, table: str) -> bool:
        #    return table in self.schema.get("tables", {})

        #def _col_exists(self, table: str, col: str) -> bool:
        #    tbl = self.schema.get("tables", {}).get(table)
        #    return tbl and col in tbl.get("columns", {})
        
        def _table_exists(self, table: str) -> bool:
            # Check if 'Mara' matches 'mara' by making both lowercase
            return table.lower() in [t.lower() for t in self.schema.get("tables", {}).keys()]

        def _col_exists(self, table: str, col: str) -> bool:
            # 1. Find the actual table key (e.g., 'mara') regardless of how LLM spelled it
            actual_table = next((t for t in self.schema.get("tables", {}) if t.lower() == table.lower()), None)
            if not actual_table:
                return False
            
            # 2. Check if the column exists in that table, also case-insensitive
            columns = self.schema["tables"][actual_table].get("columns", {}).keys()
            return col.lower() in [c.lower() for c in columns]

        def _all_tables(self) -> List[str]:
            return list(self.schema.get("tables", {}).keys())

        def _foreign_keys_text(self, tables: List[str] = None) -> str:
            keep = set(tables) if tables is not None else None
            parts = []
            for t, meta in self.schema["tables"].items():
                if keep is not None and t not in keep:
                    continue
                for fk in meta.get("foreign_keys", []) or []:
                    if fk.get("column") and fk.get("references"):
                        ref_table = str(fk["references"]).split(".", 1)[0]
                        if keep is not None and ref_table not in keep:
                            continue
                        parts.append(f"{t}.{fk['column']} -> {fk['references']} (declared)")
            for rel in self.schema.get("relations", []):
                if keep is not None and (rel.get("from_table") not in keep or rel.get("to_table") not in keep):
                    continue
                confidence = rel.get("confidence", "inferred")
                parts.append(
                    f"{rel['from_table']}.{rel['from_column']} -> {rel['to_table']}.{rel['to_column']} "
                    f"(inferred from {confidence.replace('_', ' ')} - not a declared constraint, verify it "
                    f"makes sense for this question before joining on it)"
                )
            return "\n".join(parts) or "(none)"

        def _schema_context_text(self, tables: List[str] = None) -> str:
            keep = set(tables) if tables is not None else None
            lines = []
            for t, meta in self.schema["tables"].items():
                if keep is not None and t not in keep:
                    continue
                descr = meta.get("description", "")
                lines.append(f"TABLE: {t} — {descr}")
                for col, props in meta.get("columns", {}).items():
                    props = props if isinstance(props, dict) else {}
                    # Introspected schemas carry "meaning"; older static
                    # schema files used "description".
                    cdesc = props.get("meaning") or props.get("description", "")
                    values = _category_values(props)
                    values_text = f" (values: {', '.join(values)})" if values else ""
                    lines.append(f"  - {t}.{col}: {cdesc}{values_text}")
                lines.append("")
            return "\n".join(lines)

       
            

        def _relevant_tables(self, user_query: str, hint_tables: list = None,
                             limit: int = OLLAMA_SCHEMA_MAX_TABLES) -> List[str]:
            """The `limit` tables most likely needed for this question, for
            prompts sent to local models. The full schema overflows a small
            context window (Llama 2 has 4,096 tokens), and Ollama then drops
            the start of the prompt, which holds the output rules.

            Scoring: router-hinted table 10, a word of the table name in
            the question 3, a column name in the question 1. Tables joined
            to a top-scoring table by a known relation fill any slots left,
            so the readable-name joins of rule 2 stay possible."""
            all_tables = self._all_tables()
            if len(all_tables) <= limit:
                return all_tables

            words = _query_words(user_query)
            hinted = {str(h).lower() for h in (hint_tables or [])}
            scores = {}
            for t in all_tables:
                score = 10 if t.lower() in hinted else 0
                name_parts = _query_words(t.replace("_", " "))
                if t.lower() in words or (name_parts and name_parts & words):
                    score += 3
                for col in self.schema["tables"][t].get("columns", {}):
                    if col.lower() in words or _query_words(col.replace("_", " ")) & words:
                        score += 1
                scores[t] = score

            ranked = sorted(all_tables, key=lambda t: -scores[t])
            chosen = [t for t in ranked if scores[t] > 0][:limit]
            if not chosen:
                return ranked[:limit]

            neighbours = []
            for rel in self.schema.get("relations", []):
                a, b = rel.get("from_table"), rel.get("to_table")
                if a in chosen and b not in chosen:
                    neighbours.append(b)
                elif b in chosen and a not in chosen:
                    neighbours.append(a)
            for t, meta in self.schema["tables"].items():
                for fk in meta.get("foreign_keys", []) or []:
                    ref = str(fk.get("references") or "").split(".", 1)[0]
                    if t in chosen and ref in self.schema["tables"] and ref not in chosen:
                        neighbours.append(ref)
                    elif ref in chosen and t not in chosen:
                        neighbours.append(t)
            neighbours = {t for t in neighbours if t in scores}
            for t in sorted(neighbours, key=lambda t: (-scores[t], all_tables.index(t))):
                if len(chosen) >= limit:
                    break
                chosen.append(t)
            return chosen

        def _call_llm_for_plan(self, user_query: str,target_model: str,system_instructions: str = "", hint_tables: list = None, feedback_context: str = "", user_id=None, retry_feedback: str = "") -> Dict[str, Any]:
            local_model = _is_local_model(target_model)
            # A local model only gets the tables relevant to this question
            # (see _relevant_tables); hosted models keep the full schema.
            schema_tables = (
                self._relevant_tables(user_query, hint_tables) if local_model else self._all_tables()
            )
            if local_model:
                print(f"📉 [QuerySense] Local model - schema trimmed to {len(schema_tables)} table(s): {schema_tables}")
            schema_brief = "\n".join(
                f"Table '{t}': [{', '.join(self.schema['tables'][t]['columns'].keys())}]"
                for t in schema_tables
            #schema_brief = "\n".join(
            #    f"{t}({', '.join(self.schema['tables'][t]['columns'].keys())})"
            #    for t in schema_tables
            )

            fk_text = self._foreign_keys_text(schema_tables if local_model else None)
            ctx_text = self._schema_context_text(schema_tables if local_model else None)

            # The router already read the live schema metadata and named
            # the table(s) it thinks this question needs (see
            # router_service.py's query_database tool call) - validated
            # against the real schema here (case-insensitive) so a stale or
            # invented name from the router is never echoed into the
            # prompt as if it were fact. This is a starting hint, not a
            # constraint: the instructions below explicitly allow adding or
            # dropping tables from it.
            valid_hint_tables = [
                t for t in (hint_tables or [])
                if any(t.lower() == real.lower() for real in self._all_tables())
            ]
            hint_block = (
                f"\nROUTER-IDENTIFIED TABLE(S) (from live schema metadata - a starting "
                f"point, not a constraint): {', '.join(valid_hint_tables)}\n"
                "Use these if they genuinely answer the question. Add other tables the "
                "question also needs, or ignore this hint entirely if none of these "
                "tables actually apply.\n"
                if valid_hint_tables else ""
            )

            # Self-learning feedback on past similar questions - previously
            # threaded all the way down into initial_state["feedback_context"]
            # (see run_data_bridge_agent) but never actually read by this
            # agent, so a DISLIKED remark like "wrong table" or "missed a
            # join" never reached the one step that picks tables/columns in
            # the first place - only SQLGeneratorAgent downstream saw it.
            self_learning_block = ""
            if feedback_context:
                self_learning_block = f"""
{feedback_context}

The block above is feedback on how PAST similar questions were answered -
it is NOT part of the current question. It can describe a wrong table or
column chosen, a missed or unnecessary join, a wrong aggregation/grouping,
or a wrong intent classification. If a DISLIKED note is still relevant to
this question, adjust the table/column/join/aggregation selection to
address it. If a LIKED note confirms a past selection worked, prefer
reusing that approach when it fits. Ignore anything that doesn't apply to
this specific question.
"""

            # Was previously accepted as a parameter and threaded all the
            # way down here, but never inserted into the prompt - so a
            # user's custom persona/formatting instructions had no effect
            # on table/column selection at all.
            # Set when error_diagnosis sends the pipeline back here. Without
            # it a retry sent the identical prompt at temperature 0 and got
            # the identical failed plan back.
            retry_block = (
                f"\nPREVIOUS ATTEMPT FAILED: {retry_feedback.strip()}\n"
                "Pick tables and columns ONLY from the schema below, spelled exactly as shown.\n"
                if retry_feedback and retry_feedback.strip() else ""
            )

            system_instructions_block = (
                f"\nUSER CUSTOM FORMATTING INSTRUCTIONS (context only - does not "
                f"change which tables/columns are correct):\n{system_instructions.strip()}\n"
                if system_instructions and system_instructions.strip() else ""
            )

            #prompt = f"""
#You are QuerySense — an expert SQL planner.

#Use ONLY the tables, columns, and foreign-key relationships from the schema.
#Do NOT invent names.

#Return a concise JSON with:
#- tables: list of table names
#- columns: list of "table.column"
#- intent: SELECTION | AGGREGATION | GROUPED_ANALYSIS | DISTINCT_SELECTION
#- aggregations: list of {{ "function": "sum|min|max|avg|count", "column": "table.column" or "*" }}
#- group_by: list of "table.column"
#- joins: list of {{ "left": "table.col", "right": "table.col" }}
#- filters: list of SQL boolean expressions
#- order_by: list of SQL order expressions
#- limit: integer

            
            prompt = f"""
You are QuerySense — an expert SQL planner.

Use ONLY the tables, columns, and foreign-key relationships from the schema.
Do NOT invent names.
{hint_block}{self_learning_block}{system_instructions_block}{retry_block}
1. NAME THE METRIC, DON'T SWAP IT SILENTLY: if the user's question names a
specific metric or value (e.g. "net value", "price", "cost", "revenue")
and NO column in the schema above actually matches it for the table(s) this
question needs, do not silently pick a different column (like "quantity")
as if it answers the question - that produces a confident-sounding but
wrong answer. Instead: (a) check whether some OTHER table in the schema has
a column that genuinely matches the requested metric before giving up, and
only use it if it can be reached from the same rows via a real foreign-key
relation; (b) if truly nothing in the schema matches, still return your
best-effort plan using the closest available column, but explain the
substitution in the "assumption_note" field below so the user is told what
was actually computed instead of what they asked for.
2. SHOW NAMES, NOT IDS: business users read the answer, so an ID or code
(branch_id, customer_id, product_code) is not a meaningful label on its own.
When you group by, or display, such a key column and a table reachable via
the FOREIGN-KEY RELATIONS below has a readable column for it (e.g.
branches.branch_name, customers.name), add that table, add the join on the
key, and put the readable column in "columns" and "group_by" - keep the ID
in "group_by" too so two rows sharing a name are not merged. Skip this when
the user explicitly asks for the ID itself.
3. COUNT THINGS, NOT ROWS: when the question asks how many of an entity
(machines, customers, suppliers, products, ...) and the table being counted
records events or transactions about it - so the same entity's id can appear
on many rows (e.g. one row per downtime event, order or payment) - use
{{"function": "count_distinct", "column": "<that table>.<entity id column>"}}.
Use plain "count" only when the question counts the events themselves
("how many downtime events", "number of orders") or the table has exactly
one row per entity.
4. QUALIFYING WORDS ARE FILTERS: when the question narrows what is counted
or listed with a word that matches the listed values of a column (e.g.
"breakdowns" when a category column has values like 'Minor Breakdown' and
'Major Breakdown'), add a filter on that column - use ILIKE '%<word>%' when
the word matches several values, or = '<value>' for one exact value. Never
ignore such a word, and never invent a column for it.

Return a concise JSON with:
- tables: list of table names
- columns: list of "table.column"
- intent: SELECTION | AGGREGATION | GROUPED_ANALYSIS | DISTINCT_SELECTION
- aggregations: list of {{ "function": "sum|min|max|avg|count|count_distinct", "column": "table.column" or "*" }}
- group_by: list of "table.column"
- joins: list of {{ "left": "table.col", "right": "table.col" }}
- filters: list of SQL boolean expressions
- order_by: list of SQL order expressions
- limit: integer
- assumption_note: "" normally. Only non-empty when you had to substitute a
  different column for a metric the user explicitly named because no exact
  match exists in the schema - one plain-English sentence naming what was
  asked for and what is being returned instead.

EXAMPLE:
Query: "Show 3 document numbers from bkpf"
Output:
{{
  "tables": ["bkpf"],
  "columns": ["bkpf.document_number"],
  "intent": "SELECTION",
  "aggregations": [],
  "group_by": [],
  "joins": [],
  "filters": [],
  "order_by": [],
  "limit": 3,
  "assumption_note": ""
}}

EXAMPLE (rule 2 - the key is replaced by its readable name via a join):
Query: "Number of employees by branch"
Output:
{{
  "tables": ["employees", "branches"],
  "columns": ["branches.branch_name"],
  "intent": "GROUPED_ANALYSIS",
  "aggregations": [{{"function": "count", "column": "*"}}],
  "group_by": ["employees.branch_id", "branches.branch_name"],
  "joins": [{{"left": "employees.branch_id", "right": "branches.branch_id"}}],
  "filters": [],
  "order_by": [],
  "limit": 0,
  "assumption_note": ""
}}
(These table names are illustrative - always use the real ones from the schema below.)

Now output JSON for the user query above.
SCHEMA STRUCTURE:
{schema_brief}

FOREIGN-KEY RELATIONS:
{fk_text}

SEMANTIC CONTEXT:
{ctx_text}

USER QUESTION:
\"\"\"{user_query}\"\"\"

Return ONLY the JSON plan object described above (keys: tables, columns,
intent, aggregations, group_by, joins, filters, order_by, limit,
assumption_note). Do NOT return data rows or invent values.
"""
            # --- REQUIRED CHANGES START HERE ---
            import requests # Local import to ensure it's available
            
            try:

                if target_model == "gpt-4o":
                    print("🔥 [QuerySense] Routing to ChatOpenAI [gpt-4o] Layer...")
                    from langchain_openai import ChatOpenAI
                    llm = ChatOpenAI(
                        model="gpt-4o",
                        temperature=0,
                        openai_api_key=self.openai_key
                    )
                    ai_response = tracked_invoke(
                        llm, prompt, purpose="query_sense.plan", model_name="gpt-4o",
                        provider="openai", user_id=user_id,
                    )
                    text = ai_response.content.strip()

                elif target_model == "gpt-4o-mini":
                    print("🤖 [QuerySense] Routing to ChatOpenAI [gpt-4o-mini] Layer...")
                    from langchain_openai import ChatOpenAI
                    llm = ChatOpenAI(
                        model="gpt-4o-mini",
                        temperature=0,
                        openai_api_key=self.openai_key
                    )
                    ai_response = tracked_invoke(
                        llm, prompt, purpose="query_sense.plan", model_name="gpt-4o-mini",
                        provider="openai", user_id=user_id,
                    )
                    text = ai_response.content.strip()

                elif target_model == "llama3":
                    print("🦙 [QuerySense] Routing to local Ollama [llama3] container layer...")
                    text, _ = ollama_generate(
                        self.url, "llama3", prompt,
                        purpose="query_sense.plan", response_format=PLAN_JSON_SCHEMA, user_id=user_id,
                    )

                elif str(target_model).startswith("api://"):
                    actual_model = target_model.replace("api://", "").lower()
                    print(f"🌐 [QuerySense] Dynamic Routing payload to Custom Cloud API model: {actual_model}")

                    from app.services.llm_providers import resolve_dynamic_llm
                    dynamic_llm = resolve_dynamic_llm(
                        actual_model,
                        self.custom_key,
                        temperature=0,
                        openai_fallback_key=self.openai_key,
                        strict=True,
                    )
                    ai_response = tracked_invoke(
                        dynamic_llm, prompt, purpose="query_sense.plan", model_name=actual_model, user_id=user_id,
                    )
                    text = ai_response.content.strip()

                elif str(target_model).startswith("ollama://"):
                    actual_model = target_model.replace("ollama://", "")
                    print(f"📦 [QuerySense] Dynamic Routing payload to Custom Local Ollama model: {actual_model}")
                    text, _ = ollama_generate(
                        self.url, actual_model, prompt,
                        purpose="query_sense.plan", response_format=PLAN_JSON_SCHEMA, user_id=user_id,
                    )

                else:
                    raise ValueError(f"Requested model '{target_model}' has no active route configuration.")    
    
                print(f"\n🔍 DEBUG LLM RAW OUTPUT:\n{text}\n")
                # Logic: Find the FIRST '{' and LAST '}'
                import re
            # This regex finds everything between the first { and the last }
                match = re.search(r'(\{.*\})', text, re.DOTALL)

                if match:
                # Use match.group(1) to get only the JSON part
                    parsed = json.loads(match.group(1))
                    if isinstance(parsed, dict) and not (parsed.get("assumption_note") or "").strip():
                        # Some models explain themselves in prose before the
                        # JSON instead of filling in "assumption_note" as
                        # instructed (e.g. "Since the schema doesn't have X,
                        # we assume Y... if X was meant, please clarify").
                        # That explanation is exactly the caveat this field
                        # exists to carry downstream to the user - without
                        # this fallback it's simply discarded, and a metric
                        # substitution (e.g. "quantity" standing in for "net
                        # value") reaches the user with no indication it
                        # ever happened.
                        preamble = text[:match.start()].strip()
                        preamble = re.sub(r"```(?:json)?\s*$", "", preamble).strip()
                        if preamble:
                            parsed["assumption_note"] = preamble
                    return parsed
                else:
                    print("⚠️ No JSON brackets found in LLM response.")
                    return {}
            except Exception as e:
                print(f"DEBUG Error during LLM parse: {e}")
                return {}


                #start = text.find('{')
                #end = text.rfind('}') + 1
                #if start != -1 and end > 0:
                #    return json.loads(text[start:end])
                #return {}
            #except Exception as e:
            #    print(f"DEBUG Error: {e}")
            #    return {}



                # Talking to Ollama container via self.url (http://ollama:11434/api/generate)
                #resp = requests.post(self.url, json=payload, timeout=300)
                #resp.raise_for_status()
                
                # Get response text from the Ollama API
                #text = resp.json().get("response", "").strip()
                
                #m = re.search(r"\{.*\}", text, re.S)
                #if not m:
                #    return {}
                #return json.loads(m.group(0))
            #except Exception as e:
            #    print(f"[QuerySense] LLM connection error: {e}")
            #    return {}
             

        # -------------------- FALLBACK -------------------------------
        def _fallback_simple(self, query: str, hint_tables: list = None) -> Dict[str, Any]:
            ql = query.lower()
            words = re.findall(r"\b[a-zA-Z_]{3,}\b", ql)
            resolved = []

            # Tables the question names ("machines" -> machines), plus any
            # the router hinted. When there are some, column matches are
            # kept to those tables, so "status" does not pull in every
            # table that has a status column.
            query_words = _query_words(query)
            named_tables = [t for t in self.schema["tables"] if _table_named_in(t, query_words)]
            for h in hint_tables or []:
                real = self._resolve_table(h)
                if real and real not in named_tables:
                    named_tables.append(real)

            for t, meta in self.schema["tables"].items():
                if named_tables and t not in named_tables:
                    continue
                for col in meta["columns"].keys():
                    if col.lower() in words:
                        resolved.append(f"{t}.{col}")

            intent = "SELECTION"
            aggregations = []
            group_by = []
            limit = 0

            if any(w in ql for w in ["how many", "count", "number of", "total number", "total count"]):
                intent = "AGGREGATION"
                aggregations.append({"function": "count", "column": "*"})
            elif any(w in ql for w in ["sum of", "total", "summed"]):
                intent = "AGGREGATION"
                aggregations.append({"function": "sum", "column": None})
            elif any(w in ql for w in ["average", "avg", "mean"]):
                intent = "AGGREGATION"
                aggregations.append({"function": "avg", "column": None})
            elif any(w in ql for w in ["top ", "highest", "most"]):
                intent = "AGGREGATION"
                aggregations.append({"function": "sum", "column": None})

            top_match = re.search(r"top\s+(\d+)", ql)
            limit_match = re.search(r"limit\s+(\d+)", ql)
            if top_match:
                limit = int(top_match.group(1))
            elif limit_match:
                limit = int(limit_match.group(1))

            tables = sorted({c.split(".")[0] for c in resolved}) or sorted(named_tables)

            # "count of machines by status", "per plant", "grouped by ..."
            if aggregations and resolved and re.search(r"\b(by|per|group(ed)?|each)\b", ql):
                intent = "GROUPED_ANALYSIS"
                group_by = list(resolved)

            return {
                "tables": tables,
                "columns": resolved,
                "intent": intent,
                "aggregations": aggregations,
                "group_by": group_by,
                "joins": [],
                "filters": [],
                "order_by": [],
                "limit": limit
            }

        # -------------------- VALIDATION -----------------------------
        #def _validate_plan(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        #    sanitized = {
        #        "tables": [],
        #        "columns": [],
        #        "intent": "SELECTION",
        #        "aggregations": [],
        #        "group_by": [],
        #        "joins": [],
        #        "filters": [],
        #        "order_by": [],
        #        "limit": 0,
        #    }

        #    if not isinstance(plan, dict):
        #        return sanitized

        #    sanitized["tables"] = [t for t in plan.get("tables", []) if self._table_exists(t)]

        #    for c in plan.get("columns", []):
        #        if isinstance(c, str) and "." in c:
        #            t, col = c.split(".", 1)
        #            if self._col_exists(t, col):
        #                sanitized["columns"].append(f"{t}.{col}")

        #    intent = (plan.get("intent") or "").upper()
        #    if intent in ("SELECTION", "AGGREGATION", "GROUPED_ANALYSIS", "DISTINCT_SELECTION"):
        #        sanitized["intent"] = intent

        #    for a in plan.get("aggregations", []):
        #        fn, col = a.get("function"), a.get("column")
        #        if fn in ("sum", "avg", "min", "max", "count") and (col == "*" or (isinstance(col, str) and "." in col and self._col_exists(*col.split(".", 1)))):
        #            sanitized["aggregations"].append({"function": fn, "column": col})

        #    sanitized["group_by"] = [gb for gb in plan.get("group_by", []) if "." in gb and self._col_exists(*gb.split(".", 1))]

        #    for j in plan.get("joins", []):
        #        left, right = j.get("left"), j.get("right")
        #        if left and right and "." in left and "." in right:
        #            lt, lc = left.split(".", 1)
        #            rt, rc = right.split(".", 1)
        #            if self._col_exists(lt, lc) and self._col_exists(rt, rc):
        #                sanitized["joins"].append({"left": left, "right": right})
        #                for t in [lt, rt]:
        #                    if t not in sanitized["tables"]:
        #                        sanitized["tables"].append(t)

        #    sanitized["filters"] = [
        #        f for f in plan.get("filters", []) if all(self._col_exists(t, c) for t, c in re.findall(r"([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)", f))
        #    ]

        #    sanitized["order_by"] = [o for o in plan.get("order_by", []) if isinstance(o, str)]

        #    try:
        #        sanitized["limit"] = int(plan.get("limit") or 0)
        #    except:
        #        sanitized["limit"] = 0

        #    return sanitized
        
        # -------------------- PLAN RESOLUTION HELPERS ----------------
        # Join keys too generic to trust on name alone - every table has its
        # own "id", so employees.id = branches.id is almost never a real join.
        _GENERIC_KEY_NAMES = {"id", "code", "key", "name", "description", "type", "status", "no"}
        _KEY_SUFFIXES = ("_id", "_code", "_no", "_key", "id")

        def _resolve_table(self, name: Any):
            if not isinstance(name, str):
                return None
            return next((t for t in self.schema.get("tables", {}) if t.lower() == name.strip().lower()), None)

        def _resolve_column(self, ref: Any):
            """'Table.Col' in any case -> 'table.col' as spelled in the schema, or None."""
            if not isinstance(ref, str) or "." not in ref:
                return None
            t_llm, c_llm = ref.strip().split(".", 1)
            real_t = self._resolve_table(t_llm)
            if not real_t:
                return None
            real_c = next((rc for rc in self.schema["tables"][real_t].get("columns", {})
                           if rc.lower() == c_llm.strip().lower()), None)
            return f"{real_t}.{real_c}" if real_c else None

        def _known_relation_pairs(self) -> set:
            """Every declared FK and inferred relation, as unordered lowercase 'table.col' pairs."""
            pairs = set()
            for t, meta in self.schema.get("tables", {}).items():
                for fk in meta.get("foreign_keys", []) or []:
                    if fk.get("column") and fk.get("references"):
                        pairs.add(frozenset({f"{t}.{fk['column']}".lower(), fk["references"].lower()}))
            for rel in self.schema.get("relations", []) or []:
                if all(rel.get(k) for k in ("from_table", "from_column", "to_table", "to_column")):
                    pairs.add(frozenset({
                        f"{rel['from_table']}.{rel['from_column']}".lower(),
                        f"{rel['to_table']}.{rel['to_column']}".lower(),
                    }))
            return pairs

        def _is_valid_join(self, left: str, right: str, relation_pairs: set) -> bool:
            """A join is kept only if the schema backs it: a declared/inferred
            relation, or a shared, specific key name (branch_id = branch_id)
            for schemas that were never annotated with FKs."""
            lt, lc = left.split(".", 1)
            rt, rc = right.split(".", 1)
            if lt == rt:
                return False
            if frozenset({left.lower(), right.lower()}) in relation_pairs:
                return True
            return lc.lower() == rc.lower() and lc.lower() not in self._GENERIC_KEY_NAMES

        @staticmethod
        def _singular(table: str) -> str:
            t = table.lower()
            if t.endswith("ies"):
                return t[:-3] + "y"
            if t.endswith(("ches", "shes", "sses", "xes")):
                return t[:-2]
            if t.endswith("s") and not t.endswith("ss"):
                return t[:-1]
            return t

        def _key_stem(self, col: str) -> str:
            """'branch_id' -> 'branch'. '' for columns that aren't key-like."""
            c = col.lower()
            for suffix in self._KEY_SUFFIXES:
                if c.endswith(suffix) and len(c) > len(suffix):
                    return c[: -len(suffix)].rstrip("_")
            return ""

        def _label_column_for(self, table: str, stem: str):
            """The human-readable column of `table` (branch_name, name, title,
            ...), or None if there isn't an obvious one. Deliberately narrow:
            a generic *_name like first_name is only used when it's the
            table's only *_name column."""
            cols = self.schema["tables"][table].get("columns", {}) or {}
            lower_map = {c.lower(): c for c in cols}
            singular = self._singular(table)
            candidates = [
                f"{stem}_name", f"{singular}_name", "name", "full_name",
                f"{stem}_title", "title", "label",
                f"{stem}_description", f"{stem}_desc", "description",
            ]
            for cand in candidates:
                real = lower_map.get(cand)
                if real and self._is_text_column(cols[real]):
                    return real
            name_cols = [c for c in cols if c.lower().endswith("_name") and self._is_text_column(cols[c])]
            return name_cols[0] if len(name_cols) == 1 else None

        @staticmethod
        def _is_text_column(props: Any) -> bool:
            col_type = str((props or {}).get("type") or "").lower() if isinstance(props, dict) else ""
            if not col_type:
                return True  # schema carries no type info - trust the name
            return any(k in col_type for k in ("char", "text", "string", "varchar", "object"))

        def _owner_of_key(self, table: str, col: str, stem: str):
            """For a foreign-key-like column (employees.branch_id), the table it
            identifies and that table's matching key column - ('branches',
            'branch_id') - or None if it can't be pinned to exactly one table."""
            for fk in self.schema["tables"][table].get("foreign_keys", []) or []:
                if (fk.get("column") or "").lower() == col.lower() and "." in (fk.get("references") or ""):
                    ref = self._resolve_column(fk["references"])
                    if ref:
                        return tuple(ref.split(".", 1))
            owners = []
            for other, meta in self.schema.get("tables", {}).items():
                if other == table or self._singular(other) != stem:
                    continue
                key = next((c for c in meta.get("columns", {}) if c.lower() == col.lower()), None)
                if key:
                    owners.append((other, key))
            return owners[0] if len(owners) == 1 else None

        def _add_display_labels(self, sanitized: Dict[str, Any]) -> Dict[str, Any]:
            """When the plan groups by an ID (employees.branch_id), also group
            by - and select - the readable label it stands for (branches.branch_name),
            adding the join if needed. Done in code rather than trusted to the
            prompt because models follow that instruction inconsistently, and an
            answer keyed by "branch 77" is useless to a business user. The ID
            stays in GROUP BY so two branches sharing a name aren't merged."""
            for gb in list(sanitized["group_by"]):
                table, col = gb.split(".", 1)
                stem = self._key_stem(col)
                if not stem:
                    continue
                if self._singular(table) == stem:
                    owner, owner_key = table, col  # grouping by the table's own key
                else:
                    found = self._owner_of_key(table, col, stem)
                    if not found:
                        continue
                    owner, owner_key = found
                label = self._label_column_for(owner, stem)
                if not label:
                    continue
                label_ref = f"{owner}.{label}"
                if label_ref in sanitized["group_by"]:
                    continue
                if owner != table:
                    already_joined = any(owner in (j["left"].split(".", 1)[0], j["right"].split(".", 1)[0])
                                         for j in sanitized["joins"])
                    if not already_joined:
                        sanitized["joins"].append({"left": gb, "right": f"{owner}.{owner_key}"})
                    if owner not in sanitized["tables"]:
                        sanitized["tables"].append(owner)
                sanitized["group_by"].append(label_ref)
                if label_ref not in sanitized["columns"]:
                    sanitized["columns"].append(label_ref)
                print(f"🏷️ [QuerySense] Grouping by {gb} - added readable label {label_ref}")
            return sanitized

        def _validate_plan(self, plan: Dict[str, Any]) -> Dict[str, Any]:
            sanitized = {
                "tables": [], "columns": [], "intent": "SELECTION",
                "aggregations": [], "group_by": [], "joins": [],
                "filters": [], "order_by": [], "limit": 0,
            }

            if not isinstance(plan, dict):
                return sanitized

            # Case-insensitive mapping onto the real schema spelling throughout -
            # the LLM often writes 'Mara' for 'mara'.
            for t_llm in plan.get("tables", []) or []:
                real_t = self._resolve_table(t_llm)
                if real_t and real_t not in sanitized["tables"]:
                    sanitized["tables"].append(real_t)

            for c_llm in plan.get("columns", []) or []:
                real = self._resolve_column(c_llm)
                if real and real not in sanitized["columns"]:
                    sanitized["columns"].append(real)

            sanitized["intent"] = (plan.get("intent") or "SELECTION").upper()

            for a in plan.get("aggregations", []) or []:
                if not isinstance(a, dict):
                    continue
                fn = (a.get("function") or "").lower()
                col = a.get("column")
                if fn not in ("sum", "avg", "min", "max", "count", "count_distinct"):
                    continue
                if col == "*":
                    sanitized["aggregations"].append({"function": fn, "column": "*"})
                elif self._resolve_column(col):
                    sanitized["aggregations"].append({"function": fn, "column": self._resolve_column(col)})

            for gb in plan.get("group_by", []) or []:
                real = self._resolve_column(gb)
                if real and real not in sanitized["group_by"]:
                    sanitized["group_by"].append(real)

            # Joins were previously never copied across here at all, so the SQL
            # generator (which only joins when this list is non-empty) could
            # never produce a multi-table query, whatever the LLM planned.
            relation_pairs = self._known_relation_pairs()
            for j in plan.get("joins", []) or []:
                if not isinstance(j, dict):
                    continue
                left, right = self._resolve_column(j.get("left")), self._resolve_column(j.get("right"))
                if not (left and right) or not self._is_valid_join(left, right, relation_pairs):
                    print(f"⚠️ [QuerySense] Dropping join not backed by the schema: {j}")
                    continue
                if any({left, right} == {x["left"], x["right"]} for x in sanitized["joins"]):
                    continue
                sanitized["joins"].append({"left": left, "right": right})
                for t in (left.split(".", 1)[0], right.split(".", 1)[0]):
                    if t not in sanitized["tables"]:
                        sanitized["tables"].append(t)

            for f in plan.get("filters", []) or []:
                if not isinstance(f, str) or not f.strip():
                    continue
                refs = re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\b", f)
                if all(self._resolve_column(f"{t}.{c}") for t, c in refs):
                    sanitized["filters"].append(f)

            sanitized["order_by"] = [o for o in plan.get("order_by", []) or [] if isinstance(o, str) and o.strip()]

            try:
                sanitized["limit"] = int(plan.get("limit") or 0)
            except (TypeError, ValueError):
                sanitized["limit"] = 0

            return self._add_display_labels(sanitized)

        def _build_table_context(self, tables: List[str]) -> Dict[str, str]:
            return {t: self.schema["tables"][t].get("description", "") for t in tables}

        def _build_column_context(self, columns: List[str]) -> Dict[str, str]:
            return {c: self.schema["tables"][c.split(".")[0]]["columns"][c.split(".")[1]].get("description", "") for c in columns}

        def _build_join_context(self, joins: List[Dict[str, str]]) -> List[Dict[str, str]]:
            return [{"left": j["left"], "right": j["right"], "reason": "Join based on schema foreign-key relationship"} for j in joins]

        def _build_rationale(self, user_query: str, plan: Dict[str, Any]) -> Dict[str, Any]:
            return {
                "user_intent": user_query,
                "tables_reasoning": f"Selected because they contain referenced columns: {plan['columns']}",
                "join_reasoning": str(plan["joins"]),
                "aggregation_reasoning": str(plan["aggregations"]),
                "grouping_reasoning": str(plan["group_by"]),
            }

        def _plan_names_real_tables(self, plan: Any) -> bool:
            """True when the LLM output is a plan whose "tables" list names
            at least one table that exists in the schema. Rejects JSON of
            the wrong shape, e.g. invented data rows from a small model."""
            if not isinstance(plan, dict):
                return False
            tables = plan.get("tables")
            if not isinstance(tables, list):
                return False
            return any(self._resolve_table(t) for t in tables)

        def analyze(self, user_query: str,target_model: str,system_instructions: str = "", hint_tables: list = None, feedback_context: str = "", user_id=None, retry_feedback: str = "") -> Dict[str, Any]:
            self.state["timestamp"] = datetime.now().isoformat()
            self.state["user_query"] = user_query

            plan = self._call_llm_for_plan(user_query,target_model,system_instructions,hint_tables=hint_tables,feedback_context=feedback_context,user_id=user_id,retry_feedback=retry_feedback)
            if not self._plan_names_real_tables(plan):
                if plan:
                    print("⚠️ [QuerySense] LLM output is not a usable plan (no known tables) - using keyword fallback")
                plan = self._fallback_simple(user_query, hint_tables=hint_tables)

            fallback_aggs = self._fallback_simple(user_query).get("aggregations", [])
            fallback_limit = self._fallback_simple(user_query).get("limit", 0)

            ql = user_query.lower()
            has_agg_keywords = any(w in ql for w in ["count", "sum", "total", "average", "avg", "top ", "most", "highest"])

            if has_agg_keywords and not plan.get("aggregations"):
                plan["aggregations"] = fallback_aggs
                plan["intent"] = "AGGREGATION"

            if fallback_limit > 0 and not plan.get("limit"):
                plan["limit"] = fallback_limit

            sanitized = self._validate_plan(plan)

            resolved_columns = [{"table": c.split(".")[0], "column": c.split(".")[1]} for c in sanitized["columns"]]

            table_context = self._build_table_context(sanitized["tables"])
            column_context = self._build_column_context(sanitized["columns"])
            join_context = self._build_join_context(sanitized["joins"])
            rationale = self._build_rationale(user_query, sanitized)

            output = {
                "query_type": sanitized["intent"],
                "tables": sanitized["tables"],
                "columns": [c.split(".", 1)[1] for c in sanitized["columns"]],
                "resolved_columns": resolved_columns,
                "aggregations": sanitized["aggregations"],
                "group_by": sanitized["group_by"],
                "joins": sanitized["joins"],
                "filters": sanitized["filters"],
                "order_by": sanitized["order_by"],
                "limit": sanitized["limit"],
                "timestamp": self.state["timestamp"],
                "raw_plan": plan,
                "table_context": table_context,
                "column_context": column_context,
                "join_context": join_context,
                "selection_rationale": rationale,
                "assumption_note": (plan.get("assumption_note") or "").strip() if isinstance(plan, dict) else "",
            }

            self.state["output"] = output
            print(f"✅ [QuerySense] Done ⇒ {output['tables']} {output['columns']} ({output['query_type']})")
            return output

    # --------------------------------------------------------------
    # Agent interface
    # --------------------------------------------------------------
    def __init__(self, schema: Dict[str, Any], ollama_model: str = "llama3", ollama_url: str = None):
        self.schema = schema
        self.ollama_model = ollama_model
        self.ollama_url = ollama_url
        self.query_sense = self.QuerySense(schema, ollama_model=ollama_model, ollama_url=ollama_url)

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """LangGraph-compatible execution method"""
        print(f"\n🤖 [QuerySenseAgent] Starting...")
        simplified_query = state.get("simplified_query") or state.get("user_query", "")
        chosen_model = state.get("model_name", self.ollama_model)
        custom_key = state.get("custom_key", "")
        system_instructions = state.get("system_instructions", "")
        feedback_context = state.get("feedback_context", "")
        self.query_sense.custom_key = custom_key
        self.query_sense.model = chosen_model
        hint_tables = state.get("hint_tables") or []
        if feedback_context:
            print(f"🧠 [FEEDBACK-DEBUG] [QuerySense] Using feedback context for table/column selection:\n{feedback_context}")
        diagnosis = state.get("error_diagnosis") or {}
        retry_feedback = (
            state.get("error_feedback") or ""
            if diagnosis.get("retry_from_step") == "query_sense" else ""
        )
        analysis = self.query_sense.analyze(
            simplified_query,chosen_model,system_instructions,hint_tables=hint_tables,feedback_context=feedback_context,user_id=state.get("user_id"),retry_feedback=retry_feedback)

        state["query_sense_output"] = analysis
        state["current_step"] = "query_sense"
        # A metric the user explicitly named (e.g. "net value") but that had
        # no matching column, so a different one was substituted - carried
        # forward as its own state key (read by _compose_final_answer in
        # langgraph_agent.py) so the substitution reaches the user instead
        # of being silently baked into a confident-sounding answer.
        if analysis.get("assumption_note"):
            state["assumption_note"] = analysis["assumption_note"]
        tables = analysis.get('tables', [])
        columns = analysis.get('columns', [])
        
        if "steps" not in state:
            state["steps"] = []

        # We format the list of tables and columns into a nice sentence
        description = f"Identified relevant SAP tables: {', '.join(tables)} and target columns: {', '.join(columns)}."
        state["steps"].append(description)      
        analysis["steps"] = state["steps"]
        
        print(f"✅ [QuerySenseAgent] Found tables: {analysis.get('tables', [])}")
        return state
