"""General-knowledge answers must not claim connected data is missing."""
from app.services.general_answer_rules import connected_source_labels, not_checked_instruction


def _config(db=True, files=True, sheets=True, api=True):
    return {"routing_menu": {"datasources": {
        "DB": {"tables": {"loans": {}} if db else {}},
        "FILES": {"vector_store_info": {"points_count": 12 if files else 0}},
        "SPREADSHEET": {"tables": {"commission_slabs": {}} if sheets else {}},
        "API": {"registered_tools": [{"name": "worldbank"}] if api else []},
    }}}


def test_labels_reflect_connected_sources():
    assert connected_source_labels(_config()) == [
        "a database", "uploaded documents", "uploaded spreadsheets", "external APIs"]
    assert connected_source_labels(_config(files=False, api=False)) == ["a database", "uploaded spreadsheets"]
    assert connected_source_labels({}) == []


def test_instruction_only_when_sources_exist():
    assert not_checked_instruction([]) == ""
    text = not_checked_instruction(["a database"])
    assert "did not check" in text and "Never say they would need to provide" in text
