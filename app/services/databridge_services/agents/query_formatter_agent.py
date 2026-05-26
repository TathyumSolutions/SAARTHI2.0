# """
# QueryFormatterAgent - Executes SQL and formats results
# """
# from typing import Dict, Any
# from format_decider import FormatDecider


# class QueryFormatterAgent:
#     """
#     Agent responsible for query execution and result formatting.
#     Executes SQL queries and decides output format.
#     """
    
#     def __init__(self):
#         self.format_decider = FormatDecider()
    
#     def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
#         """
#         Execute the agent: run SQL query and format results.
        
#         Args:
#             state: Current state dictionary containing 'generated_sql'
            
#         Returns:
#             Updated state with query results
#         """
#         print(f"\n🤖 [QueryFormatterAgent] Starting...")
        
#         generated_sql = state.get("generated_sql", "")
#         user_query = state.get("user_query", "")
        
#         # Execute query
#         result = self.format_decider.execute_query(generated_sql, user_query)
        
#         # Update state with results
#         state["query_results"] = result
#         state["row_count"] = result.get("row_count", 0)
#         state["columns"] = result.get("columns", [])
#         state["data"] = result.get("data", [])
#         state["format"] = result.get("format", "unknown")
#         state["case"] = result.get("case")
#         state["message"] = result.get("message", "")
#         state["current_step"] = "query_formatter"
        
#         print(f"✅ [QueryFormatterAgent] Executed query: {state['row_count']} rows")
#         return state


# dec8 code, to handle the anomaly type of question
# """
# QueryFormatterAgent - Executes SQL and formats results
# """
# from typing import Dict, Any
# from format_decider import FormatDecider


# class QueryFormatterAgent:
#     """
#     Agent responsible for query execution and result formatting.
#     Executes SQL queries and decides output format.
#     """
    
#     def __init__(self):
#         self.format_decider = FormatDecider()
    
#     def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
#         """
#         Execute the agent: run SQL query and format results.
        
#         Args:
#             state: Current state dictionary containing 'generated_sql'
            
#         Returns:
#             Updated state with query results
#         """
#         print(f"\n🤖 [QueryFormatterAgent] Starting...")
        
#         generated_sql = state.get("generated_sql", "")
#         user_query = state.get("user_query", "")
        
#         # Execute query
#         result = self.format_decider.execute_query(generated_sql, user_query)
        
#         # Raw fields passed forward
#         state["query_results"] = result
#         state["row_count"] = result.get("row_count", 0)
#         state["columns"] = result.get("columns", [])
#         state["data"] = result.get("data", [])
#         state["format"] = result.get("format", "unknown")
#         state["case"] = result.get("case")
#         state["message"] = result.get("message", "")
#         state["current_step"] = "query_formatter"
        
#         # ----------------------------------------------------------
#         # UNIVERSAL NORMALIZATION LOGIC
#         # ----------------------------------------------------------
#         normalized = self._normalize_result(result)
#         state["normalized_result"] = normalized
        
#         print(f"ℹ️ [QueryFormatterAgent] Normalized result: {normalized}")
#         print(f"✅ [QueryFormatterAgent] Executed query: {state['row_count']} rows")
        
#         return state

#     # --------------------------------------------------------------
#     # Helper method for universal normalization
#     # --------------------------------------------------------------
#     def _normalize_result(self, result: Dict[str, Any]):
#         """
#         Convert any SQL result into a clean, predictable format.
#         Works for single rows, single values, JSON fields, etc.
#         """
#         data = result.get("data")

#         # Case 1: No data returned
#         if not data:
#             return None

#         # Case 2: Exact single row
#         if isinstance(data, list) and len(data) == 1:
#             row = data[0]

#             # If row is a single value in dict form
#             if isinstance(row, dict) and len(row.keys()) == 1:
#                 return list(row.values())[0]  # return the value only
            
#             # If row is dict with multiple values → return the full row
#             if isinstance(row, dict):
#                 return row

#             # If row is a scalar (rare but possible)
#             return row

#         # Case 3: Multi-row results → return the entire dataset
#         return data



# dec10 code to make it complete langgraph
# """
# QueryFormatterAgent - Self-contained agent
# Executes SQL and formats results with optional insights and charts
# """
# from typing import Dict, Any
# import os
# import pandas as pd
# import psycopg2
# from dotenv import load_dotenv
# from sqlalchemy import create_engine
# import json
# import requests

# class DataInsightGeneratorAgent:
#     """
#     Embedded DataInsightGenerator for QueryFormatterAgent
#     """
#     def __init__(self, llm_url: str = "http://localhost:11434/api/generate", model: str = "llama3:latest"):
#         self.llm_url = llm_url
#         self.model = model

#     def generate_insights(self, data, columns, user_query=""):
#         if not data:
#             return {"insights": ["No data available to analyze."], "visualizations": []}

