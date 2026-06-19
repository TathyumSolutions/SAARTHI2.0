import psycopg2
from flask import current_app
import os
import time
import requests
import json
from urllib.parse import urlparse
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from app.services.stream_manager import stream_manager

def fetch_and_translate_tools():
    """
    Connects to Postgres, reads all columns using SELECT *, and translates 
    them into structured schemas using exact column index mapping.
    """
    # 1. Setup connection credentials to our isolated Docker database container
    base_uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')
    result = urlparse(base_uri)
    dsn = f"postgresql://{result.username}:{result.password}@{result.hostname}:{result.port or 5432}/saarthi_api_db"
    
    # 2. Open the communication pipeline
    conn = psycopg2.connect(dsn)
    cursor = conn.cursor()
    
    # 3. Grab ALL columns matching your exact table layout
    query = "SELECT * FROM registered_tools WHERE status = 'Active';"
    cursor.execute(query)
    rows = cursor.fetchall() 
    
    llm_tools_list = []
    
    # 4. Loop through each row using your precise table indexes
    for row in rows:
        # Based on your table layout: integration_name is index 1, description is index 7
        tool_name = row[1]       
        tool_description = row[7] 
        
        # Construct the exact schema package the LLM expects
        llm_schema = {
            "type": "function",
            "function": {
                "name": tool_name,
                "description": tool_description,
                "parameters": {
                    "type": "object",
                    "properties": {}  
                }
            }
        }
        
        # Append this translated dictionary item to our master tools list
        llm_tools_list.append(llm_schema)
    
    # 5. Clean up our database connection lines safely
    cursor.close()
    conn.close()
    
    return llm_tools_list


