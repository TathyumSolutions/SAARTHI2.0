import os
import nltk
import ssl
import time
import re
from langchain_community.document_loaders import (
    PyPDFLoader, 
    Docx2txtLoader, 
    TextLoader, 
    UnstructuredMarkdownLoader,
    UnstructuredRTFLoader
)
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
#from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from dotenv import load_dotenv
import requests 
import json
#from .databridge_services import run_data_bridge_agent
from .databridge_services.langgraph_agent import run_data_bridge_agent
from app.services.stream_manager import stream_manager

load_dotenv()

class LLMService:
    """Service for LLM provider interactions and RAG pipeline"""
    
    def __init__(self):
        # Initialize NLTK
        try:
            _create_unverified_https_context = ssl._create_unverified_context
        except AttributeError:
            pass
        else:
            ssl._create_default_https_context = _create_unverified_https_context

        # Initialize NLTK - forcing the download of both required pieces
        try:
            nltk.download('punkt')
            nltk.download('punkt_tab')
        except Exception as e:
            print(f"NLTK Download Warning: {e}")
        # --- FIX ENDS HERE ---
    
        
        # Initialize Embeddings Model
        self.embeddings_model = HuggingFaceEmbeddings(
            model_name="sentence-transformers/all-MiniLM-L6-v2"
        )

        # Permanent Docker Config
        self.qdrant_url = "http://qdrant:6333"
        self.collection_name = "saarthi_unstructured"

        self.llm = ChatOpenAI(
            model="gpt-4o-mini",
            temperature=0,
            openai_api_key=os.getenv("OPENAI_API_KEY")
        )



        # Permanent Docker Config for Ollama (Direct API)
        self.ollama_config = {
            "type": "ollama",
            "url": "http://ollama:11434/api/generate",
            "model": "phi3:mini",
            "max_tokens": 1024,
            "temperature": 0.0,
            "timeout": 300,
            "num_ctx":8192
        }

        BASE_DIR = os.path.dirname(os.path.abspath(__file__))
        schema_path = os.path.join(BASE_DIR, 'databridge_services', 'sap_schema_with_sap_comments.json')
        
        try:
            with open(schema_path, 'r') as f:
                self.schema_data = json.load(f)
            
            # Pre-compile human-readable string version for LLM context fallback
            tables_dict = self.schema_data.get("tables", self.schema_data)
            
            schema_lines = []
            for table_name, table_info in tables_dict.items():
                cols_dict = table_info.get("columns", {})
                cols_list = list(cols_dict.keys())
                schema_lines.append(f"Table '{table_name}': columns = {', '.join(cols_list)}")
            
            self.schema_str = "\n".join(schema_lines)
            print("✅ Schema loaded successfully into LLMService memory")
        except Exception as e:
            print(f"⚠️ Schema loading failed: {e}")
            self.schema_data = {}
            self.schema_str = "No schema available"


        # ============================================
        # PREBUILD LOOKUP KEYWORDS FOR FAST HEURISTICS
        # ============================================
        self.schema_keywords = self.build_schema_keywords()
        print(f"✅ Loaded {len(self.schema_keywords)} quick-lookup schema tokens")

        self.sql_patterns = {
            "list", "show", "count", "total", "find", "fetch", 
            "display", "records", "entries", "all", "how many", 
            "top", "highest", "lowest", "average", "sum"
        }

    # --- Fast Lookup Helper Methods ---
    
    def build_schema_keywords(self):
        keywords = set()
        # Safe handling for the "tables" wrapper key in your schema JSON layout
        tables_dict = self.schema_data.get("tables", self.schema_data)
        
        for table_name, table_info in tables_dict.items():
            keywords.add(str(table_name).lower())
            
            # Extract nested keys from inside the columns dictionary block
            cols_dict = table_info.get("columns", {})
            if isinstance(cols_dict, dict):
                for col_name in cols_dict.keys():
                    keywords.add(str(col_name).lower())
                    # Split column names containing underscores to capture separate words
                    if "_" in col_name:
                        keywords.update(col_name.lower().split("_"))
                        
        keywords = {kw.strip() for kw in keywords if len(kw.strip()) > 1}
        return keywords

    

    def fast_sql_check(self, user_query):
        clean_query = re.sub(r'[^\w\s]', ' ', user_query.lower())
        query_words = set(clean_query.split())
        matched_keywords = query_words.intersection(self.schema_keywords)
        return list(matched_keywords)

    def has_sql_intent(self, user_query):
        query_lower = user_query.lower()
        return any(pattern in query_lower for pattern in self.sql_patterns)   

    # --- Placeholder Functions (Kept exactly as requested) ---
    def generate_sql(self, natural_language_query, database_schema):
        pass
    
    def chat_completion(self, messages, model_config):
        pass
    
    def generate_insights(self, data, context):
        pass
    
    def validate_sql(self, sql_query, database_schema):
        pass

    # --- Core Processing Logic ---

    def process_to_embeddings(self, file_path, document_code=None):
        """
        Loads document, creates chunks, generates embeddings, and stores in Qdrant.
        """
        if not os.path.exists(file_path):
            return {"error": f"File not found at {file_path}"}

        ext = os.path.splitext(file_path)[-1].lower()
        
        try:
            # 1. Loader Selection
            if ext == ".pdf":
                loader = PyPDFLoader(file_path)
            elif ext in [".docx", ".doc"]:
                loader = Docx2txtLoader(file_path)
            elif ext == ".md":
                loader = UnstructuredMarkdownLoader(file_path)
            elif ext == ".rtf":
                loader = UnstructuredRTFLoader(file_path)
            else:
                loader = TextLoader(file_path)

            # Load the data
            documents = loader.load()

            # 2. Chunking
            text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=800, 
                chunk_overlap=80
            )
            chunks = text_splitter.split_documents(documents)

            # Add metadata to identify chunks by document code
            for chunk in chunks:
                chunk.metadata["document_code"] = document_code

            # 3. Store in Qdrant Vector Database
            # This handles both embedding and storage in one go
            QdrantVectorStore.from_documents(
                documents=chunks,
                embedding=self.embeddings_model,
                url=self.qdrant_url,
                collection_name=self.collection_name,
                force_recreate=False
            )
            
            # Return the exact success message for your frontend
            return {
                "status": "success",
                "message": "Embeddings are stored in vector database successfully",
                "chunk_count": len(chunks)
            }

        except Exception as e:
            return {"error": f"Processing failed: {str(e)}"}

  

    def answer_from_docs(self, user_query, session_id=1):
        """
        Retrieves relevant chunks from Qdrant and updates the live steps 
        using the new structured event payload layout.
        """
        rag_chain_of_thought = []
        session_id = str(session_id)
        
        # ========================================================
        # --- CODE CHANGE START ---
        # HELPER FUNCTION TO STREAM DICTIONARY OBJECTS TO THE NEW UI
        # ========================================================
        def push_rag_event(event_type, title, description):
            payload = {
                "event": event_type,
                "title": title,
                "description": description,
                "is_sql": False
            }
            if event_type == "start":
                rag_chain_of_thought.append(f"{title} - {description}")
            
            # Pushes the required map data structure down to StepStreamManager
            stream_manager.push_step(session_id, payload, is_sql=False)
            time.sleep(0.3) # Give frontend rendering engine time to execute animations
        # --- CODE CHANGE END ---
        # ========================================================

        try:
            # ========================================================
            # STEP 1: INQUIRY RECEIVED
            # ========================================================
            # --- CODE CHANGE START ---
            # Old implementation: stream_manager.push_step(session_id, "Step 1: Document Query Parsing...", False)
            push_rag_event("start", "Document Query Parsing", f"Analyzing raw unstructured prompt: '{user_query}'")
            # --- CODE CHANGE END ---
            
            client = QdrantClient(url=self.qdrant_url)
            vector_store = QdrantVectorStore(
                client=client,
                collection_name=self.collection_name,
                embedding=self.embeddings_model
            )
            
            # --- CODE CHANGE START ---
            push_rag_event("complete", "Document Query Parsing", "Query successfully processed and converted to dense vectors.")
            # --- CODE CHANGE END ---

            # ========================================================
            # STEP 2: INTENT ANALYSIS
            # ========================================================
            # --- CODE CHANGE START ---
            push_rag_event("start", "Context Intent Analysis", "Querying local LLM instance for contextual definition profiles...")
            # --- CODE CHANGE END ---
            
            try:
                cot_payload = {
                    "model": self.ollama_config["model"],
                    "prompt": f"Describe the analysis of this query in one short sentence: '{user_query}'. Output only the sentence.",
                    "stream": False,
                    "options": {"temperature": self.ollama_config["temperature"]}
                }
                cot_res = requests.post(self.ollama_config["url"], json=cot_payload, timeout=10)
                analysis_text = cot_res.json().get("response", "Analyzing document index for relevant parameters.").strip()
            except Exception:
                analysis_text = "Analyzing natural language inquiry for document matching modules."
            
            # --- CODE CHANGE START ---
            push_rag_event("complete", "Context Intent Analysis", analysis_text)
            # --- CODE CHANGE END ---

            # ========================================================
            # STEP 3: KNOWLEDGE BASE RETRIEVAL
            # ========================================================
            # --- CODE CHANGE START ---
            push_rag_event("start", "Vector Space Search", "Scanning local Qdrant collections for high-probability matching fragments...")
            # --- CODE CHANGE END ---
            
            docs = vector_store.similarity_search(user_query, k=3)
            context_text = "\n\n".join([doc.page_content for doc in docs])
            
            retrieval_msg = f"Successfully matched and isolated {len(docs)} high-relevance documentation segments."
            
            # --- CODE CHANGE START ---
            push_rag_event("complete", "Vector Space Search", retrieval_msg)
            # --- CODE CHANGE END ---

            if not context_text:
                stream_manager.push_step(session_id, "DONE", is_sql=False)
                return {
                    "answer": "I couldn't find any relevant information in the uploaded documents.",
                    "sql": None,
                    "table": [],
                    "chart": {},
                    "rag_chain_of_thought": rag_chain_of_thought
                }

            # ========================================================
            # STEP 4: RESPONSE SYNTHESIS
            # ========================================================
            # --- CODE CHANGE START ---
            push_rag_event("start", "Response Synthesis", f"Processing matrices through {self.llm.model_name} to compile answers...")
            # --- CODE CHANGE END ---
            
            system_prompt = (
                "You are Saarthi AI, a helpful assistant. Answer the user's question "
                "using ONLY the following context. If the answer is not in the context, "
                "politely say you don't know based on the documents.\n\n"
                f"CONTEXT:\n{context_text}"
            )
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_query)
            ]
            ai_response = self.llm.invoke(messages)
            
            # --- CODE CHANGE START ---
            push_rag_event("complete", "Response Synthesis", "Final descriptive insights generated successfully.")
            # --- CODE CHANGE END ---

            # Final execution loop boundary closeout
            stream_manager.push_step(session_id, "DONE", is_sql=False)

            return {
                "answer": ai_response.content,
                "sql": None,  
                "table": [],
                "chart": {},
                "rag_chain_of_thought": rag_chain_of_thought
            }

        except Exception as e:
            print(f"Retrieval Error Trace: {str(e)}")
            stream_manager.push_step(session_id, "DONE", is_sql=False)
            return {
                "answer": "The system encountered an error while searching the document database.",
                "sql": None,
                "table": [],
                "chart": {},
                "rag_chain_of_thought": rag_chain_of_thought
            }    
       

    def get_smart_response(self, user_query, session_id=1):
        """
        Layered high-speed query execution routing pipeline.
        Uses phi3:mini directly to categorize user query path intent.
        """
        try:
            print("\n" + "=" * 60)
            print(f"🧠 SMART ROUTER PROCESSING QUERY: {user_query}")

            # ----------------------------------------------------
            # LAYER 1: FAST HEURISTIC PATTERN PASS
            # ----------------------------------------------------
            matched_keywords = self.fast_sql_check(user_query)
            sql_intent = self.has_sql_intent(user_query)

            lower_query = user_query.lower().strip()
            
            # 1. Broad conversational/informational phrase triggers
            rag_phrases = ["what is", "what does", "tell me about", "explain", "meaning of", "who is", "how do i", "where can i"]
            
            # 2. Key operational indicators that clearly target structured computational data
            sql_indicators = ["total", "how many", "count", "sum", "average", "avg", "list", "top", "maximum", "max", "highest", "lowest"]
            
            has_rag_phrase = any(phrase in lower_query for phrase in rag_phrases)
            has_sql_indicator = any(indicator in lower_query for indicator in sql_indicators)
            
            # If a query matches a conversational pattern but contains NO data computation keywords 
            # and triggers no specific database table keywords, intercept it immediately as a RAG document request.
            if has_rag_phrase and not has_sql_indicator:
            #if has_rag_phrase and not (matched_keywords or has_sql_indicator):
                print("📄 [INTELLIGENT RAG GUARD] -> Pure descriptive intent detected. Routing directly to RAG.")
                rag_res = self.answer_from_docs(user_query, session_id=session_id)
                steps_list = rag_res.get("rag_chain_of_thought", [])
                return {
                    "answer": rag_res.get("answer"),
                    "sql": None,
                    "table": [],
                    "chart": {},
                    "steps": steps_list
                }

            # ----------------------------------------------------
            # LAYER 2: FAST HEURISTIC PATTERN PASS FOR PURE SQL
            # ----------------------------------------------------
            if matched_keywords and sql_intent:
                print("🚀 [FAST PATH TRIGGERED] -> Confirmed structured operational query. Routing straight to SQL.")
                full_result = run_data_bridge_agent(user_query, session_id=session_id)
                return full_result["chat_ui"]



            router_prompt = f"""
You are an intelligent query router for an enterprise AI system.

DATABASE SCHEMA:
{self.schema_str}

USER QUERY:
"{user_query}"

YOUR JOB:
Decide if this query should be answered from:
1. SQL - database tables shown above
2. RAG - uploaded documents/PDFs/text files

RULES:
- If the query is asking for data that EXISTS as a column in the schema above, choose SQL.
- If the query is asking for information NOT found in the schema (explanations, descriptions, policies, document content,summaries), choose RAG.
- If the same word (like "company") exists both in schema AND could be in documents, look at the INTENT:
  * "List all companies" → SQL (wants rows/records)
  * "What does the company do?" → RAG (wants description)
  * "How many companies?" → SQL (wants count)
  * "Tell me about the company" → RAG (wants explanation)

Respond with ONLY: SQL or RAG.
"""

            response = requests.post(
                self.ollama_config["url"],
                json={
                    "model": self.ollama_config["model"],  # ⚡ Explicitly runs phi3:mini
                    "prompt": router_prompt,
                    "stream": False,
                    "keep_alive": "30m",
                    "options": {
                        "temperature": 0.0,
                        "num_ctx": 8192,
                        "num_predict": 3,
                        "num_thread": 4
                    }
                },
                timeout=60
            )
            response.raise_for_status()
            res_text = response.json().get("response", "").strip().upper()
            print(f"🧠 Router LLM Decision: {res_text}")

            # ----------------------------------------------------
            # LAYER 3: PATH SPECIFIC EXECUTION ASSIGNMENT
            # ----------------------------------------------------
            if "SQL" in res_text:
                print("📊 ROUTING DIRECTION -> DATA BRIDGE LANGRAPH NETWORK")

                import time
                time.sleep(0.2)
                stream_manager.push_step(
                    session_id, 
                    "Router Analysis - Fast Path Heuristic Triggered: Bypassing router LLM.", 
                    is_sql=True)
                full_result = run_data_bridge_agent(user_query, session_id=session_id)
                stream_manager.push_step(session_id, "DONE", is_sql=True)

                if isinstance(full_result.get("chat_ui"), dict) and "Error at error_diagnosis" in full_result["chat_ui"].get("answer", ""):
                    full_result["chat_ui"]["answer"] = (
                        "I encountered an issue while generating the database query. Please check if the requested column or table exists in your schema."
                    )

                return full_result["chat_ui"]
            else:
                print("📄 ROUTING DIRECTION -> UNSTRUCTURED KNOWLEDGE DATABASE RAG")
                #return self.answer_from_docs(user_query, session_id=session_id)
                rag_res = self.answer_from_docs(user_query, session_id=session_id)
                steps_list = rag_res.get("rag_chain_of_thought", [])
                #for step in steps_list:
                #    stream_manager.push_step(session_id, step, is_sql=False)

                return {
                    "answer": rag_res.get("answer"),
                    "sql": None,
                    "table": [],
                    "chart": {},
                    "steps": steps_list  # Maps rag_chain_of_thought to steps
                }
        except requests.exceptions.Timeout:
            print("⏰ Router processing limit reached -> Fallback to RAG")
            rag_res = self.answer_from_docs(user_query, session_id=session_id)
            steps_list = rag_res.get("rag_chain_of_thought", [])
            
            for step in steps_list:
                stream_manager.push_step(session_id, step, is_sql=False)
            stream_manager.push_step(session_id, "DONE", is_sql=False)    
            return {
                "answer": rag_res.get("answer"),
                "sql": None,
                "table": [],
                "chart": {},
                "steps": steps_list
            }
        
        except Exception as e:
            import traceback
            print("\n❌ [CRITICAL SQL PIPELINE FAILURE] The database agent crashed!")
            traceback.print_exc()
            stream_manager.push_step(
                session_id, 
                "❌ Pipeline Execution Failure detected in Router Layer.", 
                is_sql=True
            )
            stream_manager.push_step(
                session_id, 
                f"⚠️ Diagnosed Error: {str(e)}", 
                is_sql=True
            )
            stream_manager.push_step(session_id, "DONE", is_sql=True)
            
            return {
                "answer": f"SQL Execution Error: {str(e)}",
                "sql": None,
                "table": [],
                "chart": {},
                "steps": [f"Pipeline failed at router layer: {str(e)}"]
            }

        
                  