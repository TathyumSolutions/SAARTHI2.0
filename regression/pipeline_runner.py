"""Runs a question through Saarthi's real DataBridge (LangGraph) pipeline.

Nothing in the pipeline is mocked. The harness only supplies what the web
app normally looks up per user:
  - the schema: the demo database introspected by the same functions the
    "Process" button uses (introspect_databridge_db + _infer_db_relations),
    passed as router_config;
  - the connection generated SQL runs against (the demo database);
  - a throwaway SQLite app database, so model-selection lookups and LLM
    call logging work without the production databases.
"""
import importlib.util
import os
import sys
import tempfile
import time
import traceback
from dataclasses import dataclass, field
from typing import Optional
from unittest.mock import MagicMock

from regression.settings import DbTarget, ollama_url

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


@dataclass
class PipelineOutcome:
    question_id: str
    sql: Optional[str] = None
    columns: list = field(default_factory=list)
    rows: list = field(default_factory=list)
    message: str = ""
    error: Optional[str] = None
    duration_s: float = 0.0
    steps: list = field(default_factory=list)

    def to_json(self) -> dict:
        return {k: getattr(self, k) for k in
                ("question_id", "sql", "columns", "rows", "message", "error", "duration_s", "steps")}


def _stub_unavailable_embeddings():
    """llm_service builds a HuggingFace embeddings client at import time.
    The DB track never embeds anything, so when the package (and its
    multi-GB torch dependency) is absent it is stubbed - the same stub
    tests/conftest.py uses."""
    if importlib.util.find_spec("langchain_huggingface") is None:
        fake = MagicMock()
        fake.HuggingFaceEmbeddings = MagicMock(return_value=MagicMock())
        sys.modules.setdefault("langchain_huggingface", fake)


def build_router_config(target: DbTarget) -> dict:
    """The routing menu the app would build for a user whose only data
    source is this database."""
    from app.services.automated_metamind import _infer_db_relations, introspect_databridge_db

    tables = introspect_databridge_db(target.as_psycopg2())
    if not tables:
        raise RuntimeError(f"Could not introspect {target.dbname} on {target.host}:{target.port}")
    return {"routing_menu": {
        "datasources": {"DB": {"tables": tables}},
        "inferred_relations": _infer_db_relations(tables),
    }}


class PipelineSession:
    """Context manager: one Flask app + introspected schema, reused for
    every question of a domain."""

    def __init__(self, target: DbTarget, model: str, api_key: str = ""):
        self.target = target
        self.model = model
        self.api_key = api_key
        self._tmpdir = None
        self._ctx = None
        self._patches = []
        self.router_config = None

    def __enter__(self):
        _stub_unavailable_embeddings()
        self._tmpdir = tempfile.TemporaryDirectory(prefix="saarthi-regression-")
        sqlite_base = f"sqlite:///{self._tmpdir.name}/app"

        from config.config import TestingConfig
        TestingConfig.SQLALCHEMY_DATABASE_URI = f"{sqlite_base}_core.db"
        TestingConfig.SQLALCHEMY_BINDS = {
            "core": f"{sqlite_base}_core.db",
            "resources": f"{sqlite_base}_resources.db",
            "workspace": f"{sqlite_base}_workspace.db",
        }
        from app import create_app, db
        app = create_app("testing")
        self._ctx = app.app_context()
        self._ctx.push()
        db.create_all()

        from app.services.databridge_services import langgraph_agent
        target_config = self.target.as_psycopg2()
        self._patch(langgraph_agent, "_build_db_config_for_user", lambda user_id: dict(target_config))
        if not self.model.startswith("api://"):
            self._point_agents_at_ollama(langgraph_agent)

        self.router_config = build_router_config(self.target)
        return self

    def __exit__(self, *exc):
        for obj, name, original in reversed(self._patches):
            setattr(obj, name, original)
        if self._ctx is not None:
            self._ctx.pop()
        if self._tmpdir is not None:
            self._tmpdir.cleanup()
        return False

    def _patch(self, obj, name, value):
        self._patches.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def _point_agents_at_ollama(self, langgraph_agent):
        """Agents default to the docker-compose host http://ollama:11434."""
        generate_url = f"{ollama_url().rstrip('/')}/api/generate"
        self._patch(langgraph_agent, "LLM_BACKEND", {**langgraph_agent.LLM_BACKEND, "url": generate_url})
        original_build = langgraph_agent._build_request_agents

        def build_with_local_urls(schema, model_name):
            agents = original_build(schema, model_name)
            for agent in agents.values():
                for attr in ("llm_url", "url", "ollama_url"):
                    if hasattr(agent, attr):
                        setattr(agent, attr, generate_url)
                inner = getattr(agent, "query_sense", None)
                if inner is not None and hasattr(inner, "url"):
                    inner.url = generate_url
            return agents

        self._patch(langgraph_agent, "_build_request_agents", build_with_local_urls)

    def ask(self, question_id: str, question: str) -> PipelineOutcome:
        from app.services.databridge_services.langgraph_agent import run_data_bridge_agent

        outcome = PipelineOutcome(question_id=question_id)
        start = time.monotonic()
        try:
            response = run_data_bridge_agent(
                question,
                session_id=f"regression-{question_id}",
                model_name=self.model,
                custom_key=self.api_key,
                user_id=1,
                router_config=self.router_config,
            ) or {}
            ui = response.get("chat_ui") or {}
            final_state = response.get("cot_logs") or {}
            built = final_state.get("response") or {}
            outcome.sql = final_state.get("generated_sql") or None
            outcome.columns = list(final_state.get("columns") or built.get("columns") or [])
            outcome.rows = _rows_from_records(ui.get("table") or [], outcome.columns)
            outcome.message = ui.get("answer") or ""
            outcome.steps = list(ui.get("steps") or [])
            if ui.get("error"):
                outcome.error = built.get("error") or final_state.get("error") or outcome.message or "pipeline returned an error"
        except Exception as e:  # the report records it; one question must not stop the run
            outcome.error = f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=5)}"
        outcome.duration_s = round(time.monotonic() - start, 2)
        return outcome


def _rows_from_records(records: list, columns: list) -> list:
    from regression.reference import json_safe

    rows = []
    for rec in records:
        if isinstance(rec, dict):
            cols = columns or list(rec.keys())
            rows.append([json_safe(rec.get(c)) for c in cols])
        elif isinstance(rec, (list, tuple)):
            rows.append([json_safe(v) for v in rec])
    return rows