def ask_dynamic_model_with_tools(user_message, llm_tools_list, model_name, session_id=1, custom_key='', ollama_config=None,display_query=None):
      """
      Dynamically routes queries to models, strictly enforcing tool execution,
      performs the actual API execution, and returns a fully parsed response context.
      """

      log_query = display_query if display_query else user_message
      tool_chain_of_thought = []
      session_id = str(session_id)
      
      def push_tool_event(event_type, title, description):
          event_data = {
              "event": event_type,
              "title": title,
              "description": description,
              "is_sql": False
          }

          if event_type == "start":
              tool_chain_of_thought.append(f"{title} - {description}")
          
          stream_manager.push_step(session_id, event_data, is_sql=False)
          time.sleep(0.3)

      system_prompt = (
          "You are Saarthi, a strict enterprise automation agent. You operate EXCLUSIVELY by executing available tools.\n\n"
          "Rules:\n"
          "1. You are NOT a general assistant. You cannot answer casual greetings, general knowledge questions, or conversational text.\n"
          "2. If the user's request matches an available tool description, you MUST call that tool.\n"
          "3. If the user's request does NOT match any available tool, you must output exactly this text: "
          "'ERROR: No matching workflow tool found to execute this request.' Do not write anything else."
      )

      try:
          push_tool_event("start", "Received the user query", f"User query: '{user_message}'")
          messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_message)]
          push_tool_event("complete", "Received the user query", f"Query successfully processed: '{user_message}'")
          
          push_tool_event("start", "Context Intent Analysis", "Evaluating structural execution state limits...")
          push_tool_event("complete", "Context Intent Analysis", "Analysis complete.")

          push_tool_event("start", "Schema Blueprint Matching", "Evaluating intent patterns against active JSON database schemas...")
          
          has_tools = False
          tool_payload = None
          generation_text = ""
          
          is_local_ollama = False

          # --- ROUTE A: OPENAI ---
          if model_name in ["gpt-4o-mini", "gpt-4o"]:
              dynamic_llm = ChatOpenAI(model=model_name, temperature=0, openai_api_key=custom_key if custom_key else os.getenv("OPENAI_API_KEY"))
              ai_response = dynamic_llm.bind_tools(llm_tools_list).invoke(messages)
              
              has_tools = bool(ai_response.tool_calls)
              tool_payload = ai_response.tool_calls if has_tools else None
              generation_text = ai_response.content

          # --- ROUTE B: LOCAL OLLAMA ---
          elif model_name == "llama3":
              is_local_ollama = True
              if not ollama_config:
                  ollama_config = {"url": "http://localhost:11434/api/chat", "temperature": 0}
              payload = {
                  "model": "llama3",
                  "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_message}],
                  "tools": llm_tools_list,
                  "stream": False,
                  "options": {"temperature": 0}
              }
              response = requests.post(ollama_config["url"], json=payload, timeout=300)
              response.raise_for_status()
              ai_message = response.json().get("message", {})
              
              has_tools = bool(ai_message.get("tool_calls"))
              tool_payload = ai_message.get("tool_calls") if has_tools else None
              generation_text = ai_message.get("content", "")

          # --- ROUTE C: DYNAMIC CLOUD PROVIDERS (api://) ---
          elif str(model_name).startswith("api://"):
              actual_model = model_name.replace("api://", "").lower()
              if "claude" in actual_model:
                  from langchain_anthropic import ChatAnthropic
                  dynamic_llm = ChatAnthropic(model=actual_model, temperature=0, anthropic_api_key=custom_key if custom_key else os.getenv("ANTHROPIC_API_KEY"))
              elif "gemini" in actual_model:
                  from langchain_google_genai import ChatGoogleGenerativeAI
                  dynamic_llm = ChatGoogleGenerativeAI(model=actual_model, temperature=0, google_api_key=custom_key if custom_key else os.getenv("GOOGLE_API_KEY"))
              elif "deepseek" in actual_model:
                  dynamic_llm = ChatOpenAI(model=actual_model, temperature=0, openai_api_key=custom_key if custom_key else os.getenv("DEEPSEEK_API_KEY"), openai_api_base="https://api.deepseek.com/v1")
              else:
                  dynamic_llm = ChatOpenAI(model=actual_model, temperature=0, openai_api_key=custom_key if custom_key else os.getenv("OPENAI_API_KEY"))

              ai_response = dynamic_llm.bind_tools(llm_tools_list).invoke(messages)
              has_tools = bool(ai_response.tool_calls)
              tool_payload = ai_response.tool_calls if has_tools else None
              generation_text = ai_response.content

          # --- ROUTE D: DYNAMIC LOCAL OLLAMA (ollama://) ---
          elif str(model_name).startswith("ollama://"):
              is_local_ollama = True
              actual_model = model_name.replace("ollama://", "")
              if not ollama_config:
                  ollama_config = {"url": "http://localhost:11434/api/chat", "temperature": 0}
              payload = {
                  "model": actual_model,
                  "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_message}],
                  "tools": llm_tools_list,
                  "stream": False,
                  "options": {"temperature": 0}
              }
              response = requests.post(ollama_config["url"], json=payload, timeout=300)
              response.raise_for_status()
              ai_message = response.json().get("message", {})
              has_tools = bool(ai_message.get("tool_calls"))
              tool_payload = ai_message.get("tool_calls") if has_tools else None
              generation_text = ai_message.get("content", "")
          else:
              raise ValueError(f"Target '{model_name}' has no active route handler.")

          push_tool_event("complete", "Schema Blueprint Matching", "Model evaluation complete.")

          if not has_tools:
              push_tool_event("start", "Response Synthesis", "Parsing execution payload...")
              push_tool_event("complete", "Response Synthesis", "Rejection rule triggered.")
              stream_manager.push_step(session_id, "DONE", is_sql=False)
              return {
                  "answer": "ERROR: No matching workflow tool found to execute this request.",
                  "tool_calls": None, "sql": None, "table": [], "chart": {}, "insights": [], "steps": tool_chain_of_thought
              }

          if has_tools and not generation_text:
              try:
                  target_name = tool_payload[0]['name'] if isinstance(tool_payload[0], dict) else tool_payload[0].name
                  tool_args = tool_payload[0].get('args', {}) if isinstance(tool_payload[0], dict) else tool_payload[0].arguments
                  if isinstance(tool_args, str):
                      tool_args = json.loads(tool_args)

                  base_uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')
                  result = urlparse(base_uri)
                  dsn = f"postgresql://{result.username}:{result.password}@{result.hostname}:{result.port or 5432}/saarthi_api_db"
                  
                  conn = psycopg2.connect(dsn)
                  cursor = conn.cursor()
                  cursor.execute("SELECT base_url, endpoint, method FROM registered_tools WHERE integration_name = %s LIMIT 1;", (target_name,))
                  api_meta = cursor.fetchone()
                  cursor.close()
                  conn.close()

                  if api_meta:
                      base_url, endpoint, method = api_meta[0], api_meta[1], api_meta[2]
                      full_target_url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"
                      
                      push_tool_event("start", "Live Tool Execution", f"Executing REST API via {method} protocol...")
                      
                      if str(method).upper() == "POST":
                          api_res = requests.post(url=full_target_url, json=tool_args, timeout=15)
                      else:
                          api_res = requests.get(url=full_target_url, params=tool_args, timeout=15)
                          
                      raw_data = api_res.json()
                      push_tool_event("complete", "Live Tool Execution", "Dynamic REST execution complete.")
                      
                      push_tool_event("start", "Response Synthesis", "Parsing execution payload...")
                      
                      refinement_sys_msg = "You are an expert data analysis engine. Read the following raw API dataset payload context and provide a precise, targeted answer to the user's specific request. Do not include unneeded object structures or JSON syntax wrappers."
                      refinement_usr_msg = f"User intent request: {user_message}\n\nLive API Fetched Raw Dataset Context:\n{str(raw_data)[:3500]}"
                      
                      # Reuses selected local Ollama model identifier cleanly
                      if is_local_ollama:
                          target_ollama_model = model_name.replace("ollama://", "") if "ollama://" in model_name else "llama3"
                          refine_payload = {
                              "model": target_ollama_model,
                              "messages": [{"role": "system", "content": refinement_sys_msg}, {"role": "user", "content": refinement_usr_msg}],
                              "stream": False,
                              "options": {"temperature": 0}
                          }
                          refine_res = requests.post(ollama_config["url"], json=refine_payload, timeout=300)
                          refine_res.raise_for_status()
                          generation_text = refine_res.json().get("message", {}).get("content", "")
                      
                      # Reuses selected cloud model type cleanly
                      else:
                          refinement_prompt = [
                              SystemMessage(content=refinement_sys_msg),
                              HumanMessage(content=refinement_usr_msg)
                          ]
                          
                          if model_name in ["gpt-4o-mini", "gpt-4o"]:
                              refinement_llm = ChatOpenAI(model=model_name, temperature=0, openai_api_key=custom_key if custom_key else os.getenv("OPENAI_API_KEY"))
                          elif str(model_name).startswith("api://"):
                              actual_model = model_name.replace("api://", "").lower()
                              if "claude" in actual_model:
                                  from langchain_anthropic import ChatAnthropic
                                  refinement_llm = ChatAnthropic(model=actual_model, temperature=0, anthropic_api_key=custom_key if custom_key else os.getenv("ANTHROPIC_API_KEY"))
                              elif "gemini" in actual_model:
                                  from langchain_google_genai import ChatGoogleGenerativeAI
                                  refinement_llm = ChatGoogleGenerativeAI(model=actual_model, temperature=0, google_api_key=custom_key if custom_key else os.getenv("GOOGLE_API_KEY"))
                              elif "deepseek" in actual_model:
                                  refinement_llm = ChatOpenAI(model=actual_model, temperature=0, openai_api_key=custom_key if custom_key else os.getenv("DEEPSEEK_API_KEY"), openai_api_base="https://api.deepseek.com/v1")
                              else:
                                  refinement_llm = ChatOpenAI(model=actual_model, temperature=0, openai_api_key=custom_key if custom_key else os.getenv("OPENAI_API_KEY"))
                          else:
                              refinement_llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, openai_api_key=custom_key if custom_key else os.getenv("OPENAI_API_KEY"))
                              
                          generation_text = refinement_llm.invoke(refinement_prompt).content
                          
                      push_tool_event("complete", "Response Synthesis", "Workflow tool successfully mapped.")
                  else:
                      push_tool_event("start", "Response Synthesis", "Parsing execution payload...")
                      generation_text = f"Tool properties for execution identifier '{target_name}' could not be located in database records."
                      push_tool_event("complete", "Response Synthesis", "Failed: Tool database configurations missing.")
              
              except Exception as e:
                  push_tool_event("start", "Response Synthesis", "Parsing execution payload...")
                  generation_text = f"Tool identified successfully, but dynamic automation handler failed: {str(e)}"
                  push_tool_event("complete", "Response Synthesis", f"Failed: {str(e)}")

          time.sleep(0.5)
          stream_manager.push_step(session_id, "DONE", is_sql=False)
          
          return {
              "answer": generation_text,
              "tool_calls": tool_payload,
              "sql": None, "table": [], "chart": {}, "insights": [], "steps": tool_chain_of_thought
          }

      except Exception as e:
          print(f"Engine failure: {str(e)}")
          stream_manager.push_step(session_id, "DONE", is_sql=False)
          return {
              "answer": f"The system encountered an error processing your routing request: {str(e)}",
              "tool_calls": None, "sql": None, "table": [], "chart": {}, "insights": [], "steps": tool_chain_of_thought
          }



