"""
QuerySenseAgent - Analyzes query intent to extract tables, columns, and filters
Compatible with LangGraph DataBridgeState
"""
import re
import json
from datetime import datetime
from typing import Dict, Any, List
#import ollama 
import requests 
import os
from langchain_openai import ChatOpenAI

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

        def _foreign_keys_text(self) -> str:
            parts = []
            for t, meta in self.schema["tables"].items():
                for fk in meta.get("foreign_keys", []) or []:
                    if fk.get("column") and fk.get("references"):
                        parts.append(f"{t}.{fk['column']} -> {fk['references']}")
            for rel in self.schema.get("relations", []):
                parts.append(f"{rel['from_table']}.{rel['from_column']} -> {rel['to_table']}.{rel['to_column']}")
            return "\n".join(parts) or "(none)"

        def _schema_context_text(self) -> str:
            lines = []
            for t, meta in self.schema["tables"].items():
                descr = meta.get("description", "")
                lines.append(f"TABLE: {t} — {descr}")
                for col, props in meta.get("columns", {}).items():
                    cdesc = props.get("description", "")
                    lines.append(f"  - {t}.{col}: {cdesc}")
                lines.append("")
            return "\n".join(lines)

       
            

        def _call_llm_for_plan(self, user_query: str,target_model: str,system_instructions: str = "") -> Dict[str, Any]:
            schema_tables = self._all_tables()
            schema_brief = "\n".join(
                f"Table '{t}': [{', '.join(self.schema['tables'][t]['columns'].keys())}]"
                for t in schema_tables
            #schema_brief = "\n".join(
            #    f"{t}({', '.join(self.schema['tables'][t]['columns'].keys())})"
            #    for t in schema_tables
            )

            fk_text = self._foreign_keys_text()
            ctx_text = self._schema_context_text()

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
1. PRINCIPLE OF MINIMAL SELECTION: Include ONLY the tables absolutely required to resolve the user's specific question. If a query can be answered using columns from a single table (e.g., just 'mara'), you must ONLY list that table in the "tables" array and leave the "joins" array completely empty `[]`. Do NOT add extra tables just because they are linked in the schema.

Return a concise JSON with:
- tables: list of table names
- columns: list of "table.column"
- intent: SELECTION | AGGREGATION | GROUPED_ANALYSIS | DISTINCT_SELECTION
- aggregations: list of {{ "function": "sum|min|max|avg|count", "column": "table.column" or "*" }}
- group_by: list of "table.column"
- joins: list of {{ "left": "table.col", "right": "table.col" }}
- filters: list of SQL boolean expressions
- order_by: list of SQL order expressions
- limit: integer

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
  "limit": 3
}}

Now output JSON for the user query above.
SCHEMA STRUCTURE:
{schema_brief}

FOREIGN-KEY RELATIONS:
{fk_text}

SEMANTIC CONTEXT:
{ctx_text}