#         df = pd.DataFrame(data)
#         summary = df.describe(include='all').to_string()
#         sample_data = df.head(5).to_string()

#         prompt = f"""
# You are a Data Analyst expert. Analyze the dataset and provide 3-5 key insights.
# Suggest the best 2 visualization types with brief reasons.

# User Query: "{user_query}"
# Data Columns: {columns}

# Data Summary:
# {summary}

# Sample Data (first 5 rows):
# {sample_data}

# Output Format (JSON):
# {{
#     "insights": ["insight 1", "insight 2", ...],
#     "visualizations": [
#         {{"type": "Bar Chart", "reason": "..."}},
#         {{"type": "Line Chart", "reason": "..."}}
#     ]
# }}

# Return ONLY valid JSON.
# """
#         payload = {"model": self.model, "prompt": prompt, "stream": False, "format": "json"}

#         try:
#             resp = requests.post(self.llm_url, json=payload, timeout=60)
#             resp.raise_for_status()
#             result = resp.json().get("response", "")
#             try:
#                 return json.loads(result)
#             except json.JSONDecodeError:
#                 if "```json" in result:
#                     json_str = result.split("```json")[1].split("```")[0].strip()
#                     return json.loads(json_str)
#                 return {"insights": ["Could not parse insights from LLM."], "visualizations": [], "raw_response": result}
#         except Exception as e:
#             return {"insights": [], "visualizations": [], "error": str(e)}

# class QueryFormatterAgent:
#     """
#     Self-contained agent to execute SQL and format results
#     """
#     def __init__(self, env_path: str = ".env", llm_url: str = "http://localhost:11434/api/generate", model: str = "llama3:latest"):
#         # Load DB credentials
#         load_dotenv(env_path)
#         self.db_config = {
#             "host": os.getenv("PGHOST"),
#             "port": os.getenv("PGPORT"),
#             "dbname": os.getenv("PGDATABASE"),
#             "user": os.getenv("PGUSER"),
#             "password": os.getenv("PGPASSWORD")
#         }
#         self.state = {}
#         self.insight_generator = DataInsightGeneratorAgent(llm_url=llm_url, model=model)

#     def _connect_db(self):
#         return psycopg2.connect(**self.db_config)

#     def execute_query(self, sql_query: str, user_query: str = "") -> dict:
#         if not sql_query or not sql_query.strip():
#             return {"format": "error", "message": "❌ No valid SQL query provided."}

#         try:
#             db_url = f"postgresql+psycopg2://{self.db_config['user']}:{self.db_config['password']}@{self.db_config['host']}:{self.db_config['port']}/{self.db_config['dbname']}"
#             engine = create_engine(db_url)
#             df = pd.read_sql_query(sql_query, engine)
#             engine.dispose()
#         except Exception as e:
#             return {"format": "error", "message": f"❌ Query execution failed: {str(e)}", "query": sql_query}

#         row_count = len(df)
#         col_count = len(df.columns)
#         insights_data = {}
#         chart_configs = {"bar": {}, "line": {}, "pie": {}, "recommended": "bar"}

#         # Determine format
#         if row_count <= 2 and col_count <= 3:
#             format_type = "kpi"
#             case_type = "single_output"
#             message = f"✅ {row_count} record(s) fetched. Display as KPI or summary table."
#         elif row_count < 4:
#             format_type = "table"
#             case_type = "single_output"
#             message = f"✅ {row_count} record(s) fetched. Display as small table."
#         else:
#             format_type = "table" if row_count < 50 else "chart"
#             case_type = "multi_output"
#             message = f"📊 {row_count} rows fetched. Suitable for chart/table visualization."
#             data_records = df.to_dict(orient="records")
#             columns_list = list(df.columns)
#             insights_data = self.insight_generator.generate_insights(data_records, columns_list, user_query)
#             # Chart configs: simplified to placeholder if visualizations exist
#             if insights_data.get("visualizations"):
#                 chart_configs = {**chart_configs, "recommended": "bar"}

#         result = {
#             "case": case_type,
#             "format": format_type,
#             "columns": list(df.columns),
#             "row_count": row_count,
#             "data": df.to_dict(orient="records"),
#             "message": message,
#             "insights": insights_data.get("insights", []),
#             "visualizations": insights_data.get("visualizations", []),
#             "chart_configs": chart_configs
#         }

#         self.state["last_result"] = result
#         return result

#     def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
#         print(f"\n🤖 [QueryFormatterAgent] Starting...")
#         generated_sql = state.get("generated_sql", "")
#         user_query = state.get("user_query", "")

