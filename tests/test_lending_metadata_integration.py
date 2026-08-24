"""
End-to-end-flavoured tests grounded in the REAL synthetic metadata shipped
in demo_lending/ (an NBFC lending dataset), rather than invented placeholder
names like "orders"/"customers"/"metal_codes" used elsewhere in this test
suite. Every table, column, document code, and API endpoint name below is
copied verbatim from the actual generator scripts:

  - DB schema (13 tables)      -> demo_lending/db_lending.py (SCHEMA_SQL)
  - Excel reference workbooks  -> demo_lending/generate_excel_reference.py
  - Policy document codes      -> demo_lending/generate_guideline_docs.py
                                   (each doc's add_title(doc, title, doc_code)
                                   call, e.g. "KYC-002 v4.0")
  - Validation API endpoints   -> demo_lending/validation_api.py

This lets each "hint is a starting point, not a hard filter" mechanism
added this session be exercised against data shaped like what a real
Saarthi deployment pointed at this demo dataset would actually see, one
section per data-source track plus reuse and MULTI synthesis.

Same verification constraint as the rest of this suite: this sandbox has
no Flask/SQLAlchemy/langchain installed, so router_service.py, api_services.py
and llm_service.py can't be imported directly here. Tests exercise their
real, unmodified source text via regex-extraction + exec() (see
_run_source_block below) rather than a hand-copied reimplementation that
could silently drift from the real code.
"""
import json
import os
import re
import sys
import textwrap
from unittest.mock import patch, MagicMock

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app.services import router_service


def _run_source_block(file_path, start_pattern, end_pattern, ns):
    """Extracts the literal code between two regex anchors from a real
    source file, dedents it, and exec()s it in the given namespace -
    proving the tests run against the actual shipped logic, not a copy of
    it. `ns` is mutated in place with whatever names the block defines."""
    src = open(os.path.join(ROOT_DIR, *file_path.split("/"))).read()
    m = re.search(f"({start_pattern}.*?{end_pattern})", src, re.S | re.M)
    assert m, f"could not locate block in {file_path} (start={start_pattern!r})"
    block = textwrap.dedent(m.group(1))
    exec(block, ns)
    return ns


# ============================================================
# Real metadata, copied from demo_lending/*.py
# ============================================================

# demo_lending/db_lending.py SCHEMA_SQL - a representative subset of the 13
# real tables (full list: branches, employees, agents, loan_products,
# customers, loan_applications, loans, repayment_schedule, collections,
# payables, npa_classification, credit_bureau_records, transactions_ledger).
LENDING_DB_TABLES = ["branches", "customers", "loans", "loan_applications", "repayment_schedule"]

# demo_lending/generate_excel_reference.py - the four real workbook sheet
# titles (ws.title), each with its actual header row.
LENDING_SPREADSHEET_TABLES = {
    "Benchmark Rates": {"columns": ["Rate", "Value", "Notes"]},
    "Branch Master": {"columns": ["Branch Code", "Branch Name", "City", "State", "Region",
                                   "Pincode", "Opened Date", "Active?", "Employee Count", "Agent Count"]},
    "Commission Slabs": {"columns": ["Product Code", "Product Name", "Slab: < Rs 10L/qtr",
                                      "Slab: Rs 10L-50L/qtr", "Slab: Rs 50L-2Cr/qtr", "Slab: > Rs 2Cr/qtr"]},
    "Insurance Rates": {"columns": ["Insurance Partner", "Cover Type", "Applicable Loan Categories",
                                     "Premium Rate (per Rs 1,000 SA p.a.)", "Min Age", "Max Age",
                                     "Claim Settlement Ratio %"]},
}

# demo_lending/generate_guideline_docs.py - real doc_code values passed to
# add_title(doc, title, doc_code) for each of the 5 policy documents.
LENDING_DOCUMENT_CODES = {
    "FPC-001": "Fair Practices Code for Lending Operations",
    "KYC-002": "Know Your Customer (KYC) and Anti-Money Laundering (AML) Policy",
    "IRACP-003": "Income Recognition, Asset Classification and Provisioning (IRACP) Norms",
    "DLG-005": "Digital Lending Operating Guidelines",
    "GRP-004": "Customer Grievance Redressal Policy",
}

# demo_lending/validation_api.py - real Flask route handler function names
# (the identifiers a registered API connector's tool schema would carry).
LENDING_API_TOOLS = ["validate_pan", "validate_gstin", "validate_aadhaar", "bureau_score", "bureau_report"]


