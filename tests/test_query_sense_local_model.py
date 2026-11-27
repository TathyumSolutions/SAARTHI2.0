"""
Tests for running the data-bridge pipeline on a small local Ollama model
(e.g. ollama://llama2:7b).

The failure these cover: for "Count of machines grouped by their current
status", Llama 2 7B received the full-schema QuerySense prompt with no
num_ctx, so Ollama dropped the start of the prompt (the output rules). The
model replied with invented data rows ({"machines": [{"machine_id": 1, ...}]}),
QuerySense took that as a plan with no tables, validation failed, and
error_diagnosis retried the identical prompt twice before giving up.
"""
import json
import os
import sys
from unittest.mock import MagicMock, patch

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app.services.databridge_services import ollama_client
from app.services.databridge_services.agents.error_diagnosis_agent import ErrorDiagnosisAgent
from app.services.databridge_services.agents.query_sense_agent import (
    PLAN_JSON_SCHEMA,
    QuerySenseAgent,
)
from app.services.databridge_services.agents.query_simplifier_agent import QuerySimplifierAgent
from app.services.databridge_services.agents.query_validator_agent import QueryValidatorAgent

LLAMA2 = "ollama://llama2:7b"
URL = "http://ollama:11434/api/generate"

# What Llama 2 7B actually returned in the failing run.
HALLUCINATED_ROWS = json.dumps({
    "machines": [
        {"machine_id": 1, "status": "Available"},
        {"machine_id": 2, "status": "Under Maintenance"},
    ]
})


def _manufacturing_schema():
    def table(*cols):
        return {"description": "", "columns": {c: {} for c in cols}}

    return {
        "tables": {
            "plants": table("plant_id", "plant_name", "city", "is_active"),
            "machines": table("machine_id", "plant_id", "machine_name", "status"),
            "machine_downtime": table("downtime_id", "machine_id", "reason", "minutes"),
            "production_orders": table("production_order_id", "product_id", "plant_id", "status"),
            "products": table("product_id", "product_name", "category"),
            "customers": table("customer_id", "company_name", "city"),
            "suppliers": table("supplier_id", "company_name", "plant_id", "is_active"),
            "shipments": table("shipment_id", "customer_id", "plant_id", "status"),
            "payables": table("payable_id", "supplier_id", "plant_id", "amount"),
            "employees": table("employee_id", "plant_id", "email", "is_active"),
        },
        "relations": [
            {"from_table": "machines", "from_column": "plant_id",
             "to_table": "plants", "to_column": "plant_id", "confidence": "name+value"},
            {"from_table": "customers", "from_column": "city",
             "to_table": "plants", "to_column": "city", "confidence": "name_only"},
        ],
    }


def _query_sense():
    return QuerySenseAgent.QuerySense(_manufacturing_schema(), ollama_model=LLAMA2, ollama_url=URL)


def _ollama_response(text):
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = lambda: None
    resp.json.return_value = {"response": text, "prompt_eval_count": 10, "eval_count": 5}
    return resp


def _sent_payload(mocked_post, call_index=0):
    return mocked_post.call_args_list[call_index].kwargs["json"]


# ---------------------------------------------------------------- request

def test_local_query_sense_request_sets_context_window_and_plan_schema():
    qs = _query_sense()
    with patch("requests.post", return_value=_ollama_response("{}")) as mocked_post:
        qs._call_llm_for_plan("Count of machines grouped by their current status", LLAMA2)

    payload = _sent_payload(mocked_post)
    assert payload["options"]["num_ctx"] == ollama_client.OLLAMA_NUM_CTX
    assert payload["format"] == PLAN_JSON_SCHEMA
    assert mocked_post.call_args.kwargs["timeout"] == ollama_client.OLLAMA_REQUEST_TIMEOUT


def test_schema_format_rejected_by_old_ollama_falls_back_to_json():
    qs = _query_sense()
    rejected = MagicMock(status_code=400)
    with patch("requests.post", side_effect=[rejected, _ollama_response("{}")]) as mocked_post:
        qs._call_llm_for_plan("machines by status", LLAMA2)

    assert mocked_post.call_count == 2
    assert _sent_payload(mocked_post, 1)["format"] == "json"


# ---------------------------------------------------------- schema trim