# def ask_dynamic_model_with_tools(user_message, llm_tools_list, model_name, session_id=1, custom_key='', ollama_config=None,display_query=None):
#       """
#       Dynamically routes queries to models, strictly enforcing tool execution,
#       performs the actual API execution, and returns a fully parsed response context.
#       """

#       log_query = display_query if display_query else user_message
#       tool_chain_of_thought = []
#       session_id = str(session_id)
      
#       def push_tool_event(event_type, title, description):
#           event_data = {
#               "event": event_type,
#               "title": title,
#               "description": description,
#               "is_sql": False
#           }

#           if event_type == "start":
#               tool_chain_of_thought.append(f"{title} - {description}")
          
#           stream_manager.push_step(session_id, event_data, is_sql=False)
#           time.sleep(0.3)

#       system_prompt = (
#           "You are Saarthi, a strict enterprise automation agent. You operate EXCLUSIVELY by executing available tools.\n\n"
#           "Rules:\n"
#           "1. You are NOT a general assistant. You cannot answer casual greetings, general knowledge questions, or conversational text.\n"
#           "2. If the user's request matches an available tool description, you MUST call that tool.\n"
#           "3. If the user's request does NOT match any available tool, you must output exactly this text: "
#           "'ERROR: No matching workflow tool found to execute this request.' Do not write anything else."
#       )

