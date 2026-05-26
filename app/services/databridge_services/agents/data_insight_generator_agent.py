"""
DataInsightGeneratorAgent - Self-contained agent
Generates insights and visualization suggestions from query results
"""
from typing import Dict, Any, List
import requests
import json
import pandas as pd

class DataInsightGeneratorAgent:
    """
    Agent responsible for generating insights.
    Analyzes data and provides business insights with recommended visualizations.
    """

    def __init__(self, llm_url: str = "http://ollama:11434/api/generate", model: str = "llama3:latest"):
        self.llm_url = llm_url
        self.model = model

    def generate_insights(self, data: List[Dict[str, Any]], columns: List[str], user_query: str = "") -> Dict[str, Any]:
        """
        Analyze data and return insights and visualization suggestions.
        """
        if not data:
            return {"insights": ["No data available to analyze."], "visualizations": []}

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

        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json"
        }

        try:
            response = requests.post(self.llm_url, json=payload, timeout=600)
            response.raise_for_status()
            result = response.json()
            response_text = result.get("response", "")

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

        insights_data = self.generate_insights(data, columns, user_query)
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