# ============================================================
# Section 1: DB track - QuerySenseAgent hint/feedback/instructions
# against the real lending schema
# ============================================================
def _lending_schema():
    return {
        "tables": {
            "loans": {
                "description": "Sanctioned/disbursed loan accounts, EMI, status, current DPD, NPA flag",
                "columns": {"loan_id": {}, "customer_id": {}, "branch_id": {}, "sanctioned_amount": {},
                             "disbursed_amount": {}, "loan_status": {}, "current_dpd": {}, "npa_flag": {}},
            },
            "customers": {
                "description": "Borrower KYC: name, PAN, masked Aadhaar, income, CIBIL score, address",
                "columns": {"customer_id": {}, "pan_number": {}, "cibil_score": {}, "kyc_status": {}},
            },
            "repayment_schedule": {
                "description": "Per-installment amortization schedule",
                "columns": {"schedule_id": {}, "loan_id": {}, "emi_due": {}, "amount_paid": {}, "payment_status": {}},
            },
            "branches": {
                "description": "Branch network (city/state/region)",
                "columns": {"branch_id": {}, "branch_code": {}, "branch_name": {}, "region": {}},
            },
        }
    }


def _query_sense():
    from app.services.databridge_services.agents.query_sense_agent import QuerySenseAgent
    return QuerySenseAgent.QuerySense(_lending_schema(), ollama_model="llama3", ollama_url="http://ollama:11434/api/generate")


def _mock_ollama_response(json_text):
    resp = MagicMock()
    resp.raise_for_status = lambda: None
    resp.json.return_value = {"response": json_text}
    return resp


_LOANS_PLAN_JSON = (
    '{"tables": ["loans", "branches"], "columns": [], "intent": "SELECTION", "aggregations": [], '
    '"group_by": [], "joins": [], "filters": [], "order_by": [], "limit": 0}'
)


def test_router_hint_naming_real_lending_tables_is_injected():
    """The router's query_database tool call hints tables straight from the
    live schema (loans, branches, ...) - QuerySenseAgent's prompt must carry
    that hint as a starting point."""
    qs = _query_sense()
    with patch("requests.post", return_value=_mock_ollama_response(_LOANS_PLAN_JSON)) as mocked_post:
        qs._call_llm_for_plan(
            "how many active loans and total sanctioned amount by branch?",
            "llama3", hint_tables=["loans", "branches"],
        )
    sent_prompt = mocked_post.call_args.kwargs["json"]["prompt"]
    assert "ROUTER-IDENTIFIED TABLE(S)" in sent_prompt
    assert "loans, branches" in sent_prompt


def test_router_hint_naming_a_table_outside_this_schema_is_dropped():
    """'loan_master' is a plausible-sounding but nonexistent table name (the
    real table is 'loans') - a hallucinated/stale hint like this must never
    be echoed into the prompt as if it were real."""
    qs = _query_sense()
    with patch("requests.post", return_value=_mock_ollama_response(_LOANS_PLAN_JSON)) as mocked_post:
        qs._call_llm_for_plan("how many loans are active?", "llama3", hint_tables=["loan_master"])
    sent_prompt = mocked_post.call_args.kwargs["json"]["prompt"]
    assert "ROUTER-IDENTIFIED TABLE(S)" not in sent_prompt
    assert "loan_master" not in sent_prompt


def test_disliked_feedback_about_wrong_lending_table_reaches_the_prompt():
    """A realistic DISLIKED remark (picked repayment_schedule's per-
    installment emi_due when the question was actually about the loan's
    overall outstanding, a common lending-domain confusion) must reach the
    table/column selection step, not just SQL generation."""
    feedback = (
        'COMPANY FEEDBACK CONTEXT:\n'
        '- A similar question was DISLIKED before, with this remark: '
        '"used repayment_schedule.emi_due instead of loans.sanctioned_amount for outstanding '
        'principal - wrong table" - avoid this problem.'
    )
    qs = _query_sense()
    with patch("requests.post", return_value=_mock_ollama_response(_LOANS_PLAN_JSON)) as mocked_post:
        qs._call_llm_for_plan(
            "what is the outstanding principal on active loans?", "llama3", feedback_context=feedback,
        )
    sent_prompt = mocked_post.call_args.kwargs["json"]["prompt"]
    assert feedback in sent_prompt
    assert "DISLIKED note is still relevant" in sent_prompt


def test_system_instructions_about_lending_terminology_reach_the_prompt():
    qs = _query_sense()
    with patch("requests.post", return_value=_mock_ollama_response(_LOANS_PLAN_JSON)) as mocked_post:
        qs._call_llm_for_plan(
            "how many loans are overdue?", "llama3",
            system_instructions="Always refer to 'current_dpd' as 'days past due', never as a raw column name.",
        )
    sent_prompt = mocked_post.call_args.kwargs["json"]["prompt"]
    assert "Always refer to 'current_dpd' as 'days past due'" in sent_prompt
    assert "USER CUSTOM FORMATTING INSTRUCTIONS" in sent_prompt


