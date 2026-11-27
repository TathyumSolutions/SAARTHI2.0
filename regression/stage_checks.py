"""Checks of the pipeline stages that need no LLM, run per question.

  reference   the reference SQL still runs and still returns its snapshot
              (catches a regenerated or changed demo data set)
  relations   inferred join relations offered to QuerySense; flags sibling
              foreign keys and joins on non-key attributes
  trim        the tables a *local* model is shown (QuerySense
              ._relevant_tables) include every table the reference SQL uses
  join_path   the schema's declared/inferred relations connect the tables
              a question's `join_path` names (e.g. loans -> agents through
              loan_applications)
"""
import re
from dataclasses import dataclass

from regression.bank import Bank, Question
from regression.evaluator import FAIL, PASS, SKIP, _values_match
from regression.reference import load_snapshot, run_reference
from regression.settings import DbTarget


@dataclass
class StageResult:
    question_id: str
    check: str
    status: str
    detail: str = ""

    def to_json(self) -> dict:
        return dict(self.__dict__)


def tables_used(question: Question, schema_tables) -> set:
    sql = (question.reference_sql or "") + " ".join(p["sql"] for p in question.extra_parts)
    return {t for t in re.findall(r"\b(?:FROM|JOIN)\s+([a-z_][a-z0-9_]*)", sql, re.I) if t in schema_tables}


def check_reference(bank: Bank, question: Question, target: DbTarget) -> StageResult:
    if not question.has_reference:
        return StageResult(question.id, "reference", SKIP, "no reference SQL")
    try:
        result = run_reference(question, target)
    except Exception as e:
        return StageResult(question.id, "reference", FAIL, f"reference SQL failed: {e}")
    snapshot = load_snapshot(bank.domain, question.id)
    if snapshot is None:
        return StageResult(question.id, "reference", SKIP, f"{result.row_count} rows; no snapshot saved yet")
    if snapshot.columns != result.columns or snapshot.row_count != result.row_count:
        return StageResult(question.id, "reference", FAIL,
                           f"snapshot {snapshot.row_count} rows {snapshot.columns}, now {result.row_count} rows {result.columns}")
    for i, col in enumerate(result.columns):
        if not _values_match([r[i] for r in snapshot.rows], [r[i] for r in result.rows], ordered=True, rel_tol=1e-9):
            return StageResult(question.id, "reference", FAIL, f"column {col} differs from the snapshot")
    return StageResult(question.id, "reference", PASS, f"{result.row_count} rows match the snapshot")


def check_relations(domain: str, router_config: dict) -> StageResult:
    tables = router_config["routing_menu"]["datasources"]["DB"]["tables"]
    relations = router_config["routing_menu"].get("inferred_relations") or []
    fk_target = {}
    keys = {}
    for t, d in tables.items():
        c = d.get("constraints") or {}
        keys[t] = set(c.get("primary_key") or []) | set(c.get("unique_columns") or [])
        for fk in c.get("foreign_keys") or []:
            fk_target[(t, fk["column"])] = (fk["references_table"], fk["references_column"])
    bad = []
    for r in relations:
        a, b = (r["from_table"], r["from_column"]), (r["to_table"], r["to_column"])
        if a in fk_target and fk_target.get(a) == fk_target.get(b):
            bad.append(f"sibling FKs {a[0]}.{a[1]} ~ {b[0]}.{b[1]}")
        elif keys.get(a[0]) and keys.get(b[0]) and a[1] not in keys[a[0]] and b[1] not in keys[b[0]]:
            bad.append(f"non-key join {a[0]}.{a[1]} ~ {b[0]}.{b[1]}")
    if bad:
        return StageResult(f"{domain}:*", "relations", FAIL, f"{len(bad)} suspect inferred relations: " + "; ".join(bad[:8]))
    return StageResult(f"{domain}:*", "relations", PASS, f"{len(relations)} inferred relations, none suspect")


def check_trim(question: Question, query_sense, schema_tables) -> StageResult:
    if not question.has_reference:
        return StageResult(question.id, "trim", SKIP, "no reference SQL")
    need = tables_used(question, schema_tables)
    chosen = set(query_sense._relevant_tables(question.question))
    missing = sorted(need - chosen)
    if missing:
        return StageResult(question.id, "trim", FAIL, f"local-model schema lacks {missing}; shown {sorted(chosen)}")
    return StageResult(question.id, "trim", PASS, f"shown {sorted(chosen)}")


def check_join_path(question: Question, schema: dict) -> StageResult:
    path = question.notes.get("join_path")
    if not path:
        return StageResult(question.id, "join_path", SKIP, "no join_path")
    tables = [p.split(".", 1)[0] for p in path]
    edges = set()
    for t, meta in schema["tables"].items():
        for fk in meta.get("foreign_keys") or []:
            ref = fk["references"].split(".", 1)[0]
            edges.add(frozenset({t, ref}))
    for r in schema.get("relations") or []:
        edges.add(frozenset({r["from_table"], r["to_table"]}))
    gaps = [f"{a}-{b}" for a, b in zip(tables, tables[1:]) if a != b and frozenset({a, b}) not in edges]
    if gaps:
        return StageResult(question.id, "join_path", FAIL, f"no relation for {gaps}")
    return StageResult(question.id, "join_path", PASS, " -> ".join(tables))


def run_stage_checks(bank: Bank, target: DbTarget, questions: list) -> list:
    from app.services.automated_metamind import to_sql_agent_schema
    from app.services.databridge_services.agents.query_sense_agent import QuerySenseAgent
    from regression.pipeline_runner import build_router_config

    router_config = build_router_config(target)
    menu = router_config["routing_menu"]
    schema = to_sql_agent_schema(menu["datasources"]["DB"]["tables"], relations=menu.get("inferred_relations"))
    query_sense = QuerySenseAgent(schema).query_sense

    results = [check_relations(bank.domain, router_config)]
    for q in questions:
        results.append(check_reference(bank, q, target))
        results.append(check_trim(q, query_sense, schema["tables"]))
        results.append(check_join_path(q, schema))
    return results