USER QUESTION:
\"\"\"{user_query}\"\"\"
"""
            # --- REQUIRED CHANGES START HERE ---
            import requests # Local import to ensure it's available
            
            payload = {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.0}
            }

            try:

                if target_model == "gpt-4o":
                    print("🔥 [QuerySense] Routing to ChatOpenAI [gpt-4o] Layer...")
                    from langchain_openai import ChatOpenAI
                    llm = ChatOpenAI(
                        model="gpt-4o",
                        temperature=0,
                        openai_api_key=self.openai_key
                    )
                    ai_response = llm.invoke(prompt)
                    text = ai_response.content.strip()

                elif target_model == "gpt-4o-mini":
                    print("🤖 [QuerySense] Routing to ChatOpenAI [gpt-4o-mini] Layer...")
                    from langchain_openai import ChatOpenAI
                    llm = ChatOpenAI(
                        model="gpt-4o-mini",
                        temperature=0,
                        openai_api_key=self.openai_key
                    )
                    ai_response = llm.invoke(prompt)
                    text = ai_response.content.strip()

                elif target_model == "llama3":
                    print("🦙 [QuerySense] Routing to local Ollama [llama3] container layer...")
                    payload = {
                        "model": "llama3",  # Forces local Llama 3 image call explicitly
                        "prompt": prompt,
                        "stream": False,
                        "options": {"temperature": 0.0}
                    }
                    resp = requests.post(self.url, json=payload, timeout=120)
                    resp.raise_for_status()
                    text = resp.json().get("response", "").strip()

                elif str(target_model).startswith("api://"):
                    actual_model = target_model.replace("api://", "").lower()
                    print(f"🌐 [QuerySense] Dynamic Routing payload to Custom Cloud API model: {actual_model}")

                    if "claude" in actual_model:
                        from langchain_anthropic import ChatAnthropic
                        dynamic_llm = ChatAnthropic(
                            model=actual_model,
                            temperature=0,
                            anthropic_api_key=self.custom_key if self.custom_key else os.getenv("ANTHROPIC_API_KEY")
                        )
                        ai_response = dynamic_llm.invoke(prompt)
                        text = ai_response.content.strip()

                    elif "gemini" in actual_model:
                        from langchain_google_genai import ChatGoogleGenerativeAI
                        dynamic_llm = ChatGoogleGenerativeAI(
                            model=actual_model,
                            temperature=0,
                            google_api_key=self.custom_key if self.custom_key else os.getenv("GOOGLE_API_KEY")
                        )
                        ai_response = dynamic_llm.invoke(prompt)
                        text = ai_response.content.strip()

                    elif "deepseek" in actual_model:
                        dynamic_llm = ChatOpenAI(
                            model=actual_model,
                            temperature=0,
                            openai_api_key=self.custom_key if self.custom_key else os.getenv("DEEPSEEK_API_KEY"),
                            openai_api_base="https://api.deepseek.com/v1"
                        )
                        ai_response = dynamic_llm.invoke(prompt)
                        text = ai_response.content.strip()

                    elif "gpt" in actual_model or "openai" in actual_model:
                        dynamic_llm = ChatOpenAI(
                            model=actual_model,
                            temperature=0,
                            openai_api_key=self.custom_key if self.custom_key else self.openai_key
                        )
                        ai_response = dynamic_llm.invoke(prompt)
                        text = ai_response.content.strip()
                    else:
                        raise ValueError(
                            f"Custom cloud provider mapping failed: Identifier '{actual_model}' "
                            f"does not match any recognized provider keyword (claude, gemini, deepseek, gpt)."
                        )

                elif str(target_model).startswith("ollama://"):
                    actual_model = target_model.replace("ollama://", "")
                    print(f"📦 [QuerySense] Dynamic Routing payload to Custom Local Ollama model: {actual_model}")
                    payload = {
                        "model": actual_model,
                        "prompt": prompt,
                        "stream": False,
                        "options": {"temperature": 0.0}
                    }
                    resp = requests.post(self.url, json=payload, timeout=600)
                    resp.raise_for_status()
                    text = resp.json().get("response", "").strip()
                

                else:
                    raise ValueError(f"Requested model '{target_model}' has no active route configuration.")    
    
                print(f"\n🔍 DEBUG LLM RAW OUTPUT:\n{text}\n")
                # Logic: Find the FIRST '{' and LAST '}'
                import re
            # This regex finds everything between the first { and the last }
                match = re.search(r'(\{.*\})', text, re.DOTALL)
            
                if match:
                # Use match.group(1) to get only the JSON part
                    return json.loads(match.group(1))
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
        def _fallback_simple(self, query: str) -> Dict[str, Any]:
            ql = query.lower()
            words = re.findall(r"\b[a-zA-Z_]{3,}\b", ql)
            resolved = []

            for t, meta in self.schema["tables"].items():
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

            tables = sorted({c.split(".")[0] for c in resolved})

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
        
        def _validate_plan(self, plan: Dict[str, Any]) -> Dict[str, Any]:
            sanitized = {
                "tables": [], "columns": [], "intent": "SELECTION",
                "aggregations": [], "group_by": [], "joins": [],
                "filters": [], "order_by": [], "limit": 0,
            }

            if not isinstance(plan, dict):
                return sanitized

            # --- KEY FIX: Case-Insensitive Table Mapping ---
            for t_llm in plan.get("tables", []):
                # Look for a match in schema regardless of case
                match = next((real_t for real_t in self.schema.get("tables", {}) 
                             if real_t.lower() == t_llm.lower()), None)
                if match:
                    sanitized["tables"].append(match)

            # --- KEY FIX: Case-Insensitive Column Mapping ---
            for c_llm in plan.get("columns", []):
                if isinstance(c_llm, str) and "." in c_llm:
                    t_llm, col_llm = c_llm.split(".", 1)
                    # Find the real table name
                    real_t = next((rt for rt in self.schema.get("tables", {}) 
                                 if rt.lower() == t_llm.lower()), None)
                    if real_t:
                        # Find the real column name
                        real_col = next((rc for rc in self.schema["tables"][real_t].get("columns", {}) 
                                       if rc.lower() == col_llm.lower()), None)
                        if real_col:
                            sanitized["columns"].append(f"{real_t}.{real_col}")

            # Keep the rest of your intent/limit logic as is...
            sanitized["intent"] = (plan.get("intent") or "SELECTION").upper()
            sanitized["limit"] = int(plan.get("limit") or 0)
            
            return sanitized

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

        def analyze(self, user_query: str,target_model: str,system_instructions: str = "") -> Dict[str, Any]:
            self.state["timestamp"] = datetime.now().isoformat()
            self.state["user_query"] = user_query

            plan = self._call_llm_for_plan(user_query,target_model,system_instructions)
            if not plan:
                plan = self._fallback_simple(user_query)

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
        self.query_sense.custom_key = custom_key
        self.query_sense.model = chosen_model
        analysis = self.query_sense.analyze(simplified_query,chosen_model,system_instructions)

        state["query_sense_output"] = analysis
        state["current_step"] = "query_sense"
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
