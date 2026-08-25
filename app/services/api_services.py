from flask import current_app
import os
import re
import time
import requests
import json
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from app.services.stream_manager import stream_manager
from app.utils.network_guard import is_safe_url, build_full_api_url
from app.utils.redaction import redact_secrets
from app.utils.crypto import decrypt
from app.models.api_connector import ApiConnector
from app.services.llm_call_logger import tracked_invoke, record_ollama_call


def _auth_headers_and_params(auth_type, encrypted_token):
    """
    Builds the request header(s)/query param(s) for a registered API
    tool's saved auth_type/api_token - without this, every authenticated
    integration (auth_type "API Key" or "Bearer Token") gets called with
    no credentials at all, and fails with a 401/403 that then gets
    narrated back to the user as "the API endpoint does not exist or
    access is not permitted", which reads like a broken registration
    rather than what it actually is (missing credentials).

    "API Key" auth covers a lot of real-world APIs with no single
    convention - some read a header, but plenty of public data APIs
    (e.g. api.metals.dev, and much of the free-tier finance/weather/data
    API space) only accept the key as a `?api_key=...` query parameter
    and silently ignore any header. Sending it both ways covers both
    conventions without needing per-integration configuration for where
    the key goes.
    """
    token = decrypt(encrypted_token) if encrypted_token else None
    normalized_type = (auth_type or '').strip().casefold()
    if not token:
        return {}, {}
    if normalized_type == 'bearer token':
        return {'Authorization': f'Bearer {token}'}, {}
    if normalized_type == 'api key':
        return {'X-API-Key': token}, {'api_key': token}
    return {}, {}


def _sanitize_tool_name(name):
    """
    Integration names are free-text (e.g. "Copper Price API"), but
    OpenAI-compatible function-calling APIs require tool names to match
    ^[a-zA-Z0-9_-]+$. Translate into a safe identifier before it's handed
    to the LLM as a tool/function name.
    """
    sanitized = re.sub(r'[^a-zA-Z0-9_-]+', '_', name or '').strip('_')
    return sanitized or 'tool'


def fetch_and_translate_tools():
    """
    Loads active API connectors and translates them into the structured
    tool schema the LLM expects.
    """
    tools = ApiConnector.query.filter_by(status='Active').all()

    return [
        {
            "type": "function",
            "function": {
                "name": _sanitize_tool_name(tool.integration_name),
                "description": redact_secrets(tool.api_description),
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            }
        }
        for tool in tools
    ]


