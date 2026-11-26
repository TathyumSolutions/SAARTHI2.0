"""Reference values (API / documents) must reach the data tracks' questions."""
from app.services.staged_execution import needs_staging, run_staged


def _call(name, q):
    return {"name": name, "args": {"question": q}, "id": name}


def test_staging_only_when_both_kinds_present():
    assert needs_staging([_call("call_external_api", "a"), _call("query_database", "b")])
    assert needs_staging([_call("search_documents", "a"), _call("query_spreadsheet_data", "b")])
    assert not needs_staging([_call("query_database", "a"), _call("query_spreadsheet_data", "b")])
    assert not needs_staging([_call("call_external_api", "a"), _call("search_documents", "b")])


def test_data_tracks_get_reference_answers_and_order_is_kept():
    calls = [
        _call("query_database", "avg interest_rate by product, 2022"),
        _call("call_external_api", "India lending rate 2022"),
        _call("query_spreadsheet_data", "commission by product, top slab"),
        _call("search_documents", "IRACP provisioning %"),
    ]
    batches = []

    def run_batch(batch):
        batches.append([c["name"] for c in batch])
        out = []
        for c in batch:
            if c["name"] == "call_external_api":
                out.append((c["name"], {"answer": "India lending rate 2022 = 8.57%"}))
            elif c["name"] == "search_documents":
                out.append((c["name"], {"answer": "Sub-Standard: 25%"}))
            else:
                out.append((c["name"], {"answer": "ok", "question_seen": c["args"]["question"]}))
        return out

    outcomes, context = run_staged(calls, run_batch)
    assert batches == [["call_external_api", "search_documents"], ["query_database", "query_spreadsheet_data"]]
    assert [o[0] for o in outcomes] == [c["name"] for c in calls]
    db_q = outcomes[0][1]["question_seen"]
    assert "8.57%" in db_q and "Sub-Standard: 25%" in db_q and db_q.startswith("avg interest_rate")
    assert "8.57%" in context
    # original calls are not mutated
    assert calls[0]["args"]["question"] == "avg interest_rate by product, 2022"


def test_failed_reference_adds_nothing():
    calls = [_call("call_external_api", "rate"), _call("query_database", "rows")]

    def run_batch(batch):
        return [(c["name"], {"answer": "boom", "error": True} if c["name"] == "call_external_api"
                 else {"answer": "ok", "question_seen": c["args"]["question"]}) for c in batch]

    outcomes, context = run_staged(calls, run_batch)
    assert context == "" and outcomes[1][1]["question_seen"] == "rows"