#         result = self.execute_query(generated_sql, user_query)
#         state["query_results"] = result
#         state["row_count"] = result.get("row_count", 0)
#         state["columns"] = result.get("columns", [])
#         state["data"] = result.get("data", [])
#         state["format"] = result.get("format", "unknown")
#         state["case"] = result.get("case")
#         state["message"] = result.get("message", "")
#         state["insights"] = result.get("insights", [])
#         state["visualizations"] = result.get("visualizations", [])
#         state["chart_configs"] = result.get("chart_configs", {})
#         state["current_step"] = "query_formatter"

#         print(f"✅ [QueryFormatterAgent] Executed query: {state['row_count']} rows")
#         return state

"""
QueryFormatterAgent - Self-contained agent with enhanced debugging
Executes SQL and formats results with optional insights and charts
"""
from typing import Dict, Any
import os
import pandas as pd
import psycopg2
from dotenv import load_dotenv
from sqlalchemy import create_engine
import json
import requests
import traceback
import re


class DataInsightGeneratorAgent:
    """
    Embedded DataInsightGenerator for QueryFormatterAgent
    """
    def __init__(self, llm_url: str = "http://localhost:11434/api/generate", model: str = "llama3:latest"):
        self.llm_url = llm_url
        self.model = model

    def generate_insights(self, data, columns, user_query=""):
        if not data:
            return {"insights": ["No data available to analyze."], "visualizations": []}

        df = pd.DataFrame(data)
        summary = df.describe(include='all').to_string()
        sample_data = df.head(5).to_string()

        prompt = f"""
You are a Data Analyst expert. Analyze the dataset and provide 3–5 key insights.
Suggest the best 2 visualization types with brief reasons.

User Query: "{user_query}"
Data Columns: {columns}

Data Summary:
{summary}

Sample Data (first 5 rows):
{sample_data}

Return ONLY valid JSON.
"""

        payload = {"model": self.model, "prompt": prompt, "stream": False, "format": "json"}

        try:
            resp = requests.post(self.llm_url, json=payload, timeout=60)
            resp.raise_for_status()
            result = resp.json().get("response", "")
            try:
                return json.loads(result)
            except json.JSONDecodeError:
                return {"insights": ["Could not parse insights."], "visualizations": [], "raw_response": result}
        except Exception as e:
            return {"insights": [], "visualizations": [], "error": str(e)}