# ============================================================
# Section 2: Spreadsheet track - hint narrowing with the real
# Excel workbook sheet names/columns
# ============================================================
def test_spreadsheet_hint_narrows_to_real_workbook_sheets_only():
    """answer_from_spreadsheets' hinted_tables line (spreadsheet_query_
    service.py) must keep only hint entries that are real, currently-
    uploaded sheet names - 'Commission Slabs' and 'Insurance Rates' are
    real; 'Interest Rates' is a plausible near-miss of the real 'Insurance
    Rates' name and must be dropped rather than crashing or being invented
    into existence."""
    ns = _run_source_block(
        "app/services/spreadsheet_query_service.py",
        r"^        hinted_tables = \{name: info",
        r"available_tables\.items\(\) if name in \(hint_tables or \[\]\)\}\n",
        {"available_tables": LENDING_SPREADSHEET_TABLES,
         "hint_tables": ["Commission Slabs", "Insurance Rates", "Interest Rates"]},
    )
    assert set(ns["hinted_tables"].keys()) == {"Commission Slabs", "Insurance Rates"}
    assert ns["hinted_tables"]["Commission Slabs"]["columns"] == LENDING_SPREADSHEET_TABLES["Commission Slabs"]["columns"]


def test_spreadsheet_hint_with_no_real_match_falls_back_to_full_set_at_prompt_time():
    """If every hinted name is bogus, hinted_tables comes back empty - the
    caller's `hinted_tables or available_tables` must fall back to the full
    real table set rather than building a plan prompt with nothing to
    choose from."""
    ns = _run_source_block(
        "app/services/spreadsheet_query_service.py",
        r"^        hinted_tables = \{name: info",
        r"available_tables\.items\(\) if name in \(hint_tables or \[\]\)\}\n",
        {"available_tables": LENDING_SPREADSHEET_TABLES, "hint_tables": ["Interest Rates"]},
    )
    assert ns["hinted_tables"] == {}
    effective_tables = ns["hinted_tables"] or LENDING_SPREADSHEET_TABLES
    assert set(effective_tables.keys()) == set(LENDING_SPREADSHEET_TABLES.keys())


# ============================================================
# Section 3: Files track - hint_document_codes filtering with the
# real policy document codes (FPC-001, KYC-002, IRACP-003, DLG-005, GRP-004)
# ============================================================
def test_files_hint_narrows_to_the_real_hinted_document():
    """A question about grievance escalation should hint GRP-004 (the real
    Customer Grievance Redressal Policy code) - llm_service.py's hint
    filter must narrow retrieval to just that document when it's both
    hinted and visible."""
    ns = _run_source_block(
        "app/services/llm_service.py",
        r"^            if hint_document_codes:",
        r"doc_codes = hinted_and_visible\n",
        {"hint_document_codes": ["GRP-004"], "doc_codes": list(LENDING_DOCUMENT_CODES.keys())},
    )
    assert ns["doc_codes"] == ["GRP-004"]


def test_files_hint_naming_a_stale_document_code_falls_back_to_full_visible_set():
    """'KYC-999' is a plausible-looking but nonexistent code (the real KYC
    policy is KYC-002) - a stale/hallucinated hint must never narrow
    retrieval to nothing; it must fall back to this user's full visible
    document set, exactly as if no hint had been given."""
    all_codes = list(LENDING_DOCUMENT_CODES.keys())
    ns = _run_source_block(
        "app/services/llm_service.py",
        r"^            if hint_document_codes:",
        r"doc_codes = hinted_and_visible\n",
        {"hint_document_codes": ["KYC-999"], "doc_codes": list(all_codes)},
    )
    assert ns["doc_codes"] == all_codes


# ============================================================
# Section 4: API track - hint_tool_name forcing with the real
# validation_api.py endpoint handler names
# ============================================================
def _lending_llm_tools_list():
    return [{"type": "function", "function": {"name": name}} for name in LENDING_API_TOOLS]


def test_api_hint_forces_the_real_registered_bureau_score_tool():
    ns = _run_source_block(
        "app/services/api_services.py",
        r"^    forced_tool_name = None",
        r"forced_tool_name = hint_tool_name\n",
        {"hint_tool_name": "bureau_score", "llm_tools_list": _lending_llm_tools_list()},
    )
    assert ns["forced_tool_name"] == "bureau_score"


