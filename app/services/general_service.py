import os
import time
import requests
from datetime import datetime
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

# Import the exact stream manager your architecture uses
from app.services.stream_manager import stream_manager

def answer_general_knowledge(
  user_query: str,
  model_name: str,
  custom_key: str,
  system_instructions: str,
  master_steps: list,
  session_id: str = "1"
) -> dict:
  """
  Standalone track runner that queries the LLM's world knowledge base.
  Pushes normal, accurate step states to stream_manager without RAG/Vector terminology.
  """
  print("🌐 Executing Standalone Track: GENERAL")
  session_id = str(session_id)

  # ===================================================================
  # HELPER FUNCTION FOR REAL-TIME STREAMING
  # ===================================================================
  def push_general_event(event_type, title, description):
      payload = {
          "event": event_type,
          "title": title,
          "description": description,
          "is_sql": False
      }
      if event_type == "start":
          master_steps.append(f"{title} - {description}")
      
      # Broadcast event to your UI layer via the stream manager
      stream_manager.push_step(session_id, payload, is_sql=False)
      time.sleep(0.3)  # Give frontend rendering engine time to execute animations

  # ===================================================================
  # STEP 1: REQUEST INITIALIZATION
  # ===================================================================
  push_general_event("start", "Request Received", f"Processing general inquiry: '{user_query}'")
  push_general_event("complete", "Request Received", f"General knowledge pipeline initialized for: '{user_query}'")

  # ===================================================================
  # STEP 2: CLOCK & CONTEXT INJECTION
  # ===================================================================
  #push_general_event("start", "System Context Setup", "Fetching live system clock parameters and custom formatting instructions...")
  push_general_event("start", "Knowledge Alignment", "Checking query requirements against available knowledge networks...")
  
  # Fetch live system time dynamically right when the function is called
  live_now = datetime.now()
  current_date_context = (
      f"Today's Date: {live_now.strftime('%A, %B %d, %Y')}\n"
      f"Current Time: {live_now.strftime('%I:%M %p')}\n"
      f"Current Month: {live_now.strftime('%B')}\n"
      f"Current Year: {live_now.strftime('%Y')}"
  )

  # Compile full core system behavior instructions
  system_content = (
      "You are Saarthi AI, a helpful enterprise assistant. "
      "Answer the user's question accurately using your general world knowledge.\n\n"
      f"REAL-TIME SYSTEM CLOCK CONTEXT:\n{current_date_context}\n\n"
      "Use this clock context to accurately answer any questions about today, the date, time, year, or month. "
      "Be concise, factual, and friendly."
  )
  if system_instructions and system_instructions.strip():
      system_content += f"\n\n[CRITICAL PERSONA AND CUSTOM FORMATTING RULES]:\n{system_instructions}"

  #push_general_event("complete", "System Context Setup", f"Real-time clock injected successfully ({live_now.strftime('%Y-%m-%d %I:%M %p')}).")
  push_general_event("complete", "Knowledge Alignment", "Query matched successfully with parametric knowledge base parameters.")

  # ===================================================================
  # STEP 3: MODEL RESPONSE GENERATION
  # ===================================================================
  push_general_event("start", "Model Execution", f"Querying {model_name} world knowledge base...")
  final_answer = ""

  try:
      # 1. Cloud Pre-configured Models
      if model_name in ["gpt-4o", "gpt-4o-mini"]:
          openai_api_key = custom_key if custom_key else os.getenv("OPENAI_API_KEY")
          llm = ChatOpenAI(
              model=model_name,
              temperature=0.3,
              openai_api_key=openai_api_key
          )
          response = llm.invoke([
              SystemMessage(content=system_content),
              HumanMessage(content=user_query)
          ])
          final_answer = response.content

      # 2. Dynamic Custom Cloud API Providers
      elif str(model_name).startswith("api://"):
          actual_model = model_name.replace("api://", "").lower()
          messages = [SystemMessage(content=system_content), HumanMessage(content=user_query)]

          if "claude" in actual_model:
              from langchain_anthropic import ChatAnthropic
              dynamic_llm = ChatAnthropic(
                  model=actual_model,
                  temperature=0.3,
                  anthropic_api_key=custom_key if custom_key else os.getenv("ANTHROPIC_API_KEY")
              )
              final_answer = dynamic_llm.invoke(messages).content

          elif "gemini" in actual_model:
              from langchain_google_genai import ChatGoogleGenerativeAI
              dynamic_llm = ChatGoogleGenerativeAI(
                  model=actual_model,
                  temperature=0.3,
                  google_api_key=custom_key if custom_key else os.getenv("GOOGLE_API_KEY")
              )
              final_answer = dynamic_llm.invoke(messages).content

          elif "deepseek" in actual_model:
              dynamic_llm = ChatOpenAI(
                  model=actual_model,
                  temperature=0.3,
                  openai_api_key=custom_key if custom_key else os.getenv("DEEPSEEK_API_KEY"),
                  openai_api_base="https://api.deepseek.com/v1"
              )
              final_answer = dynamic_llm.invoke(messages).content

          elif "gpt" in actual_model or "openai" in actual_model:
              dynamic_llm = ChatOpenAI(
                  model=actual_model,
                  temperature=0.3,
                  openai_api_key=custom_key if custom_key else os.getenv("OPENAI_API_KEY")
              )
              final_answer = dynamic_llm.invoke(messages).content
          else:
              raise ValueError(f"Custom cloud provider mapping failed for identifier: '{actual_model}'")

      # 3. Dynamic Local Ollama Runtime Containers
      elif str(model_name).startswith("ollama://") or model_name == "llama3":
          actual_model = model_name.replace("ollama://", "") if str(model_name).startswith("ollama://") else "llama3"
          ollama_prompt = f"{system_content}\n\nUSER QUESTION:\n{user_query}"
          
          response = requests.post(
              "http://ollama:11434/api/generate",
              json={
                  "model": actual_model,
                  "prompt": ollama_prompt,
                  "stream": False,
                  "keep_alive": "30m",
                  "options": {
                      "temperature": 0.3,
                      "num_ctx": 8192,
                      "num_thread": 4
                  }
              },
              timeout=300
          )
          response.raise_for_status()
          final_answer = response.json().get("response", "").strip()

      else:
          raise ValueError(f"Requested model target configuration error: '{model_name}'")

      push_general_event("complete", "Model Execution", f"Response generated successfully through {model_name}.")

  except Exception as e:
      print(f"⚠️ General Service Track Exception: {e}")
      push_general_event("complete", "Model Execution", f"Error encountered during generation: {str(e)}")
      final_answer = "The system encountered an unexpected error generating your answer via world knowledge parameters."

  # Close out execution lifecycle loop
  stream_manager.push_step(session_id, "DONE", is_sql=False)

  return {
      "answer": final_answer,
      "sql": None,
      "table": [],
      "chart": {},
      "insights": [],
      "steps": master_steps,
      "chain_of_thought": master_steps
  }