#       try:
#           push_tool_event("start", "Received the user query", f"User query: '{user_message}'")
#           messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_message)]
#           push_tool_event("complete", "Received the user query", f"Query successfully processed: '{user_message}'")
          
#           push_tool_event("start", "Context Intent Analysis", "Evaluating structural execution state limits...")
#           push_tool_event("complete", "Context Intent Analysis", "Analysis complete.")

#           push_tool_event("start", "Schema Blueprint Matching", "Evaluating intent patterns against active JSON database schemas...")
          
#           has_tools = False
#           tool_payload = None
#           generation_text = ""
          
#           # Tracks the chosen model instance dynamically
#           active_llm_instance = None
#           is_local_ollama = False

#           # --- ROUTE A: OPENAI ---
#           if model_name in ["gpt-4o-mini", "gpt-4o"]:
#               active_llm_instance = ChatOpenAI(model=model_name, temperature=0, openai_api_key=custom_key if custom_key else os.getenv("OPENAI_API_KEY"))
#               ai_response = active_llm_instance.bind_tools(llm_tools_list).invoke(messages)
              
#               has_tools = bool(ai_response.tool_calls)
#               tool_payload = ai_response.tool_calls if has_tools else None
#               generation_text = ai_response.content

#           # --- ROUTE B: LOCAL OLLAMA ---
#           elif model_name == "llama3":
#               is_local_ollama = True
#               if not ollama_config:
#                   ollama_config = {"url": "http://localhost:11434/api/chat", "temperature": 0}
#               payload = {
#                   "model": "llama3",
#                   "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_message}],
#                   "tools": llm_tools_list,
#                   "stream": False,
#                   "options": {"temperature": 0}
#               }
#               response = requests.post(ollama_config["url"], json=payload, timeout=300)
#               response.raise_for_status()
#               ai_message = response.json().get("message", {})
              
#               has_tools = bool(ai_message.get("tool_calls"))
#               tool_payload = ai_message.get("tool_calls") if has_tools else None
#               generation_text = ai_message.get("content", "")

#           # --- ROUTE C: DYNAMIC CLOUD PROVIDERS (api://) ---
#           elif str(model_name).startswith("api://"):
#               actual_model = model_name.replace("api://", "").lower()
#               if "claude" in actual_model:
#                   from langchain_anthropic import ChatAnthropic
#                   active_llm_instance = ChatAnthropic(model=actual_model, temperature=0, anthropic_api_key=custom_key if custom_key else os.getenv("ANTHROPIC_API_KEY"))
#               elif "gemini" in actual_model:
#                   from langchain_google_genai import ChatGoogleGenerativeAI
#                   active_llm_instance = ChatGoogleGenerativeAI(model=actual_model, temperature=0, google_api_key=custom_key if custom_key else os.getenv("GOOGLE_API_KEY"))
#               elif "deepseek" in actual_model:
#                   active_llm_instance = ChatOpenAI(model=actual_model, temperature=0, openai_api_key=custom_key if custom_key else os.getenv("DEEPSEEK_API_KEY"), openai_api_base="https://api.deepseek.com/v1")
#               else:
#                   active_llm_instance = ChatOpenAI(model=actual_model, temperature=0, openai_api_key=custom_key if custom_key else os.getenv("OPENAI_API_KEY"))