def test_api_hint_naming_an_unregistered_tool_is_not_forced():
    """'credit_score_lookup' is a plausible name for what this API actually
    does, but the real registered handler is 'bureau_score' - an
    unregistered/invented hint must fall back to free tool choice (None),
    never a lookup error."""
    ns = _run_source_block(
        "app/services/api_services.py",
        r"^    forced_tool_name = None",
        r"forced_tool_name = hint_tool_name\n",
        {"hint_tool_name": "credit_score_lookup", "llm_tools_list": _lending_llm_tools_list()},
    )
    assert ns["forced_tool_name"] is None


def test_api_hint_reinforcement_line_names_the_real_forced_tool():
    """When a real tool is forced, the system prompt reinforcement (added
    for providers without reliable tool_choice, e.g. the Ollama route) must
    name that exact tool."""
    ns = _run_source_block(
        "app/services/api_services.py",
        r"^    if forced_tool_name:\n        system_prompt \+=",
        r"\"Call exactly this tool for this request\.\"\n        \)\n",
        {"forced_tool_name": "validate_pan", "system_prompt": "BASE PROMPT"},
    )
    assert "TOOL SELECTED BY THE ROUTER" in ns["system_prompt"]
    assert "'validate_pan'" in ns["system_prompt"]


# ============================================================
# Section 5: Self-learning reuse - real lending SQL / spreadsheet plan
# ============================================================
class _FakeMatched:
    def __init__(self, query_code, main_query, answer, sources, question, remarks=None):
        self.query_code = query_code
        self.main_query = main_query
        self.answer = answer
        self.sources = sources
        self.question = question
        self.remarks = remarks


_REAL_LENDING_SQL = (
    "SELECT b.branch_code, b.branch_name, count(l.loan_id) AS active_loans, "
    "sum(l.sanctioned_amount) AS total_sanctioned FROM loans l "
    "JOIN branches b ON b.branch_id = l.branch_id "
    "WHERE l.loan_status = 'Active' GROUP BY b.branch_code, b.branch_name"
)


def test_reused_db_query_replays_real_lending_sql_with_no_regeneration():
    """A previously-liked query over the real loans/branches schema must be
    re-executed via query_formatter.execute_query with its exact stored SQL
    - never regenerated by QuerySenseAgent/SQLGeneratorAgent again."""
    matched = _FakeMatched(
        query_code="QUERY00042", main_query=_REAL_LENDING_SQL,
        answer="3 branches have active loans, MUM01 leads with 412 active loans.",
        sources=["loans<Database>", "branches<Database>"],
        question="how many active loans and total sanctioned amount by branch?",
    )
    fake_result = {
        "status": "success", "message": matched.answer,
        "data": [{"branch_code": "MUM01", "branch_name": "Mumbai Fort", "active_loans": 412, "total_sanctioned": 58200000.0}],
        "chart_configs": {}, "insights": [],
    }

    with patch("app.services.databridge_services.langgraph_agent.query_formatter") as mocked_qf, \
         patch("app.services.databridge_services.langgraph_agent._build_db_config_for_user", return_value={}):
        mocked_qf.execute_query.return_value = fake_result
        result = router_service._run_reused_db_query(
            "how many active loans by branch?", matched, 0.96, {"session_id": "s1", "model_name": "gpt-4o-mini"},
        )

    mocked_qf.execute_query.assert_called_once()
    called_args, called_kwargs = mocked_qf.execute_query.call_args
    assert called_args[0] == _REAL_LENDING_SQL
    assert result["error"] is False
    assert result["sql"] == _REAL_LENDING_SQL
    assert result["table"] == fake_result["data"]
    assert result["execution_type"] == "reused"


def test_reused_spreadsheet_query_replays_real_commission_slab_plan():
    """A liked query against the real 'Commission Slabs' workbook must
    replay its stored plan via _execute_plan directly - no LLM plan-
    building call."""
    stored_plan = {"tables": ["Commission Slabs"], "filters": [{"column": "Product Code", "op": "==", "value": "GL"}]}
    matched = _FakeMatched(
        query_code="QUERY00099", main_query=json.dumps(stored_plan),
        answer="The Gold Loan commission slab ranges from 0.65% to 1.20% depending on disbursement volume.",
        sources=["Commission Slabs<Spreadsheet>"],
        question="what is the commission slab for gold loans?",
    )
    fake_df = MagicMock()
    fake_df.to_json.return_value = json.dumps([{
        "Product Code": "GL", "Product Name": "Gold Loan",
        "Slab: < Rs 10L/qtr": "0.65%", "Slab: > Rs 2Cr/qtr": "1.20%",
    }])

    with patch("app.services.spreadsheet_query_service._execute_plan", return_value=fake_df) as mocked_exec:
        result = router_service._run_reused_spreadsheet_query(
            "what is the commission slab for gold loans", matched, 0.95, {"session_id": "s1"},
        )

    mocked_exec.assert_called_once_with(stored_plan)
    assert result["error"] is False
    assert result["table"][0]["Product Code"] == "GL"
    assert result["matched_query_code"] == "QUERY00099"


