"""Writes a run's results as Markdown (for people) and JSON (for diffs)."""
import datetime
import json
from collections import Counter
from pathlib import Path

REPORT_DIR = Path(__file__).resolve().parent / "reports"


def _cell(text, limit=160) -> str:
    text = " ".join(str(text or "").split()).replace("|", "\\|")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def write_report(run: dict, report_dir: Path = REPORT_DIR) -> tuple:
    """run = {"started", "model", "domains": {domain: {"stage": [...], "pipeline": [...]}}}"""
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = report_dir / f"regression-{stamp}.json"
    md_path = report_dir / f"regression-{stamp}.md"
    json_path.write_text(json.dumps(run, indent=1, default=str), encoding="utf-8")

    lines = [f"# Saarthi question-bank regression - {run['started']}", ""]
    if run.get("model"):
        lines += [f"Model: `{run['model']}`", ""]
    for domain, parts in run["domains"].items():
        lines += [f"## {domain}", ""]
        if parts.get("pipeline"):
            counts = Counter(r["verdict"]["status"] for r in parts["pipeline"])
            lines += ["### Pipeline answers", "",
                      "Summary: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())), "",
                      "| ID | Category | Status | Detail | Rows (exp/got) | Time s |",
                      "|---|---|---|---|---|---|"]
            for r in parts["pipeline"]:
                v = r["verdict"]
                lines.append(f"| {r['id']} | {r['category']} | {v['status']} | {_cell(v['detail'])} | "
                             f"{v.get('expected_rows')}/{v.get('actual_rows')} | {r['outcome'].get('duration_s')} |")
            lines.append("")
            failures = [r for r in parts["pipeline"] if r["verdict"]["status"] not in ("PASS", "SKIP")]
            if failures:
                lines += ["#### Generated SQL for non-passing questions", ""]
                for r in failures:
                    lines += [f"**{r['id']}** - {_cell(r['question'], 300)}", "", "```sql",
                              (r["outcome"].get("sql") or "-- none").strip(), "```", ""]
        if parts.get("stage"):
            counts = Counter(s["status"] for s in parts["stage"])
            lines += ["### Stage checks (no LLM)", "",
                      "Summary: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())), "",
                      "| ID | Check | Status | Detail |", "|---|---|---|---|"]
            for s in parts["stage"]:
                if s["status"] == "SKIP":
                    continue
                lines.append(f"| {s['question_id']} | {s['check']} | {s['status']} | {_cell(s['detail'])} |")
            lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path, json_path