#               ai_response = active_llm_instance.bind_tools(llm_tools_list).invoke(messages)
#               has_tools = bool(ai_response.tool_calls)
#               tool_payload = ai_response.tool_calls if has_tools else None
#               generation_text = ai_response.content

#           # --- ROUTE D: DYNAMIC LOCAL OLLAMA (ollama://) ---
#           elif str(model_name).startswith("ollama://"):
#               is_local_ollama = True
#               actual_model = model_name.replace("ollama://", "")
#               if not ollama_config:
#                   ollama_config = {"url": "http://localhost:11434/api/chat", "temperature": 0}
#               payload = {
#                   "model": actual_model,
#                   "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_message}],
#                   "tools": llm_tools_list,
#                   "stream": False,
#                   "options": {"temperature": 0}
#               }
#               response = requests.post(ollama_config["url"], json=payload, timeout=300)
#               response.raise_for_status()
#               ai_message = response.json().get("message", {})
#               has_tools = bool(ai_message.get("tool_calls"))
#               tool_payload = ai_message.get("tool_calls") if has_tools else None
#               generation_text = ai_message.get("content", "")
#           else:
#               raise ValueError(f"Target '{model_name}' has no active route handler.")

#           push_tool_event("complete", "Schema Blueprint Matching", "Model evaluation complete.")

#           if not has_tools:
#               push_tool_event("start", "Response Synthesis", "Parsing execution payload...")
#               push_tool_event("complete", "Response Synthesis", "Rejection rule triggered.")
#               stream_manager.push_step(session_id, "DONE", is_sql=False)
#               return {
#                   "answer": "ERROR: No matching workflow tool found to execute this request.",
#                   "tool_calls": None, "sql": None, "table": [], "chart": {}, "insights": [], "steps": tool_chain_of_thought
#               }

#           if has_tools and not generation_text:
#               try:
#                   target_name = tool_payload[0]['name'] if isinstance(tool_payload[0], dict) else tool_payload[0].name
#                   tool_args = tool_payload[0].get('args', {}) if isinstance(tool_payload[0], dict) else tool_payload[0].arguments
#                   if isinstance(tool_args, str):
#                       tool_args = json.loads(tool_args)

#                   base_uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')
#                   result = urlparse(base_uri)
#                   dsn = f"postgresql://{result.username}:{result.password}@{result.hostname}:{result.port or 5432}/saarthi_api_db"
                  
#                   conn = psycopg2.connect(dsn)
#                   cursor = conn.cursor()
#                   cursor.execute("SELECT base_url, endpoint, method FROM registered_tools WHERE integration_name = %s LIMIT 1;", (target_name,))
#                   api_meta = cursor.fetchone()
#                   cursor.close()
#                   conn.close()

#                   if api_meta:
#                       base_url, endpoint, method = api_meta[0], api_meta[1], api_meta[2]
#                       full_target_url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"
                      
#                       push_tool_event("start", "Live Tool Execution", f"Executing REST API via {method} protocol...")
                      
#                       if str(method).upper() == "POST":
#                           api_res = requests.post(url=full_target_url, json=tool_args, timeout=15)
#                       else:
#                           api_res = requests.get(url=full_target_url, params=tool_args, timeout=15)
                          
#                       raw_data = api_res.json()
#                       push_tool_event("complete", "Live Tool Execution", "Dynamic REST execution complete.")
                      
#                       push_tool_event("start", "Response Synthesis", "Parsing execution payload...")
                      
#                       refinement_sys_msg = "You are an expert data analysis engine. Read the following raw API dataset payload context and provide a precise, targeted answer to the user's specific request. Do not include unneeded object structures or JSON syntax wrappers."
#                       refinement_usr_msg = f"User intent request: {user_message}\n\nLive API Fetched Raw Dataset Context:\n{str(raw_data)[:3500]}"
                      