def test_find_reusable_query_matches_a_liked_real_lending_question():
    candidate = MagicMock()
    candidate.question = "how many active loans and total sanctioned amount by branch?"
    candidate.router_decision = "DB"

    mock_query_chain = MagicMock()
    mock_query_chain.filter.return_value = mock_query_chain
    mock_query_chain.order_by.return_value = mock_query_chain
    mock_query_chain.limit.return_value = mock_query_chain
    mock_query_chain.all.return_value = [candidate]

    fake_embedder = MagicMock()
    fake_embedder.embed_query.return_value = [1.0, 0.0]

    with patch.object(router_service.QueryLog, "query", mock_query_chain), \
         patch.object(router_service, "_get_feedback_embedder", return_value=fake_embedder), \
         patch.object(router_service, "_cosine_similarity", return_value=0.97):
        matched, score, track = router_service._find_reusable_query(
            "acme_nbfc", None, "how many active loans by branch, with total sanctioned amount?",
        )

    assert matched is candidate
    assert track == "DB"
    assert score == 0.97


# ============================================================
# Section 6: MULTI-track synthesis - merging a DB result (loan
# portfolio by branch) with a Spreadsheet result (Branch Master
# staffing) and charting it
# ============================================================
def test_multi_chart_generated_for_merged_branch_portfolio_and_staffing_table():
    """A realistic MULTI question ("compare active loan volume against
    branch staffing") merges a DB aggregate (branch_code/active_loans/
    total_sanctioned) with the real Branch Master spreadsheet's staffing
    columns (employee_count/agent_count) - _generate_chart_for_merged_table
    must run the same deterministic DataVisualizerAgent on that merged,
    domain-real table shape."""
    merged_table = [
        {"branch_code": "MUM01", "active_loans": 412, "total_sanctioned": 58200000.0, "employee_count": 18, "agent_count": 7},
        {"branch_code": "DEL02", "active_loans": 289, "total_sanctioned": 39750000.0, "employee_count": 12, "agent_count": 5},
    ]
    fake_chart_configs = {"recommended": "bar", "bar": {"type": "bar"}, "chart_worthy": True}

    mock_agent_instance = MagicMock()
    mock_agent_instance.execute.return_value = {"chart_configs": fake_chart_configs}
    mock_agent_cls = MagicMock(return_value=mock_agent_instance)

    with patch("app.services.databridge_services.agents.DataVisualizerAgent", mock_agent_cls):
        result = router_service._generate_chart_for_merged_table(
            merged_table, "compare active loan volume against branch staffing",
        )

    mock_agent_instance.execute.assert_called_once_with({
        "data": merged_table,
        "columns": ["branch_code", "active_loans", "total_sanctioned", "employee_count", "agent_count"],
        "user_query": "compare active loan volume against branch staffing",
    })
    assert result == fake_chart_configs


def test_multi_merge_joins_db_branch_aggregate_with_spreadsheet_staffing_on_branch_code():
    """_merge_tabular_results (pre-existing, source-agnostic Python) must
    join the DB track's per-branch loan aggregate with the Spreadsheet
    track's per-branch staffing lookup on their shared branch_code column,
    rather than keeping only one track's table and dropping the other's
    columns."""
    db_result = {
        "table": [
            {"branch_code": "MUM01", "active_loans": 412, "total_sanctioned": 58200000.0},
            {"branch_code": "DEL02", "active_loans": 289, "total_sanctioned": 39750000.0},
        ]
    }
    spreadsheet_result = {
        "table": [
            {"branch_code": "MUM01", "employee_count": 18, "agent_count": 7},
            {"branch_code": "DEL02", "employee_count": 12, "agent_count": 5},
        ]
    }
    ok_results = [("query_database", db_result), ("query_spreadsheet_data", spreadsheet_result)]

    name, merged = router_service._merge_tabular_results(ok_results)

    assert name == "query_database"
    assert merged["table"] == [
        {"branch_code": "MUM01", "active_loans": 412, "total_sanctioned": 58200000.0, "employee_count": 18, "agent_count": 7},
        {"branch_code": "DEL02", "active_loans": 289, "total_sanctioned": 39750000.0, "employee_count": 12, "agent_count": 5},
    ]
