"""Command-line entry point for the question-bank regression framework.

    python -m regression.run_regression --snapshot              # save expected results
    python -m regression.run_regression --stages                # checks needing no LLM
    python -m regression.run_regression --pipeline              # ask the real pipeline
    python -m regression.run_regression --pipeline --domain lending --ids S1,M2
    python -m regression.run_regression --check-params

Settings come from the environment (see regression/settings.py):
REGRESSION_DB_URL, REGRESSION_MODEL, REGRESSION_API_KEY, REGRESSION_OLLAMA_URL.
"""
import argparse
import datetime
import sys
from collections import Counter

from regression.bank import available_domains, load_bank
from regression.evaluator import grade
from regression.reference import load_snapshot, run_reference, run_sql, save_snapshot
from regression.report import write_report
from regression.settings import demo_db_target, pipeline_api_key, pipeline_model

# Placeholder -> (table, column) it must exist in.
_PARAM_LOOKUPS = {
    "loan_account_number": ("loans", "loan_account_number"),
    "agent_code": ("agents", "agent_code"),
    "branch_code": ("branches", "branch_code"),
    "supplier_code": ("suppliers", "supplier_code"),
    "f3_supplier_code": ("suppliers", "supplier_code"),
    "plant_code": ("plants", "plant_code"),
}


def _select(bank, ids):
    if not ids:
        return list(bank.questions)
    wanted = {i.strip() for i in ids.split(",") if i.strip()}
    return [q for q in bank.questions if q.id in wanted]


def cmd_snapshot(bank, questions) -> int:
    target = demo_db_target(bank.database)
    failures = 0
    for q in questions:
        if not q.has_reference:
            continue
        try:
            result = run_reference(q, target)
        except Exception as e:
            print(f"  {q.id:8} reference SQL failed: {e}")
            failures += 1
            continue
        meta = {"question": q.question, "database": bank.database, "params": bank.params,
                "data_scale": bank.data_scale,
                "saved": datetime.datetime.now().isoformat(timespec="seconds")}
        path = save_snapshot(bank.domain, q.id, result, meta)
        print(f"  {q.id:8} {result.row_count:5} rows -> {path.relative_to(path.parents[2])}")
    return failures


def cmd_check_params(bank) -> int:
    target = demo_db_target(bank.database)
    missing = 0
    for name, value in bank.params.items():
        if name not in _PARAM_LOOKUPS:
            continue
        table, column = _PARAM_LOOKUPS[name]
        found = run_sql(target, f"SELECT COUNT(*) FROM {table} WHERE {column} = '{value}'").rows[0][0]
        print(f"  {name:22} {value:14} {'ok' if found else 'NOT FOUND in ' + table}")
        missing += 0 if found else 1
    return missing


def cmd_stages(bank, questions) -> list:
    from regression.stage_checks import run_stage_checks
    results = run_stage_checks(bank, demo_db_target(bank.database), questions)
    for r in results:
        if r.status != "SKIP":
            print(f"  {r.question_id:10} {r.check:10} {r.status:5} {r.detail[:110]}")
    return [r.to_json() for r in results]


def cmd_pipeline(bank, questions, model, api_key) -> list:
    from regression.pipeline_runner import PipelineSession

    target = demo_db_target(bank.database)
    out = []
    with PipelineSession(target, model=model, api_key=api_key) as session:
        for q in questions:
            expected = load_snapshot(bank.domain, q.id)
            if expected is None and q.has_reference:
                expected = run_reference(q, target)
            outcome = session.ask(q.id, q.question)
            verdict = grade(q, expected, outcome)
            print(f"  {q.id:8} {verdict.status:7} {outcome.duration_s:6.1f}s  {verdict.detail[:100]}")
            out.append({"id": q.id, "category": q.category, "sources": q.sources, "question": q.question,
                        "verdict": verdict.to_json(), "outcome": outcome.to_json()})
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--domain", default="all", help=f"one of {available_domains()} or 'all'")
    parser.add_argument("--ids", default="", help="comma-separated question ids")
    parser.add_argument("--snapshot", action="store_true", help="run reference SQL and save expected results")
    parser.add_argument("--check-params", action="store_true", help="check placeholder values exist in the data")
    parser.add_argument("--stages", action="store_true", help="run the stage checks that need no LLM")
    parser.add_argument("--pipeline", action="store_true", help="ask the real pipeline and grade its answers")
    parser.add_argument("--db-only", action="store_true", help="with --pipeline: only questions whose sources are just DB")
    parser.add_argument("--model", default=None, help="overrides REGRESSION_MODEL")
    args = parser.parse_args(argv)

    if not any((args.snapshot, args.check_params, args.stages, args.pipeline)):
        parser.error("choose at least one of --snapshot, --check-params, --stages, --pipeline")

    domains = available_domains() if args.domain == "all" else [args.domain]
    model = args.model or pipeline_model()
    run = {"started": datetime.datetime.now().isoformat(timespec="seconds"),
           "model": model if args.pipeline else None, "domains": {}}
    exit_code = 0
    for domain in domains:
        bank = load_bank(domain)
        questions = _select(bank, args.ids)
        print(f"\n== {domain} ({bank.database}, {len(questions)} questions)")
        parts = {}
        if args.check_params:
            exit_code |= 1 if cmd_check_params(bank) else 0
        if args.snapshot:
            exit_code |= 1 if cmd_snapshot(bank, questions) else 0
        if args.stages:
            parts["stage"] = cmd_stages(bank, questions)
            exit_code |= 1 if any(s["status"] == "FAIL" for s in parts["stage"]) else 0
        if args.pipeline:
            asked = [q for q in questions if q.is_db_only] if args.db_only else questions
            parts["pipeline"] = cmd_pipeline(bank, asked, model, pipeline_api_key())
            counts = Counter(r["verdict"]["status"] for r in parts["pipeline"])
            print("  summary:", dict(counts))
            exit_code |= 1 if counts.get("FAIL") or counts.get("ERROR") else 0
        if parts:
            run["domains"][domain] = parts
    if run["domains"]:
        md, js = write_report(run)
        print(f"\nReport: {md}\n        {js}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