#                       # Reuses selected local Ollama model identifier
#                       if is_local_ollama:
#                           target_ollama_model = model_name.replace("ollama://", "") if "ollama://" in model_name else "llama3"
#                           refine_payload = {
#                               "model": target_ollama_model,
#                               "messages": [{"role": "system", "content": refinement_sys_msg}, {"role": "user", "content": refinement_usr_msg}],
#                               "stream": False,
#                               "options": {"temperature": 0}
#                           }
#                           refine_res = requests.post(ollama_config["url"], json=refine_payload, timeout=300)
#                           refine_res.raise_for_status()
#                           generation_text = refine_res.json().get("message", {}).get("content", "")
                      
#                       # Reuses selected cloud LangChain instance model identifier
#                       else:
#                           refinement_prompt = [
#                               SystemMessage(content=refinement_sys_msg),
#                               HumanMessage(content=refinement_usr_msg)
#                           ]
#                           generation_text = active_llm_instance.invoke(refinement_prompt).content
                          
#                       push_tool_event("complete", "Response Synthesis", "Workflow tool successfully mapped.")
#                   else:
#                       push_tool_event("start", "Response Synthesis", "Parsing execution payload...")
#                       generation_text = f"Tool properties for execution identifier '{target_name}' could not be located in database records."
#                       push_tool_event("complete", "Response Synthesis", "Failed: Tool database configurations missing.")
              
#               except Exception as e:
#                   push_tool_event("start", "Response Synthesis", "Parsing execution payload...")
#                   generation_text = f"Tool identified successfully, but dynamic automation handler failed: {str(e)}"
#                   push_tool_event("complete", "Response Synthesis", f"Failed: {str(e)}")

#           time.sleep(0.5)
#           stream_manager.push_step(session_id, "DONE", is_sql=False)
          
#           return {
#               "answer": generation_text,
#               "tool_calls": tool_payload,
#               "sql": None, "table": [], "chart": {}, "insights": [], "steps": tool_chain_of_thought
#           }

#       except Exception as e:
#           print(f"Engine failure: {str(e)}")
#           stream_manager.push_step(session_id, "DONE", is_sql=False)
#           return {
#               "answer": f"The system encountered an error processing your routing request: {str(e)}",
#               "tool_calls": None, "sql": None, "table": [], "chart": {}, "insights": [], "steps": tool_chain_of_thought
#           }


# def ask_dynamic_model_with_tools(user_message, llm_tools_list, model_name, session_id=1, custom_key='', ollama_config=None,display_query=None):
#     """
#     Dynamically routes queries to models, strictly enforcing tool execution,
#     performs the actual API execution, and returns a fully parsed response context.
#     """

#     log_query = display_query if display_query else user_message
#     tool_chain_of_thought = []
#     session_id = str(session_id)
    
#     def push_tool_event(event_type, title, description):
#         event_data = {
#             "event": event_type,
#             "title": title,
#             "description": description,
#             "is_sql": False
#         }

#         if event_type == "start":
#             tool_chain_of_thought.append(f"{title} - {description}")
        
#         stream_manager.push_step(session_id, event_data, is_sql=False)
#         time.sleep(0.3)

#     system_prompt = (
#         "You are Saarthi, a strict enterprise automation agent. You operate EXCLUSIVELY by executing available tools.\n\n"
#         "Rules:\n"
#         "1. You are NOT a general assistant. You cannot answer casual greetings, general knowledge questions, or conversational text.\n"
#         "2. If the user's request matches an available tool description, you MUST call that tool.\n"
#         "3. If the user's request does NOT match any available tool, you must output exactly this text: "
#         "'ERROR: No matching workflow tool found to execute this request.' Do not write anything else."
#     )

#     try:
#         # Step 1: Parsing - Formatted to explicitly state "Received the query:"
#         # push_tool_event("start", "Automation Query Parsing", f"Received the query: '{user_message}'")
#         # messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_message)]
#         # push_tool_event("complete", "Automation Query Parsing", "Query successfully processed.")

#         push_tool_event("start", "Received the user query", f"User query: '{user_message}'")
#         messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_message)]
#         push_tool_event("complete", "Received the user query", f"Query successfully processed: '{user_message}'")
        

#         # Step 2: Context Analysis
#         push_tool_event("start", "Context Intent Analysis", "Evaluating structural execution state limits...")
#         push_tool_event("complete", "Context Intent Analysis", "Analysis complete.")

