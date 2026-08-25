# """
# SQLGeneratorAgent - Generates SQL queries from intent
# """
# from typing import Dict, Any
# from sql_generator import generate_sql_from_querysense


# class SQLGeneratorAgent:
#     """
#     Agent responsible for SQL generation.
#     Converts query intent into executable SQL.
#     """
    
#     def __init__(self, llm_backend: Dict[str, Any]):
#         self.llm_backend = llm_backend
    
#     def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
#         """
#         Execute the agent: generate SQL query.
        
#         Args:
#             state: Current state dictionary
            
#         Returns:
#             Updated state with 'generated_sql'
#         """
#         print(f"\n🤖 [SQLGeneratorAgent] Starting...")
        
#         try:
#             user_query = state.get("user_query", "")
#             query_sense_output = state.get("query_sense_output", {})
#             simplified_query = state.get("simplified_query", user_query)
            
#             # Get error feedback if this is a retry
#             error_feedback = state.get("error_feedback", "")
            
#             sql = generate_sql_from_querysense(
#                 user_query,
#                 query_sense_output,
#                 self.llm_backend,
#                 simplified_query=simplified_query
#             )
            
#             # Check if SQL was generated
#             if not sql or sql.strip() == "":
#                 print(f"⚠️ [SQLGeneratorAgent] No SQL generated!")
#                 state["error"] = "SQL generation failed - LLM returned empty response"
#                 state["generated_sql"] = None
#             else:
#                 state["generated_sql"] = sql
#                 print(f"✅ [SQLGeneratorAgent] Generated SQL: {sql[:100]}...")
            
#             state["current_step"] = "sql_generator"
            
#         except Exception as e:
#             print(f"❌ [SQLGeneratorAgent] Error: {str(e)}")
#             state["error"] = f"SQL generation failed: {str(e)}"
#             state["generated_sql"] = None
#             state["current_step"] = "sql_generator"
        
#         return state


    # current code



from typing import Dict, Any
import requests
import json
import os
import time
from langchain_openai import ChatOpenAI
from app.services.bi_semantics_service import build_measure_guidance
from app.services.llm_call_logger import tracked_invoke, record_llm_call