class QueryFormatterAgent:
    """
    Self-contained agent to execute SQL and format results, with deep debugging
    """
    def __init__(self, env_path: str = ".env", llm_url: str = "http://ollama:11434/api/generate", model: str = "llama3:latest"):
        load_dotenv(env_path)
        self.db_config = {
            #"host": os.getenv("PGHOST"),
            #"port": os.getenv("PGPORT"),
            #"dbname": os.getenv("PGDATABASE"),
            #"user": os.getenv("PGUSER"),
            #"password": os.getenv("PGPASSWORD")
            "host": "db",
            "port": "5432",
            "dbname":"databrige_db" ,
            "user": "saarthi",
            "password": "password"

        }
        self.state = {}
        self.insight_generator = DataInsightGeneratorAgent(llm_url=llm_url, model=model)

    def execute_query(self, sql_query: str, user_query: str = "") -> dict:

        if sql_query:
            sql_query = sql_query.replace("```sql", "").replace("```", "").strip()

            match = re.search(r"(SELECT|INSERT|UPDATE|DELETE)[\s\S]+", sql_query, re.IGNORECASE)
            if match:
                sql_query = match.group(0).strip()
            if ";" in sql_query:
                sql_query = sql_query.split(";")[0].strip() + ";"
            sql_query = sql_query.replace("```sql", "").replace("```", "").strip()    
    
        if not sql_query.strip():
            error_result = {
                "status": "error",
                "format": "error",
                "message": "❌ No valid SQL query provided.",
                "query": sql_query
            }
            print("\n[DEBUG] Returning error (empty SQL):", json.dumps(error_result, indent=4))
            return error_result

        try:
            db_url = (
                f"postgresql+psycopg2://{self.db_config['user']}:{self.db_config['password']}@"
                f"{self.db_config['host']}:{self.db_config['port']}/{self.db_config['dbname']}"
            )
            engine = create_engine(db_url)
            df = pd.read_sql_query(sql_query, engine)
            engine.dispose()

        except Exception as e:
            error_result = {
                "status": "error",
                "format": "error",
                "message": f"❌ Query execution failed: {str(e)}",
                "trace": traceback.format_exc(),
                "query": sql_query
            }
            print("\n[DEBUG] Returning query execution error:", json.dumps(error_result, indent=4))
            return error_result

        row_count = len(df)
        col_count = len(df.columns)

        # ZERO ROWS → SUCCESS
        if row_count == 0:
            success_zero = {
                "status": "success",
                "format": "empty",
                "case": "no_data",
                "message": "No results found.",
                "columns": list(df.columns),
                "row_count": 0,
                "data": [],
                "insights": [],
                "visualizations": [],
                "chart_configs": {},
                "query": sql_query
            }
            print("\n[DEBUG] Returning EMPTY result:", json.dumps(success_zero, indent=4))
            return success_zero

        # NORMAL SUCCESS CASE
        df.columns = [
            f"{col}_{i}" if list(df.columns).count(col) > 1 else col
            for i, col in enumerate(df.columns)]
        insights_data = {}
        chart_configs = {"bar": {}, "line": {}, "pie": {}, "recommended": "bar"}

        if row_count <= 1 and col_count <= 3:
            format_type = "kpi"
            case_type = "single_output"
            message = f"✅ {row_count} record(s) fetched. Display as KPI or summary."
            data_records = df.to_dict(orient="records")
            columns_list = list(df.columns)
            
            raw_insights = self.insight_generator.generate_insights(
                data_records, columns_list, user_query
            )
            
            # FIX: Ensure it always builds a dict with BOTH keys so the bottom code doesn't break
            if isinstance(raw_insights, dict):
                insights_data = {
                    "insights": raw_insights.get("insights", []),
                    "visualizations": raw_insights.get("visualizations", [])
                }
            else:
                insights_data = {
                    "insights": raw_insights if isinstance(raw_insights, list) else ["Data fetched successfully."],
                    "visualizations": []
                }
            
            
        elif row_count < 4:
            format_type = "table"
            #case_type = "single_output"
            case_type = "multi_output"  # Highly recommended for tables
            message = f"✅ {row_count} record(s) fetched."

            chart_configs = {"bar": {}, "line": {}, "pie": {}, "recommended": ""}
            
            data_records = df.to_dict(orient="records")
            columns_list = list(df.columns)
            raw_insights = self.insight_generator.generate_insights(
                data_records, columns_list, user_query
            )
            if isinstance(raw_insights, dict):
                insights_data = {
                    "insights": raw_insights.get("insights", []),
                    "visualizations": raw_insights.get("visualizations", [])
                }
            else:
                # Safe structure placeholder container payload normalization
                insights_data = {
                    "insights": raw_insights if isinstance(raw_insights, list) else [],
                    "visualizations": []
                }
            
            
        else:
            format_type = "table" if row_count < 50 else "chart"
            case_type = "multi_output"
            message = f"📊 {row_count} rows fetched."

            data_records = df.to_dict(orient="records")
            columns_list = list(df.columns)

            insights_data = self.insight_generator.generate_insights(
                data_records, columns_list, user_query
            )



        result = {
            "status": "success",
            "case": case_type,
            "format": format_type,
            "columns": list(df.columns),
            "row_count": row_count,
            "data": df.to_dict(orient="records"),
            "message": message,
            "insights": insights_data.get("insights", []),
            "visualizations": insights_data.get("visualizations", []),
            "chart_configs": chart_configs,
            "query": sql_query
        }

        # print("\n[DEBUG] Returning SUCCESS result:", json.dumps(result, indent=4))
        return result

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        print("\n🤖 [QueryFormatterAgent] Starting...")
        # print("[DEBUG] Incoming state:", json.dumps(state, indent=4))
        if "steps" not in state or state.get("steps") is None:
            state["steps"] = []

        generated_sql = state.get("generated_sql", "")
        user_query = state.get("user_query", "")

        result = self.execute_query(generated_sql, user_query)

        # print("\n[DEBUG] OUTBOUND result to router:", json.dumps(result, indent=4))

        # Write result back into state
        state.update({
            "query_results": result,
            #"row_count": result.get("row_count", 0),
            "row_count": int(result.get("row_count")) if (result.get("row_count") is not None and str(result.get("row_count")).isdigit()) else 0,
            "columns": result.get("columns", []),
            "data": result.get("data", []),
            "format": result.get("format", "unknown"),
            "case": result.get("case"),
            "message": result.get("message", ""),
            "insights": result.get("insights", []),
            "visualizations": result.get("visualizations", []),
            "chart_configs": result.get("chart_configs", {}),
            "query": result.get("query", generated_sql),
            "status": result.get("status", "unknown"),
            "current_step": "query_formatter"
        })

        row_count = state.get('row_count', 0)
        status = state.get('status', 'unknown')

        state["steps"].append(
            f"QueryFormatter: Query Execution: {status.upper()}. Successfully retrieved {row_count} rows and formatted the response."
        )
        
        query_sense_output = state.get("query_sense_output", {})
        query_sense_output["steps"] = state["steps"]
        state["query_sense_output"] = query_sense_output

        print(f"✅ [QueryFormatterAgent] Executed query: {state['row_count']} rows")
        # print("[DEBUG] Updated state returned to router:", json.dumps(state, indent=4))

        return state