#         # Step 3: Schema Matching
#         push_tool_event("start", "Schema Blueprint Matching", "Evaluating intent patterns against active JSON database schemas...")
        
#         has_tools = False
#         tool_payload = None
#         generation_text = ""

#         # --- ROUTE A: OPENAI ---
#         if model_name in ["gpt-4o-mini", "gpt-4o"]:
#             dynamic_llm = ChatOpenAI(model=model_name, temperature=0, openai_api_key=custom_key if custom_key else os.getenv("OPENAI_API_KEY"))
#             ai_response = dynamic_llm.bind_tools(llm_tools_list).invoke(messages)
            
#             has_tools = bool(ai_response.tool_calls)
#             tool_payload = ai_response.tool_calls if has_tools else None
#             generation_text = ai_response.content

#         # --- ROUTE B: LOCAL OLLAMA ---
#         elif model_name == "llama3":
#             if not ollama_config:
#                 ollama_config = {"url": "http://localhost:11434/api/chat", "temperature": 0}
#             payload = {
#                 "model": "llama3",
#                 "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_message}],
#                 "tools": llm_tools_list,
#                 "stream": False,
#                 "options": {"temperature": 0}
#             }
#             response = requests.post(ollama_config["url"], json=payload, timeout=300)
#             response.raise_for_status()
#             ai_message = response.json().get("message", {})
            
#             has_tools = bool(ai_message.get("tool_calls"))
#             tool_payload = ai_message.get("tool_calls") if has_tools else None
#             generation_text = ai_message.get("content", "")

#         # --- ROUTE C: DYNAMIC CLOUD PROVIDERS (api://) ---
#         elif str(model_name).startswith("api://"):
#             actual_model = model_name.replace("api://", "").lower()
#             if "claude" in actual_model:
#                 from langchain_anthropic import ChatAnthropic
#                 dynamic_llm = ChatAnthropic(model=actual_model, temperature=0, anthropic_api_key=custom_key if custom_key else os.getenv("ANTHROPIC_API_KEY"))
#             elif "gemini" in actual_model:
#                 from langchain_google_genai import ChatGoogleGenerativeAI
#                 dynamic_llm = ChatGoogleGenerativeAI(model=actual_model, temperature=0, google_api_key=custom_key if custom_key else os.getenv("GOOGLE_API_KEY"))
#             elif "deepseek" in actual_model:
#                 dynamic_llm = ChatOpenAI(model=actual_model, temperature=0, openai_api_key=custom_key if custom_key else os.getenv("DEEPSEEK_API_KEY"), openai_api_base="https://api.deepseek.com/v1")
#             else:
#                 dynamic_llm = ChatOpenAI(model=actual_model, temperature=0, openai_api_key=custom_key if custom_key else os.getenv("OPENAI_API_KEY"))

#             ai_response = dynamic_llm.bind_tools(llm_tools_list).invoke(messages)
#             has_tools = bool(ai_response.tool_calls)
#             tool_payload = ai_response.tool_calls if has_tools else None
#             generation_text = ai_response.content

#         # --- ROUTE D: DYNAMIC LOCAL OLLAMA (ollama://) ---
#         elif str(model_name).startswith("ollama://"):
#             actual_model = model_name.replace("ollama://", "")
#             if not ollama_config:
#                 ollama_config = {"url": "http://localhost:11434/api/chat", "temperature": 0}
#             payload = {
#                 "model": actual_model,
#                 "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_message}],
#                 "tools": llm_tools_list,
#                 "stream": False,
#                 "options": {"temperature": 0}
#             }
#             response = requests.post(ollama_config["url"], json=payload, timeout=300)
#             response.raise_for_status()
#             ai_message = response.json().get("message", {})
#             has_tools = bool(ai_message.get("tool_calls"))
#             tool_payload = ai_message.get("tool_calls") if has_tools else None
#             generation_text = ai_message.get("content", "")
#         else:
#             raise ValueError(f"Target '{model_name}' has no active route handler.")

#         # Complete Step 3 cleanly
#         push_tool_event("complete", "Schema Blueprint Matching", "Model evaluation complete.")

#         # Guardrail check: Refusal Path
#         if not has_tools:
#             push_tool_event("start", "Response Synthesis", "Parsing execution payload...")
#             push_tool_event("complete", "Response Synthesis", "Rejection rule triggered.")
#             stream_manager.push_step(session_id, "DONE", is_sql=False)
#             return {
#                 "answer": "ERROR: No matching workflow tool found to execute this request.",
#                 "tool_calls": None, "sql": None, "table": [], "chart": {}, "insights": [], "steps": tool_chain_of_thought
#             }

