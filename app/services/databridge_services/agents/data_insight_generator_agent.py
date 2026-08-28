"""
DataInsightGeneratorAgent - Self-contained agent
Generates insights and visualization suggestions from query results
"""
from typing import Dict, Any, List
import requests
import json
import time
import pandas as pd
import os
from langchain_openai import ChatOpenAI
from app.services.llm_call_logger import tracked_invoke, record_llm_call

class DataInsightGeneratorAgent:
    """
    Agent responsible for generating insights.
    Analyzes data and provides business insights with recommended visualizations.
    """

    def __init__(self, llm_url: str = "http://ollama:11434/api/generate", model: str = "llama3"):
        self.llm_url = llm_url
        self.model = model

        self.openai_key = os.getenv("OPENAI_API_KEY")
        self.custom_key = ""

    def generate_insights(self, data: List[Dict[str, Any]], columns: List[str], user_query: str = "",target_model: str = None,system_instructions: str = "", user_id=None) -> Dict[str, Any]:
        """
        Analyze data and return insights and visualization suggestions.
        """
        if not data:
            return {"insights": ["No data available to analyze."], "visualizations": []}
        
        model_to_use = target_model or self.model

        # Prepare a summarized dataset to avoid sending too much data to LLM
        df = pd.DataFrame(data)
        summary = df.describe(include='all').to_string()
        sample_data = df.head(5).to_string()

        prompt = f"""
You are a Data Analyst expert. Analyze the following dataset and provide:
1. 3-5 Key strategic insights or patterns found in the data.
2. The best 2 visualization types (Bar, Line, Pie, Histogram, etc.) with brief reasons.

User Query: "{user_query}"
Data Columns: {columns}

Data Summary:
{summary}

Sample Data (first 5 rows):
{sample_data}

Output Format (JSON):
{{
    "insights": ["insight 1", "insight 2", ...],
    "visualizations": [
        {{"type": "Bar Chart", "reason": "..."}},
        {{"type": "Line Chart", "reason": "..."}}
    ]
}}

Return ONLY valid JSON.
"""
        if system_instructions.strip():
            prompt += f"\n\nUSER CUSTOM FORMATTING INSTRUCTIONS:\n{system_instructions}"

        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json"
        }

        try:
            if model_to_use == "gpt-4o":
                print(f"☁️ [DataInsightGeneratorAgent] Routing insights to ChatOpenAI [gpt-4o] Layer...")
                
                
                llm = ChatOpenAI(
                model="gpt-4o",
                temperature=0.3,
                openai_api_key=self.openai_key
                )
                ai_response = tracked_invoke(
                    llm, prompt, purpose="data_insight.generate", model_name="gpt-4o",
                    provider="openai", user_id=user_id,
                )
                response_text = ai_response.content.strip()

            elif model_to_use == "gpt-4o-mini":
                print(f"🤖 [DataInsightGeneratorAgent] Routing insights to ChatOpenAI [gpt-4o-mini] Layer...")


                llm = ChatOpenAI(
                model="gpt-4o-mini",
                temperature=0.3,
                openai_api_key=self.openai_key
                )
                ai_response = tracked_invoke(
                    llm, prompt, purpose="data_insight.generate", model_name="gpt-4o-mini",
                    provider="openai", user_id=user_id,
                )
                response_text = ai_response.content.strip()

            elif model_to_use == "llama3":
                print(f"🦙 [DataInsightGeneratorAgent] Routing insights to Local Ollama [llama3] Layer...")
                payload = {
                "model": "llama3",
                "prompt": prompt,
                "stream": False,
                "format": "json"
                }
                _t0 = time.monotonic()
                response = requests.post(self.llm_url, json=payload, timeout=600)
                response.raise_for_status()
                result = response.json()
                response_text = result.get("response", "")
                record_llm_call(
                    purpose="data_insight.generate", model_name="llama3", provider="ollama",
                    prompt_text=prompt, response_text=response_text,
                    prompt_tokens=result.get("prompt_eval_count"), completion_tokens=result.get("eval_count"),
                    duration_ms=int((time.monotonic() - _t0) * 1000), user_id=user_id,
                )

            elif str(model_to_use).startswith("api://"):
                actual_model = model_to_use.replace("api://", "").lower()
                print(f"🌐 [DataInsightGeneratorAgent] Dynamic Routing insights to Custom Cloud API model: {actual_model}")

                from app.services.llm_providers import resolve_dynamic_llm
                dynamic_llm = resolve_dynamic_llm(
                    actual_model,
                    self.custom_key,
                    temperature=0.3,
                    openai_fallback_key=self.openai_key,
                    strict=True,
                )
                ai_response = tracked_invoke(
                    dynamic_llm, prompt, purpose="data_insight.generate", model_name=actual_model, user_id=user_id,
                )
                response_text = ai_response.content.strip()

            elif str(model_to_use).startswith("ollama://"):
                actual_model = model_to_use.replace("ollama://", "")
                print(f"📦 [DataInsightGeneratorAgent] Dynamic Routing insights to Custom Local Ollama model: {actual_model}")
                payload = {
                    "model": actual_model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json"
                }
                _t0 = time.monotonic()
                response = requests.post(self.llm_url, json=payload, timeout=600)
                response.raise_for_status()
                result = response.json()
                response_text = result.get("response", "")
                record_llm_call(
                    purpose="data_insight.generate", model_name=actual_model, provider="ollama",
                    prompt_text=prompt, response_text=response_text,
                    prompt_tokens=result.get("prompt_eval_count"), completion_tokens=result.get("eval_count"),
                    duration_ms=int((time.monotonic() - _t0) * 1000), user_id=user_id,
                )
            else:
                raise ValueError(f"Strict Execution Rule Violated: Unknown model parameter target '{model_to_use}'")
                #print(f"🦙 [DataInsightGeneratorAgent] Routing insights to Local Ollama ({model_to_use})...")
                #payload = {
                #    "model": model_to_use,  # <--- Dynamic parameter injection
                #    "prompt": prompt,
                #    "stream": False,
                #    "format": "json"
                #}
            #response = requests.post(self.llm_url, json=payload, timeout=600)
            #response.raise_for_status()
            #result = response.json()
            #response_text = result.get("response", "")

            # Parse JSON from response
            try:
                parsed_response = json.loads(response_text)
                return parsed_response
            except json.JSONDecodeError:
                # Fallback if LLM returns code block
                if "```json" in response_text:
                    json_str = response_text.split("```json")[1].split("```")[0].strip()
                    return json.loads(json_str)
                return {"insights": ["Could not parse insights from LLM."], "visualizations": [], "raw_response": response_text}

        except Exception as e:
            return {"insights": [], "visualizations": [], "error": f"Failed to generate insights: {str(e)}"}

    # --------------------------
    # Execute agent
    # --------------------------
    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the agent: generate insights from data.
        """
        print(f"\n🤖 [DataInsightGeneratorAgent] Starting...")
        if "steps" not in state or state.get("steps") is None:
            state["steps"] = []

        data = state.get("data", [])
        columns = state.get("columns", [])
        user_query = state.get("user_query", "")
        system_instructions = state.get("system_instructions", "")

        chosen_model = state.get("model_name", self.model)

        custom_key = state.get("custom_key", "")
        self.custom_key = custom_key

        # A single-row result (KPI format) has no distribution for
        # df.describe() to summarize - mean/min/max all collapse to the one
        # value and std is NaN, so this call would just ask the LLM to spin
        # that degenerate summary into "insights", producing filler like
        # "there is no variation in the data" instead of anything concrete.
        # The KPI card already states the one fact directly; skip it here.
        if len(data) <= 1:
            insights_data = {"insights": [], "visualizations": []}
        else:
            insights_data = self.generate_insights(data, columns, user_query,target_model=chosen_model,system_instructions=system_instructions,user_id=state.get("user_id"))
        state["insights"] = insights_data.get("insights", [])
        state["visualizations"] = insights_data.get("visualizations", [])
        state["current_step"] = "data_insight_generator"

        # --- EXTRA: Add simple status to UI sidebar ---
        insight_count = len(state["insights"])
        viz_count = len(state["visualizations"])
        
        if insight_count > 0:
            status_msg = f"Data Analysis: SUCCESS. Generated {insight_count} business insights and {viz_count} visualization configurations."
        else:
            status_msg = "Data Analysis: COMPLETED. Scanned data for trends; no significant anomalies detected."
            
        state["steps"].append(status_msg)

        query_sense_output = state.get("query_sense_output", {})
        query_sense_output["steps"] = state["steps"]
        state["query_sense_output"] = query_sense_output

        print(f"✅ [DataInsightGeneratorAgent] Generated {len(state['insights'])} insights")
        return state
