"""
QuerySimplifierAgent - Simplifies user queries to extract core intent
"""
import requests
import json
from typing import Dict, Any
import os
from langchain_openai import ChatOpenAI


class QuerySimplifierAgent:
    """
    Agent responsible for simplifying user queries.
    Uses LLM to extract core intent and remove ambiguity.
    """
    
    def __init__(self, schema_path: str, model_name: str = "llama3", url: str = "http://ollama:11434/api/generate"):
        self.schema_path = schema_path
        self.model_name = model_name
        self.url = url

        self.openai_key = os.getenv("OPENAI_API_KEY")
        
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
        state_model = state.get("model_name")
        chosen_model = state_model if state_model else self.model_name
        print(f"DEBUG: target_model received in execution layer is: '{chosen_model}' (Type: {type(chosen_model)})")
        custom_key = state.get("custom_key", "")
        simplified = self.simplify(user_query, chosen_model,custom_key)
        #chosen_model = state.get("model_name", self.model_name)
        #simplified = self.simplify(user_query,chosen_model)
        
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
    
    def simplify(self, user_query: str,target_model: str,custom_key: str = "") -> str:
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
            if target_model == "gpt-4o":
                print("🔥 [QuerySimplifierAgent] Routing to ChatOpenAI [gpt-4o] Layer...")
                
                llm = ChatOpenAI(
                model="gpt-4o",
                temperature=0,
                openai_api_key=self.openai_key
                )
                response = llm.invoke(prompt)
                simplified = response.content.strip()
            elif target_model == "gpt-4o-mini":
                print("🤖 [QuerySimplifierAgent] Routing to ChatOpenAI [gpt-4o-mini] Layer...")
                
                llm = ChatOpenAI(
                model="gpt-4o-mini",
                temperature=0,
                openai_api_key=self.openai_key
                )
                response = llm.invoke(prompt)
                simplified = response.content.strip()
            elif target_model == "llama3":
                print("🦙 [QuerySimplifierAgent] Routing to local Ollama [llama3] container layer...")
                response = requests.post(
                self.url,
                json={
                    "model": "llama3",  # Forces local Llama 3 image call explicitly
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                    "temperature": 0.0,
                    "num_ctx": 4096
                    }
                },
                timeout=120
                )
                response.raise_for_status()
                result = response.json()
                simplified = result.get("response", user_query).strip()
                return simplified if simplified else user_query
            elif str(target_model).startswith("api://"):
                actual_model = target_model.replace("api://", "").lower()
                print(f"🌐 [QuerySimplifierAgent] Dynamic Routing payload to Custom Cloud API model: {actual_model}")
                
                # Anthropic Claude Models
                if "claude" in actual_model:
                    from langchain_anthropic import ChatAnthropic
                    dynamic_llm = ChatAnthropic(
                        model=actual_model,
                        temperature=0,
                        anthropic_api_key=custom_key if custom_key else os.getenv("ANTHROPIC_API_KEY")
                    )
                    response = dynamic_llm.invoke(prompt)
                    return response.content.strip()

                # Google Gemini Models
                elif "gemini" in actual_model:
                    from langchain_google_genai import ChatGoogleGenerativeAI
                    dynamic_llm = ChatGoogleGenerativeAI(
                        model=actual_model,
                        temperature=0,
                        google_api_key=custom_key if custom_key else os.getenv("GOOGLE_API_KEY")
                    )
                    response = dynamic_llm.invoke(prompt)
                    return response.content.strip()

                # DeepSeek Models
                elif "deepseek" in actual_model:
                    dynamic_llm = ChatOpenAI(
                        model=actual_model,
                        temperature=0,
                        openai_api_key=custom_key if custom_key else os.getenv("DEEPSEEK_API_KEY"),
                        openai_api_base="https://api.deepseek.com/v1"
                    )
                    response = dynamic_llm.invoke(prompt)
                    return response.content.strip()

                # Custom OpenAI Models
                elif "gpt" in actual_model or "openai" in actual_model:
                    dynamic_llm = ChatOpenAI(
                        model=actual_model,
                        temperature=0,
                        openai_api_key=custom_key if custom_key else self.openai_key
                    )
                    response = dynamic_llm.invoke(prompt)
                    return response.content.strip()
                else:
                    raise ValueError(
                        f"Custom cloud provider mapping failed: Identifier '{actual_model}' "
                        f"does not match any recognized provider keyword (claude, gemini, deepseek, gpt)."
                    )

            # --- 4. DYNAMIC LOCAL OLLAMA ROUTING BLOCK (ollama://) ---
            elif str(target_model).startswith("ollama://"):
                actual_model = target_model.replace("ollama://", "")
                print(f"📦 [QuerySimplifierAgent] Dynamic Routing payload to Custom Local Ollama model: {actual_model}")
                
                response = requests.post(
                    self.url,
                    json={
                        "model": actual_model,
                        "prompt": prompt,
                        "stream": False,
                        "options": {
                            "temperature": 0.0,
                            "num_ctx": 4096
                        }
                    },
                    timeout=120
                )
                response.raise_for_status()
                result = response.json()
                simplified = result.get("response", user_query).strip()
                return simplified if simplified else user_query
                
            else:
                raise ValueError(f"Requested model '{target_model}' has no active route handler configuration.")
        except Exception as e:
            print(f"⚠️ [QuerySimplifierAgent] LLM failed: {e}, using original query")
            return user_query