def test_local_model_prompt_only_carries_relevant_tables():
    qs = _query_sense()
    with patch("requests.post", return_value=_ollama_response("{}")) as mocked_post:
        qs._call_llm_for_plan("Count of machines grouped by their current status", LLAMA2)

    prompt = _sent_payload(mocked_post)["prompt"]
    assert "Table 'machines'" in prompt
    # Joined to machines by a relation, so it fills a free slot.
    assert "Table 'plants'" in prompt
    tables_in_prompt = prompt.count("Table '")
    assert tables_in_prompt <= ollama_client.OLLAMA_SCHEMA_MAX_TABLES
    assert "Table 'payables'" not in prompt
    # The output rules are repeated after the schema.
    assert prompt.rstrip().endswith("Do NOT return data rows or invent values.")


def test_hinted_table_is_always_kept_for_local_model():
    qs = _query_sense()
    with patch("requests.post", return_value=_ollama_response("{}")) as mocked_post:
        qs._call_llm_for_plan("how much do we owe", LLAMA2, hint_tables=["payables"])

    assert "Table 'payables'" in _sent_payload(mocked_post)["prompt"]


def test_hosted_model_still_gets_full_schema():
    qs = _query_sense()
    qs.openai_key = "test-key"  # ChatOpenAI is built, but never called
    fake_llm_response = MagicMock(content="{}")
    with patch("app.services.databridge_services.agents.query_sense_agent.tracked_invoke",
               return_value=fake_llm_response) as mocked_invoke:
        qs._call_llm_for_plan("machines by status", "gpt-4o-mini")

    prompt = mocked_invoke.call_args.args[1]
    assert prompt.count("Table '") == len(_manufacturing_schema()["tables"])


# ------------------------------------------------- bad output / fallback

def test_hallucinated_rows_fall_back_to_keyword_plan():
    qs = _query_sense()
    with patch("requests.post", return_value=_ollama_response(HALLUCINATED_ROWS)):
        out = qs.analyze("Count of machines grouped by their current status", LLAMA2)

    assert out["tables"] == ["machines"]
    assert "status" in out["columns"]
    assert out["query_type"] == "GROUPED_ANALYSIS"
    assert any(a.get("function") == "count" for a in out["aggregations"])


def test_valid_local_plan_is_used_as_is():
    plan = {
        "tables": ["machines"], "columns": ["machines.status"], "intent": "GROUPED_ANALYSIS",
        "aggregations": [{"function": "count", "column": "*"}], "group_by": ["machines.status"],
        "joins": [], "filters": [], "order_by": [], "limit": 0, "assumption_note": "",
    }
    qs = _query_sense()
    with patch("requests.post", return_value=_ollama_response(json.dumps(plan))):
        out = qs.analyze("Count of machines grouped by their current status", LLAMA2)

    assert out["tables"] == ["machines"]
    assert out["raw_plan"]["group_by"] == ["machines.status"]


# --------------------------------------------------------------- retries

def test_retry_feedback_reaches_the_prompt():
    agent = QuerySenseAgent(_manufacturing_schema(), ollama_model=LLAMA2, ollama_url=URL)
    state = {
        "simplified_query": "machines by status",
        "model_name": LLAMA2,
        "error_diagnosis": {"retry_from_step": "query_sense"},
        "error_feedback": "Schema validation failed: ⚠️ Data Insufficient",
    }
    with patch("requests.post", return_value=_ollama_response("{}")) as mocked_post:
        agent.execute(state)

    assert "PREVIOUS ATTEMPT FAILED: Schema validation failed" in _sent_payload(mocked_post)["prompt"]


def test_schema_validation_failure_message_reaches_error_diagnosis():
    validator = QueryValidatorAgent(_manufacturing_schema())
    state = {"query_sense_output": {"tables": [], "columns": []}, "current_step": "query_sense"}
    state = validator.execute(state)

    assert "No matching tables or columns" in state["error"]

    state = ErrorDiagnosisAgent().execute(state)
    # Unrecoverable: go straight to the handler instead of two identical retries.
    assert state["error_diagnosis"]["retry_from_step"] == "error_handler"


# ------------------------------------------------------------ simplifier

def test_simplifier_uses_shared_timeout_and_context_window():
    simplifier = QuerySimplifierAgent(schema=_manufacturing_schema(), url=URL)
    with patch("requests.post", return_value=_ollama_response("machines by status")) as mocked_post:
        result = simplifier.simplify("how many machines are there per status?", LLAMA2)

    assert result == "machines by status"
    assert mocked_post.call_args.kwargs["timeout"] == ollama_client.OLLAMA_REQUEST_TIMEOUT
    assert _sent_payload(mocked_post)["options"]["num_ctx"] == ollama_client.OLLAMA_NUM_CTX