#         # Success Path - Dynamic Database API Call Resolution
#         if has_tools and not generation_text:
#             try:
#                 # 1. Grab target tool name from payload
#                 target_name = tool_payload[0]['name'] if isinstance(tool_payload[0], dict) else tool_payload[0].name
                
#                 # 2. Extract runtime parameters if passed
#                 tool_args = tool_payload[0].get('args', {}) if isinstance(tool_payload[0], dict) else tool_payload[0].arguments
#                 if isinstance(tool_args, str):
#                     tool_args = json.loads(tool_args)

#                 # 3. Connect to your database configuration table
#                 base_uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')
#                 result = urlparse(base_uri)
#                 dsn = f"postgresql://{result.username}:{result.password}@{result.hostname}:{result.port or 5432}/saarthi_api_db"
                
#                 conn = psycopg2.connect(dsn)
#                 cursor = conn.cursor()
#                 cursor.execute("SELECT base_url, endpoint, method FROM registered_tools WHERE integration_name = %s LIMIT 1;", (target_name,))
#                 api_meta = cursor.fetchone()
#                 cursor.close()
#                 conn.close()

#                 if api_meta:
#                     base_url, endpoint, method = api_meta[0], api_meta[1], api_meta[2]
#                     full_target_url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"
                    
#                     # Step 4: Live Tool Execution starts and runs completely first
#                     push_tool_event("start", "Live Tool Execution", f"Executing REST API via {method} protocol...")
                    
#                     # 4. Handle GET vs POST dynamics cleanly using database configuration
#                     if str(method).upper() == "POST":
#                         api_res = requests.post(url=full_target_url, json=tool_args, timeout=15)
#                     else:
#                         api_res = requests.get(url=full_target_url, params=tool_args, timeout=15)
                        
#                     raw_data = api_res.json()
#                     push_tool_event("complete", "Live Tool Execution", "Dynamic REST execution complete.")
                    
#                     # Step 5: Response Synthesis ONLY starts after the live tool response arrives
#                     push_tool_event("start", "Response Synthesis", "Parsing execution payload...")
                    
#                     # 5. Fast contextual refinement step to isolate specific user intent from raw data array
#                     refinement_prompt = [
#                         SystemMessage(content="You are an expert data analysis engine. Read the following raw API dataset payload context and provide a precise, targeted answer to the user's specific request. Do not include unneeded object structures or JSON syntax wrappers."),
#                         HumanMessage(content=f"User intent request: {user_message}\n\nLive API Fetched Raw Dataset Context:\n{str(raw_data)[:3500]}")
#                     ]
                    
#                     openai_api_key = custom_key if custom_key else os.getenv("OPENAI_API_KEY")
#                     refinement_llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, openai_api_key=openai_api_key)
#                     generation_text = refinement_llm.invoke(refinement_prompt).content
#                     push_tool_event("complete", "Response Synthesis", "Workflow tool successfully mapped.")
#                 else:
#                     push_tool_event("start", "Response Synthesis", "Parsing execution payload...")
#                     generation_text = f"Tool properties for execution identifier '{target_name}' could not be located in database records."
#                     push_tool_event("complete", "Response Synthesis", "Failed: Tool database configurations missing.")
            
#             except Exception as e:
#                 push_tool_event("start", "Response Synthesis", "Parsing execution payload...")
#                 generation_text = f"Tool identified successfully, but dynamic automation handler failed: {str(e)}"
#                 push_tool_event("complete", "Response Synthesis", f"Failed: {str(e)}")

#         time.sleep(0.5)
#         stream_manager.push_step(session_id, "DONE", is_sql=False)
        
#         return {
#             "answer": generation_text,
#             "tool_calls": tool_payload,
#             "sql": None, "table": [], "chart": {}, "insights": [], "steps": tool_chain_of_thought
#         }

#     except Exception as e:
#         print(f"Engine failure: {str(e)}")
#         stream_manager.push_step(session_id, "DONE", is_sql=False)
#         return {
#             "answer": f"The system encountered an error processing your routing request: {str(e)}",
#             "tool_calls": None, "sql": None, "table": [], "chart": {}, "insights": [], "steps": tool_chain_of_thought
#         }