class SQLGeneratorAgent:
    """
    Agent responsible for SQL generation.
    Converts query intent into executable SQL using LLM (Ollama-safe).
    """

    def __init__(self, llm_backend: Dict[str, Any]):
        self.llm_backend = llm_backend

        self.openai_key = os.getenv("OPENAI_API_KEY")
        self.custom_key = ""

    def _parse_ollama_ndjson(self, raw_text: str) -> str:
        """
        Handles Ollama NDJSON responses and concatenates all 'response' chunks.
        Returns the full model text output.
        """

        lines = raw_text.strip().splitlines()
        chunks = []

        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                chunks.append(obj)
            except json.JSONDecodeError:
                # Ignore malformed lines instead of crashing
                continue

        # Collect streamed response text
        full_text = ""

        for obj in chunks:
            # Native Ollama: streaming chunks
            if "response" in obj:
                full_text += obj["response"]
            # OpenAI compatibility mode (rare but possible)
            elif "message" in obj and "content" in obj["message"]:
                full_text += obj["message"]["content"]
            elif "text" in obj:
                full_text += obj["text"]
            elif "completion" in obj:
                full_text += obj["completion"]

        return full_text.strip()

    def _extract_ollama_usage(self, raw_text: str):
        """Ollama's token counts (prompt_eval_count/eval_count) land on
        whichever JSON object has done=true - the single object for a
        normal stream=False response, or the last line for the NDJSON
        fallback _parse_ollama_ndjson handles. Returns (None, None) if
        neither count is found anywhere in the payload."""
        prompt_tokens = completion_tokens = None
        for line in raw_text.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "prompt_eval_count" in obj:
                prompt_tokens = obj["prompt_eval_count"]
            if "eval_count" in obj:
                completion_tokens = obj["eval_count"]
        return prompt_tokens, completion_tokens

    def generate_sql_from_querysense(
        self,
        user_query: str,
        query_sense_output: Dict[str, Any],
        simplified_query: str,
        error_feedback: str = "",
        target_model: str = "llama3",
        system_instructions: str = "",
        bi_semantics_hint: str = "",
        feedback_context: str = "",
        user_id=None,

    ) -> str:
        """Generate SQL from QuerySense output using LLM (Ollama-safe)"""


        try:
            self_learning_block = ""
            if feedback_context:
                self_learning_block = f"""
{feedback_context}

The block above is feedback on how PAST similar questions were answered -
it is NOT part of the current question. It can describe any kind of
problem: a missing/wrong WHERE filter, wrong JOIN, wrong aggregation or
GROUP BY, wrong columns selected, wrong sort/limit, or a data-quality
issue (placeholder/"not applicable" values like "n/a" that should be
excluded). If a DISLIKED note is still relevant to this question, adjust
the SQL to address it - using ONLY tables/columns present in QUERY SENSE
OUTPUT above, never inventing one. If a LIKED note confirms a past
approach worked, prefer reusing it when it fits. Ignore anything in the
feedback that doesn't apply to this specific question.
"""

            prompt = f"""
You are a strict PostgreSQL query generator.

USER QUERY: {user_query}
SIMPLIFIED QUERY: {simplified_query}
QUERY SENSE OUTPUT:
{json.dumps(query_sense_output, indent=2)}
ERROR FEEDBACK: {error_feedback}
{bi_semantics_hint}
{self_learning_block}

STRICT RULES:
1. Use ONLY tables and columns present in Query Sense Output, or a measure column named in BI SEMANTICS GUIDANCE above (if present). Nothing else.
2. NEVER invent columns like some_metric, score, rank, total_amount unless in Query Sense Output or explicitly named in BI SEMANTICS GUIDANCE.
3. Use PostgreSQL syntax ONLY.
4. Output ONLY raw executable PostgreSQL query. No markdown, no backticks, no explanation.
5.DO NOT append explanations, notes, or reasoning about why clauses were included or skipped.
6. If a clause like ORDER BY or WHERE is not explicitly needed, do not type the keyword. Completely omit it.
7. NEVER generate "ORDER BY LIMIT". If an ORDER BY clause is included, it MUST specify a column name
8. Never alter the logical intent of the user's question to force a successful database execution. If the exact requested columns are unavailable, generate the query using the user's requested column name exactly as asked, even if it results in a database execution error.
9. FORCE SYNTAX FAILURE: If the requested column is missing from the schema, you must still write the query using that exact missing column name (e.g., SELECT ghost_count FROM mara;). Let the database engine handle the error. Do not attempt to fix or bypass it
10. Generate ONE query only.

JOIN RULES:
- Use joins ONLY if present in Query Sense Output joins field.
- Join ONLY on the exact columns specified in joins field.
- NEVER change join columns.
- NEVER join columns with different data types.
- If joins field is empty, use single table query.

AGGREGATION RULES:
- Use GROUP BY only if aggregations exist in Query Sense Output.
- Use ORDER BY + LIMIT for top N queries, NOT RANK().
- NEVER use RANK(), ROW_NUMBER() unless explicitly requested.

POSTGRESQL RULES:
- Use LIMIT not TOP.
- Use :: for type casting if needed.
- Use ILIKE for case insensitive search.
- Use NOW() not GETDATE().

OUTPUT FORMAT:
SELECT ... FROM ... JOIN ... ON ... WHERE ... GROUP BY ... ORDER BY ... LIMIT ...;

Return ONLY the PostgreSQL query, nothing else.
"""         
            if system_instructions.strip():
                prompt += f"\n\nUSER CUSTOM FORMATTING INSTRUCTIONS:\n{system_instructions}"

            prompt += "\n\nReturn ONLY the PostgreSQL query, nothing else.\n"

            if target_model == "gpt-4o":
                print("🔥 [SQLGeneratorAgent] Routing to ChatOpenAI [gpt-4o] Layer...")
                
                llm = ChatOpenAI(
                model="gpt-4o",
                temperature=0.0,
                openai_api_key=self.openai_key
                )
                ai_response = tracked_invoke(
                    llm, prompt, purpose="sql_generator.generate_sql", model_name="gpt-4o",
                    provider="openai", user_id=user_id,
                )
                raw_sql = ai_response.content.strip()

            elif target_model == "gpt-4o-mini":
                print("🤖 [SQLGeneratorAgent] Routing to ChatOpenAI [gpt-4o-mini] Layer...")

                llm = ChatOpenAI(
                model="gpt-4o-mini",
                temperature=0.0,
                openai_api_key=self.openai_key
                )
                ai_response = tracked_invoke(
                    llm, prompt, purpose="sql_generator.generate_sql", model_name="gpt-4o-mini",
                    provider="openai", user_id=user_id,
                )
                raw_sql = ai_response.content.strip()

            elif target_model == "llama3":
                print("🦙 [SQLGeneratorAgent] Routing to local Ollama [llama3] container layer...")
                payload = {
                "model": "llama3",  # Forces local Llama 3 image call explicitly
                "prompt": prompt,
                "stream": False,
                "max_tokens": self.llm_backend.get("max_tokens", 1024),
                "temperature": self.llm_backend.get("temperature", 0.0)
                }
                _t0 = time.monotonic()
                response = requests.post(
                self.llm_backend["url"],
                json=payload,
                timeout=self.llm_backend.get("timeout", 300)
                )
                response.raise_for_status()
                raw_text = response.text
                raw_sql = self._parse_ollama_ndjson(raw_text)
                _p_tok, _c_tok = self._extract_ollama_usage(raw_text)
                record_llm_call(
                    purpose="sql_generator.generate_sql", model_name="llama3", provider="ollama",
                    prompt_text=prompt, response_text=raw_sql,
                    prompt_tokens=_p_tok, completion_tokens=_c_tok,
                    duration_ms=int((time.monotonic() - _t0) * 1000), user_id=user_id,
                )

            elif str(target_model).startswith("api://"):
                actual_model = target_model.replace("api://", "").lower()
                print(f"🌐 [SQLGeneratorAgent] Dynamic Routing payload to Custom Cloud API model: {actual_model}")

                from app.services.llm_providers import resolve_dynamic_llm
                dynamic_llm = resolve_dynamic_llm(
                    actual_model,
                    self.custom_key,
                    temperature=0,
                    openai_fallback_key=self.openai_key,
                    strict=True,
                )
                ai_response = tracked_invoke(
                    dynamic_llm, prompt, purpose="sql_generator.generate_sql", model_name=actual_model,
                    user_id=user_id,
                )
                raw_sql = ai_response.content.strip()

            elif str(target_model).startswith("ollama://"):
                actual_model = target_model.replace("ollama://", "")
                print(f"📦 [SQLGeneratorAgent] Dynamic Routing payload to Custom Local Ollama model: {actual_model}")
                payload = {
                    "model": actual_model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.0}
                }
                _t0 = time.monotonic()
                response = requests.post(self.llm_backend["url"], json=payload, timeout=300)
                response.raise_for_status()
                raw_text = response.text
                if "{" in raw_text and "}" in raw_text:
                    raw_sql = self._parse_ollama_ndjson(raw_text)
                else:
                    raw_sql = raw_text.strip()
                _p_tok, _c_tok = self._extract_ollama_usage(raw_text)
                record_llm_call(
                    purpose="sql_generator.generate_sql", model_name=actual_model, provider="ollama",
                    prompt_text=prompt, response_text=raw_sql,
                    prompt_tokens=_p_tok, completion_tokens=_c_tok,
                    duration_ms=int((time.monotonic() - _t0) * 1000), user_id=user_id,
                )
            else:
                raise ValueError(f"Requested model '{target_model}' has no active route configuration.") 
            # Cleanup: remove JSON/object-like lines or explanations
            sql_lines = [
                line.strip()
                for line in raw_sql.splitlines()
                if line.strip() and not line.strip().startswith("{") and not line.strip().startswith("}")
            ]

            sql = " ".join(sql_lines)

            return sql.strip()

        except Exception as e:
            print(f"❌ [SQLGeneratorAgent] LLM SQL generation error: {e}")
            return ""

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """LangGraph-compatible execute method"""
        print(f"\n🤖 [SQLGeneratorAgent] Starting...")

        try:
            if "steps" not in state:
                state["steps"] = []
            user_query = state.get("user_query", "")
            query_sense_output = state.get("query_sense_output", {})
            simplified_query = state.get("simplified_query", user_query)
            error_feedback = state.get("error_feedback", "")

            chosen_model = state.get("model_name", self.llm_backend["model"])
            custom_key = state.get("custom_key", "")
            system_instructions = state.get("system_instructions", "")
            feedback_context = state.get("feedback_context", "")
            self.custom_key = custom_key

            if feedback_context:
                print(f"🧠 [FEEDBACK-DEBUG] [SQL] Using feedback context for SQL generation:\n{feedback_context}")

            # Consult the BI semantics config (app/services/bi_semantics_service.py)
            # for the tables this question touches: if QuerySense found no
            # explicit aggregation, a business entity like "sales orders" should
            # default to SUM(net_value) rather than a raw row per order that
            # degenerates into a meaningless one-count-per-row chart downstream.
            try:
                bi_semantics_hint = build_measure_guidance(
                    query_sense_output.get("tables") or [],
                    query_sense_output,
                    user_id=state.get("user_id", 1),
                )
            except Exception as e:
                print(f"⚠️ [SQLGeneratorAgent] BI semantics lookup failed: {e}")
                bi_semantics_hint = ""

            sql = self.generate_sql_from_querysense(
                user_query,
                query_sense_output,
                simplified_query,
                error_feedback,
                chosen_model,
                system_instructions=system_instructions,
                bi_semantics_hint=bi_semantics_hint,
                feedback_context=feedback_context,
                user_id=state.get("user_id"),
            )

            if not sql:
                print(f"⚠️ [SQLGeneratorAgent] No SQL generated!")
                state["error"] = "SQL generation failed - LLM returned empty response"
                state["generated_sql"] = None
            else:
                state["generated_sql"] = sql
                print(f"✅ [SQLGeneratorAgent] Generated SQL: {sql[:100]}...")

                extra_narration_prompt = f"""
                You are a professional SAP Data Analyst. Describe the SQL query logic in one beautiful sentence.
                ### EXAMPLE:
                Query: "top 5 materials"
                SQL: "SELECT * FROM mara LIMIT 5"
                Output: I have constructed an optimized query to retrieve the first five records from the material master table.
                
                ### YOUR TASK:
                Query: "{simplified_query}"
                SQL: "{sql}"
                Output:
                """
                
                try:
                    _uid = state.get("user_id")
                    if chosen_model == "gpt-4o":

                        llm = ChatOpenAI(
                        model="gpt-4o",
                        temperature=0.3,
                        openai_api_key=self.openai_key
                        )
                        description = tracked_invoke(
                            llm, extra_narration_prompt, purpose="sql_generator.narration",
                            model_name="gpt-4o", provider="openai", user_id=_uid,
                        ).content.strip()

                    elif chosen_model == "gpt-4o-mini":

                        llm = ChatOpenAI(
                        model="gpt-4o-mini",
                        temperature=0.3,
                        openai_api_key=self.openai_key
                        )
                        description = tracked_invoke(
                            llm, extra_narration_prompt, purpose="sql_generator.narration",
                            model_name="gpt-4o-mini", provider="openai", user_id=_uid,
                        ).content.strip()

                    elif chosen_model == "llama3":
                        _t0 = time.monotonic()
                        resp = requests.post(self.llm_backend["url"], json={
                        "model": "llama3",
                        "prompt": extra_narration_prompt,
                        "stream": False,
                        "temperature": 0.3
                        }, timeout=300)
                        resp_json = resp.json()
                        description = resp_json.get("response", "").strip()
                        record_llm_call(
                            purpose="sql_generator.narration", model_name="llama3", provider="ollama",
                            prompt_text=extra_narration_prompt, response_text=description,
                            prompt_tokens=resp_json.get("prompt_eval_count"), completion_tokens=resp_json.get("eval_count"),
                            duration_ms=int((time.monotonic() - _t0) * 1000), user_id=_uid,
                        )
                    elif str(chosen_model).startswith("api://"):
                        actual_model = chosen_model.replace("api://", "").lower()

                        from app.services.llm_providers import resolve_dynamic_llm
                        dynamic_llm = resolve_dynamic_llm(
                            actual_model,
                            self.custom_key,
                            temperature=0.3,
                            openai_fallback_key=self.openai_key,
                            strict=True,
                        )
                        description = tracked_invoke(
                            dynamic_llm, extra_narration_prompt, purpose="sql_generator.narration",
                            model_name=actual_model, user_id=_uid,
                        ).content.strip()

                    elif str(chosen_model).startswith("ollama://"):
                        actual_model = chosen_model.replace("ollama://", "")
                        _t0 = time.monotonic()
                        resp = requests.post(self.llm_backend["url"], json={
                            "model": actual_model,
                            "prompt": extra_narration_prompt,
                            "stream": False,
                            "options": {"temperature": 0.3}
                        }, timeout=600)

                        raw_resp = resp.text
                        if "{" in raw_resp and "}" in raw_resp:
                            description = self._parse_ollama_ndjson(raw_resp)
                        else:
                            description = raw_resp.strip()
                        _p_tok, _c_tok = self._extract_ollama_usage(raw_resp)
                        record_llm_call(
                            purpose="sql_generator.narration", model_name=actual_model, provider="ollama",
                            prompt_text=extra_narration_prompt, response_text=description,
                            prompt_tokens=_p_tok, completion_tokens=_c_tok,
                            duration_ms=int((time.monotonic() - _t0) * 1000), user_id=_uid,
                        )
                    else:
                        description = "Successfully generated an optimized SQL query."
            
                except:
                    description = "Successfully generated an optimized SQL query."        

                state["steps"].append(f"SQLGenerator: {description}")
                query_sense_output["steps"] = state["steps"]
                state["query_sense_output"] = query_sense_output    

            state["current_step"] = "sql_generator"


        except Exception as e:
            print(f"❌ [SQLGeneratorAgent] Error: {str(e)}")
            state["error"] = f"SQL generation failed: {str(e)}"
            state["generated_sql"] = None
            state["current_step"] = "sql_generator"
            if "steps" in state:
                state["steps"].append(f"SQLGenerator: ERROR. {str(e)}")

        return state

