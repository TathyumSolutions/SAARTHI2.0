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
from langchain_openai import ChatOpenAI


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

    def generate_sql_from_querysense(
        self,
        user_query: str,
        query_sense_output: Dict[str, Any],
        simplified_query: str,
        error_feedback: str = "",
        target_model: str = "llama3",
        system_instructions: str = ""

    ) -> str:
        """Generate SQL from QuerySense output using LLM (Ollama-safe)"""


        try:
            prompt = f"""
You are a strict PostgreSQL query generator.

USER QUERY: {user_query}
SIMPLIFIED QUERY: {simplified_query}
QUERY SENSE OUTPUT:
{json.dumps(query_sense_output, indent=2)}
ERROR FEEDBACK: {error_feedback}

STRICT RULES:
1. Use ONLY tables and columns present in Query Sense Output. Nothing else.
2. NEVER invent columns like some_metric, score, rank, total_amount unless in Query Sense Output.
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
                ai_response = llm.invoke(prompt)
                raw_sql = ai_response.content.strip()

            elif target_model == "gpt-4o-mini":
                print("🤖 [SQLGeneratorAgent] Routing to ChatOpenAI [gpt-4o-mini] Layer...")
                
                llm = ChatOpenAI(
                model="gpt-4o-mini",
                temperature=0.0,
                openai_api_key=self.openai_key
                )
                ai_response = llm.invoke(prompt)
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
                response = requests.post(
                self.llm_backend["url"],
                json=payload,
                timeout=self.llm_backend.get("timeout", 300)
                )
                response.raise_for_status()
                raw_text = response.text
                raw_sql = self._parse_ollama_ndjson(raw_text)

            elif str(target_model).startswith("api://"):
                actual_model = target_model.replace("api://", "").lower()
                print(f"🌐 [SQLGeneratorAgent] Dynamic Routing payload to Custom Cloud API model: {actual_model}")

                if "claude" in actual_model:
                    from langchain_anthropic import ChatAnthropic
                    dynamic_llm = ChatAnthropic(
                        model=actual_model,
                        temperature=0,
                        anthropic_api_key=self.custom_key if self.custom_key else os.getenv("ANTHROPIC_API_KEY")
                    )
                    ai_response = dynamic_llm.invoke(prompt)
                    raw_sql = ai_response.content.strip()

                elif "gemini" in actual_model:
                    from langchain_google_genai import ChatGoogleGenerativeAI
                    dynamic_llm = ChatGoogleGenerativeAI(
                        model=actual_model,
                        temperature=0,
                        google_api_key=self.custom_key if self.custom_key else os.getenv("GOOGLE_API_KEY")
                    )
                    ai_response = dynamic_llm.invoke(prompt)
                    raw_sql = ai_response.content.strip()

                elif "deepseek" in actual_model:
                    dynamic_llm = ChatOpenAI(
                        model=actual_model,
                        temperature=0,
                        openai_api_key=self.custom_key if self.custom_key else os.getenv("DEEPSEEK_API_KEY"),
                        openai_api_base="https://api.deepseek.com/v1"
                    )
                    ai_response = dynamic_llm.invoke(prompt)
                    raw_sql = ai_response.content.strip()

                elif "gpt" in actual_model or "openai" in actual_model:
                    dynamic_llm = ChatOpenAI(
                        model=actual_model,
                        temperature=0,
                        openai_api_key=self.custom_key if self.custom_key else self.openai_key
                    )
                    ai_response = dynamic_llm.invoke(prompt)
                    raw_sql = ai_response.content.strip()
                else:
                    raise ValueError(
                        f"Custom cloud provider mapping failed: Identifier '{actual_model}' "
                        f"does not match any recognized provider keyword (claude, gemini, deepseek, gpt)."
                    )

            elif str(target_model).startswith("ollama://"):
                actual_model = target_model.replace("ollama://", "")
                print(f"📦 [SQLGeneratorAgent] Dynamic Routing payload to Custom Local Ollama model: {actual_model}")
                payload = {
                    "model": actual_model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.0}
                }
                response = requests.post(self.llm_backend["url"], json=payload, timeout=300)
                response.raise_for_status()
                raw_text = response.text
                if "{" in raw_text and "}" in raw_text:
                    raw_sql = self._parse_ollama_ndjson(raw_text)
                else:
                    raw_sql = raw_text.strip()
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
            self.custom_key = custom_key


            sql = self.generate_sql_from_querysense(
                user_query,
                query_sense_output,
                simplified_query,
                error_feedback,
                chosen_model,
                system_instructions=system_instructions
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
                    if chosen_model == "gpt-4o":
                        
                        llm = ChatOpenAI(
                        model="gpt-4o",
                        temperature=0.3,
                        openai_api_key=self.openai_key
                        )
                        description = llm.invoke(extra_narration_prompt).content.strip()

                    elif chosen_model == "gpt-4o-mini":
                        
                        llm = ChatOpenAI(
                        model="gpt-4o-mini",
                        temperature=0.3,
                        openai_api_key=self.openai_key
                        )
                        description = llm.invoke(extra_narration_prompt).content.strip()

                    elif chosen_model == "llama3":
                        resp = requests.post(self.llm_backend["url"], json={
                        "model": "llama3", 
                        "prompt": extra_narration_prompt, 
                        "stream": False, 
                        "temperature": 0.3
                        }, timeout=300)
                        description = resp.json().get("response", "").strip()
                    elif str(chosen_model).startswith("api://"):
                        actual_model = chosen_model.replace("api://", "").lower()
                        
                        if "claude" in actual_model:
                            from langchain_anthropic import ChatAnthropic
                            dynamic_llm = ChatAnthropic(
                                model=actual_model,
                                temperature=0.3,
                                anthropic_api_key=self.custom_key if self.custom_key else os.getenv("ANTHROPIC_API_KEY")
                            )
                            description = dynamic_llm.invoke(extra_narration_prompt).content.strip()

                        elif "gemini" in actual_model:
                            from langchain_google_genai import ChatGoogleGenerativeAI
                            dynamic_llm = ChatGoogleGenerativeAI(
                                model=actual_model,
                                temperature=0.3,
                                google_api_key=self.custom_key if self.custom_key else os.getenv("GOOGLE_API_KEY")
                            )
                            description = dynamic_llm.invoke(extra_narration_prompt).content.strip()

                        elif "deepseek" in actual_model:
                            dynamic_llm = ChatOpenAI(
                                model=actual_model,
                                temperature=0.3,
                                openai_api_key=self.custom_key if self.custom_key else os.getenv("DEEPSEEK_API_KEY"),
                                openai_api_base="https://api.deepseek.com/v1"
                            )
                            description = dynamic_llm.invoke(extra_narration_prompt).content.strip()

                        elif "gpt" in actual_model or "openai" in actual_model:
                            dynamic_llm = ChatOpenAI(
                                model=actual_model,
                                temperature=0.3,
                                openai_api_key=self.custom_key if self.custom_key else self.openai_key
                            )
                            description = dynamic_llm.invoke(extra_narration_prompt).content.strip()
                        else:
                            description = "Successfully generated an optimized SQL query."

                    elif str(chosen_model).startswith("ollama://"):
                        actual_model = chosen_model.replace("ollama://", "")
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

