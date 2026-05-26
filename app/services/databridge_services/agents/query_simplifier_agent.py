"""
QuerySimplifierAgent - Simplifies user queries to extract core intent
"""
import requests
import json
from typing import Dict, Any


class QuerySimplifierAgent:
    """
    Agent responsible for simplifying user queries.
    Uses LLM to extract core intent and remove ambiguity.
    """
    
    def __init__(self, schema_path: str, model_name: str = "llama3:latest", url: str = "http://ollama:11434/api/generate"):
        self.schema_path = schema_path
        self.model_name = model_name
        self.url = url
        
        # Load schema for context
        if self.schema_path:
            try:
                with open(self.schema_path, "r") as f:
                    self.schema = json.load(f)
            except (FileNotFoundError, TypeError, Exception):
                # If file is missing, we just log a warning instead of crashing
                print(f"⚠️ Warning: Could not load schema from {self.schema_path}. Proceeding with empty schema.")


        #with open(schema_path, "r") as f:
         #   self.schema = json.load(f)
    
    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the agent: simplify user query.
        
        Args:
            state: Current state dictionary containing 'user_query'
            
        Returns:
            Updated state with 'simplified_query'
        """
        print(f"\n🤖 [QuerySimplifierAgent] Starting...")
        
        user_query = state.get("user_query", "")
        simplified = self.simplify(user_query)
        
        state["simplified_query"] = simplified
        state["current_step"] = "query_simplifier"

        if "steps" not in state:
            state["steps"] = []

        # We only store the text that the UI actually needs to display
        state["steps"].append(
            f"Refined the user request to extract the core intent: '{simplified}'"
        )
        
        print(f"✅ [QuerySimplifierAgent] Simplified: {simplified}")
        return state
    
    def simplify(self, user_query: str) -> str:
        """Simplify the user query using LLM"""
        # Get table names for context
        table_names = list(self.schema.keys())
        
        #prompt = f"""
#You are a query simplification expert. Your task is to simplify the user's natural language query while preserving its core intent.

#Available tables: {', '.join(table_names[:10])}

#User Query: "{user_query}"

#Simplify this query to its core intent. Remove unnecessary words, clarify ambiguities, and make it concise.
#Return ONLY the simplified query, nothing else.
#"""    
        prompt = f"""
You are a query simplifier.

AVAILABLE TABLES: {', '.join(table_names[:10])}

USER QUERY: "{user_query}"

RULES:
- Return ONLY plain natural language
- NEVER generate SQL or code
- ALWAYS preserve numbers exactly as given (3, 10, 100 etc)
- KEEP all numbers, limits, table names, column names exactly
- DO NOT change meaning or invent words
- Keep output short and clear

EXAMPLES:
User: "Can you show me the top 5 materials from the mara table?"
Output: top 5 materials from mara

User: "List 3 customers from kna1"
Output: 3 customers from kna1

User: "Show sales orders and customer names"
Output: sales orders and customer names

Return ONLY the simplified query, nothing else.
"""      
        try:
            response = requests.post(
                self.url,
                json={
                    "model": self.model_name,
                    "prompt": prompt,
                    "stream": False,
                    "temperature": 0.0
                },
                timeout=300
            )
            response.raise_for_status()
            result = response.json()
            simplified = result.get("response", user_query).strip()
            return simplified if simplified else user_query
        except Exception as e:
            print(f"⚠️ [QuerySimplifierAgent] LLM failed: {e}, using original query")
            return user_query