def ask_dynamic_model_with_tools(user_message, llm_tools_list, model_name, session_id=1, custom_key='', ollama_config=None,display_query=None,system_instructions='',feedback_context='',hint_tool_name=''):
    """
    Dynamically routes queries to models, strictly enforcing tool execution,
    performs the actual API execution, and returns a fully parsed response context.

    hint_tool_name: the specific registered tool the router already
    identified from the LIVE REGISTERED TOOLS metadata (router_service.py's
    call_external_api tool call). Resolved below against the tool names
    actually on offer in llm_tools_list - only a real match is used, so a
    stale or invented name from the router just falls back to letting the
    model choose freely, never a lookup error.
    """

    log_query = display_query if display_query else user_message
    tool_chain_of_thought = []
    session_id = str(session_id)

    forced_tool_name = None
    if hint_tool_name:
        available_names = {t.get("function", {}).get("name") for t in llm_tools_list if isinstance(t, dict)}
        if hint_tool_name in available_names:
            forced_tool_name = hint_tool_name

    def _bind_tools(llm):
        """bind_tools with tool_choice forced to the router's metadata-based
        pick when one resolved - not every provider/model accepts
        tool_choice the same way, so this falls back to an unforced bind on
        any rejection rather than breaking the whole request over it."""
        if forced_tool_name:
            try:
                return llm.bind_tools(llm_tools_list, tool_choice=forced_tool_name)
            except Exception as e:
                print(f"⚠️ [API] tool_choice='{forced_tool_name}' rejected by this model, falling back to free choice: {e}")
        return llm.bind_tools(llm_tools_list)

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
    if forced_tool_name:
        system_prompt += (
            f"\n\nTOOL SELECTED BY THE ROUTER (from live tool metadata): '{forced_tool_name}'. "
            "Call exactly this tool for this request."
        )
    if system_instructions.strip():
        system_prompt += f"\n\nUSER CUSTOM FORMATTING INSTRUCTIONS:\n{system_instructions}"
    if feedback_context:
        print(f"🧠 [FEEDBACK-DEBUG] [API] Using feedback context:\n{feedback_context}")
        system_prompt += (
            f"\n\n{feedback_context}\n\n"
            "That is feedback on how PAST similar requests were handled, not part of this "
            "request. It can be about anything - wrong tool picked, wrong parameter value, "
            "wrong endpoint, a formatting problem. If any of it is still relevant here, adjust "
            "which tool or arguments you pick accordingly; ignore whatever doesn't apply."
        )

    try:
        push_tool_event("start", "Your Question", f"\"{user_message}\"")
        messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_message)]
        push_tool_event("complete", "Your Question", f"\"{user_message}\"")

        push_tool_event("start", "Understanding What You Need", "Reviewing your request to identify what action is needed.")
        push_tool_event("complete", "Understanding What You Need", "I understood what you need.")
        push_tool_event("start", "Finding the Right Tool", "Selecting the best available tool for your request.")

        has_tools = False
        tool_payload = None
        generation_text = ""
        is_local_ollama = False
        had_error = False

        # --- ROUTE A: OPENAI ---
        if model_name in ["gpt-4o-mini", "gpt-4o"]:
            dynamic_llm = ChatOpenAI(model=model_name, temperature=0, openai_api_key=custom_key if custom_key else os.getenv("OPENAI_API_KEY"))
            ai_response = tracked_invoke(
                _bind_tools(dynamic_llm), messages,
                purpose="api_tool.selection", model_name=model_name, provider="openai", session_id=session_id,
            )
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
            _t0 = time.monotonic()
            response = requests.post(ollama_config["url"], json=payload, timeout=300)
            response.raise_for_status()
            response_json = response.json()
            ai_message = response_json.get("message", {})
            has_tools = bool(ai_message.get("tool_calls"))
            tool_payload = ai_message.get("tool_calls") if has_tools else None
            generation_text = ai_message.get("content", "")
            record_ollama_call(
                purpose="api_tool.selection", model_name="llama3",
                prompt_text=f"{system_prompt}\n\n{user_message}",
                response_json={**response_json, "response": generation_text},
                duration_ms=int((time.monotonic() - _t0) * 1000), session_id=session_id,
            )

        # --- ROUTE C: DYNAMIC CLOUD PROVIDERS (api://) ---
        elif str(model_name).startswith("api://"):
            actual_model = model_name.replace("api://", "").lower()
            from app.services.llm_providers import resolve_dynamic_llm
            dynamic_llm = resolve_dynamic_llm(
                actual_model,
                custom_key,
                temperature=0,
                openai_fallback_key=os.getenv("OPENAI_API_KEY"),
                strict=False,
            )

            ai_response = tracked_invoke(
                _bind_tools(dynamic_llm), messages,
                purpose="api_tool.selection", model_name=actual_model, session_id=session_id,
            )
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
            _t0 = time.monotonic()
            response = requests.post(ollama_config["url"], json=payload, timeout=300)
            response.raise_for_status()
            response_json = response.json()
            ai_message = response_json.get("message", {})
            has_tools = bool(ai_message.get("tool_calls"))
            tool_payload = ai_message.get("tool_calls") if has_tools else None
            generation_text = ai_message.get("content", "")
            record_ollama_call(
                purpose="api_tool.selection", model_name=actual_model,
                prompt_text=f"{system_prompt}\n\n{user_message}",
                response_json={**response_json, "response": generation_text},
                duration_ms=int((time.monotonic() - _t0) * 1000), session_id=session_id,
            )
        else:
            raise ValueError(f"Target '{model_name}' has no active route handler.")

        # Resolve which registered tool the model actually picked *before*
        # announcing the selection, so the step can name it directly (e.g.
        # "Selected tool: Metal Price API") instead of a generic "Tool
        # selection complete." that gives the user nothing to trace.
        selected_tool = None
        target_name = None
        tool_args = {}
        if has_tools and tool_payload:
            try:
                target_name = tool_payload[0]['name'] if isinstance(tool_payload[0], dict) else tool_payload[0].name
                tool_args = tool_payload[0].get('args', {}) if isinstance(tool_payload[0], dict) else tool_payload[0].arguments
                if isinstance(tool_args, str):
                    tool_args = json.loads(tool_args)
            except Exception:
                target_name, tool_args = None, {}

            if target_name:
                selected_tool = next(
                    (t for t in ApiConnector.query.filter_by(status='Active').all()
                     if _sanitize_tool_name(t.integration_name) == target_name),
                    None
                )

        if selected_tool:
            push_tool_event("complete", "Finding the Right Tool", f"Selected tool: {selected_tool.integration_name}.")
        elif has_tools:
            push_tool_event("complete", "Finding the Right Tool", f"Selected tool: {target_name or 'unknown'} (its connection details could not be found).")
        else:
            push_tool_event("complete", "Finding the Right Tool", "No matching tool was found for this request.")

        if not has_tools:
            push_tool_event("start", "Putting Your Answer Together", "Preparing your final response.")
            push_tool_event("complete", "Putting Your Answer Together", "No matching tool was available for this request.")
            stream_manager.push_step(session_id, "DONE", is_sql=False)
            return {
                "answer": "I don't have a connected data source that covers this request.",
                "tool_calls": None, "sql": None, "table": [], "chart": {}, "insights": [], "steps": tool_chain_of_thought
            }

        if selected_tool:
            push_tool_event(
                "start",
                "Planning the Approach",
                f"Strategy: call {selected_tool.integration_name} with a {selected_tool.method} request to fetch the data needed for your question."
            )
            push_tool_event("complete", "Planning the Approach", f"Ready to call {selected_tool.integration_name}.")

        tool_call_detail = None

        if has_tools and not generation_text:
            try:
                tool = selected_tool

                if tool:
                    base_url, endpoint, method = tool.base_url, tool.endpoint, tool.method
                    full_target_url = build_full_api_url(base_url, endpoint)

                    # Re-checked here, not just at registration time - the
                    # host this resolves to today might not be the one it
                    # resolved to when the tool was registered (DNS can
                    # change), and this is what actually gets called.
                    safe, reason = is_safe_url(full_target_url)
                    if not safe:
                        push_tool_event("start", "Calling the Live System", "This tool's endpoint is no longer reachable.")
                        push_tool_event("complete", "Calling the Live System", "Blocked: the endpoint resolves to a private or internal address.")
                        stream_manager.push_step(session_id, "DONE", is_sql=False)
                        return {
                            "answer": "This tool's endpoint can't be called because it points to a private or internal address.",
                            "tool_calls": None, "sql": None, "table": [], "chart": {}, "insights": [], "steps": tool_chain_of_thought
                        }

                    push_tool_event("start", "Calling the Live System", f"Calling {tool.integration_name} with a {method} request.")

                    auth_headers, auth_params = _auth_headers_and_params(tool.auth_type, tool.api_token)
                    print(f"🔌 DEBUG [{tool.integration_name}] auth_type={tool.auth_type!r} "
                          f"has_token={bool(tool.api_token)} header_sent={list(auth_headers.keys()) or 'none'} "
                          f"param_sent={list(auth_params.keys()) or 'none'} url={full_target_url}")

                    if str(method).upper() == "POST":
                        api_res = requests.post(url=full_target_url, json=tool_args, params=auth_params, headers=auth_headers, timeout=15)
                    else:
                        api_res = requests.get(url=full_target_url, params={**auth_params, **(tool_args or {})}, headers=auth_headers, timeout=15)

                    print(f"🔌 DEBUG [{tool.integration_name}] response status={api_res.status_code} "
                          f"body_preview={api_res.text[:300]!r}")

                    raw_data = api_res.json()
                    push_tool_event("complete", "Calling the Live System", f"{tool.integration_name} responded successfully.")

                    # Mirrors the "View technical query" detail the SQL track
                    # shows for its generated query - lets anyone trace this
                    # answer back to the exact live request that produced it.
                    tool_call_detail = {
                        "tool_name": tool.integration_name,
                        "method": method,
                        "url": full_target_url,
                        "params": tool_args or {},
                    }

                    push_tool_event("start", "Putting Your Answer Together", "Formatting the result into a clear answer.")

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
                        _t0 = time.monotonic()
                        refine_res = requests.post(ollama_config["url"], json=refine_payload, timeout=300)
                        refine_res.raise_for_status()
                        refine_json = refine_res.json()
                        generation_text = refine_json.get("message", {}).get("content", "")
                        record_ollama_call(
                            purpose="api_tool.answer_refinement", model_name=target_ollama_model,
                            prompt_text=f"{refinement_sys_msg}\n\n{refinement_usr_msg}",
                            response_json={**refine_json, "response": generation_text},
                            duration_ms=int((time.monotonic() - _t0) * 1000), session_id=session_id,
                        )

                    # Reuses selected cloud model type cleanly
                    else:
                        refinement_prompt = [
                            SystemMessage(content=refinement_sys_msg),
                            HumanMessage(content=refinement_usr_msg)
                        ]

                        refinement_model_name = model_name
                        refinement_provider = "openai"
                        if model_name in ["gpt-4o-mini", "gpt-4o"]:
                            refinement_llm = ChatOpenAI(model=model_name, temperature=0, openai_api_key=custom_key if custom_key else os.getenv("OPENAI_API_KEY"))
                        elif str(model_name).startswith("api://"):
                            actual_model = model_name.replace("api://", "").lower()
                            refinement_model_name = actual_model
                            refinement_provider = None
                            from app.services.llm_providers import resolve_dynamic_llm
                            refinement_llm = resolve_dynamic_llm(
                                actual_model,
                                custom_key,
                                temperature=0,
                                openai_fallback_key=os.getenv("OPENAI_API_KEY"),
                                strict=False,
                            )
                        else:
                            refinement_model_name = "gpt-4o-mini"
                            refinement_llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, openai_api_key=custom_key if custom_key else os.getenv("OPENAI_API_KEY"))

                        generation_text = tracked_invoke(
                            refinement_llm, refinement_prompt,
                            purpose="api_tool.answer_refinement", model_name=refinement_model_name,
                            provider=refinement_provider, session_id=session_id,
                        ).content

                    push_tool_event("complete", "Putting Your Answer Together", "Your answer is ready.")
                else:
                    push_tool_event("start", "Putting Your Answer Together", "Formatting the result into a clear answer.")
                    had_error = True
                    generation_text = "I found a matching tool for this request, but its connection details are missing. Please check the API Integrations setup."
                    print(f"Tool properties for execution identifier '{target_name}' could not be located in database records.")
                    push_tool_event("complete", "Putting Your Answer Together", "Could not find configuration for the selected tool.")

            except Exception as e:
                push_tool_event("start", "Putting Your Answer Together", "Formatting the result into a clear answer.")
                had_error = True
                generation_text = "I found a matching tool for this request, but the connected system didn't respond successfully, so I can't provide this data right now."
                print(f"Dynamic automation handler failed: {str(e)}")
                push_tool_event("complete", "Putting Your Answer Together", f"Could not complete the tool run: {str(e)}")

        time.sleep(0.5)
        stream_manager.push_step(session_id, "DONE", is_sql=False)

        return {
            "answer": generation_text,
            "tool_calls": tool_payload,
            "sql": None, "table": [], "chart": {}, "insights": [], "steps": tool_chain_of_thought,
            "error": had_error,
            "tool_call": tool_call_detail,
        }

    except Exception as e:
        print(f"Engine failure: {str(e)}")
        stream_manager.push_step(session_id, "DONE", is_sql=False)
        return {
            "answer": "I couldn't reach the connected external system for this request. Please try again in a moment, or let us know if the issue continues.",
            "tool_calls": None, "sql": None, "table": [], "chart": {}, "insights": [], "steps": tool_chain_of_thought,
            "error": True,
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