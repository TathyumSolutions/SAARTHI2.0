"""
Two-stage execution for questions that combine reference values with data.

Some sources return a fixed value to *apply* (a benchmark rate from an
external API, a provisioning % from a policy document), while database and
spreadsheet tracks return rows to apply it to. Run all at once, the rows
never see the value: a 2022 benchmark of 8.57% cannot be subtracted inside
SQL that was written without it, and the Result Combiner cannot join a
one-row API answer to a per-product table because they share no values.

So when the router picks both kinds, the reference tracks run first and
their answers are added to each data track's sub-question; the data tracks
then run (in parallel with each other) knowing those values. A question
with only one kind runs exactly as before.
"""
from __future__ import annotations

import copy
from typing import Callable, List, Optional, Sequence, Tuple

REFERENCE_TOOLS = frozenset({"call_external_api", "search_documents"})
DATA_TOOLS = frozenset({"query_database", "query_spreadsheet_data"})

MAX_CONTEXT_CHARS_PER_SOURCE = 1500

_FRIENDLY = {
    "call_external_api": "External API",
    "search_documents": "Uploaded documents",
}

Outcome = Optional[Tuple[str, dict]]


def needs_staging(tool_calls: Sequence[dict]) -> bool:
    names = {c.get("name") for c in tool_calls}
    return bool(names & REFERENCE_TOOLS) and bool(names & DATA_TOOLS)


def split_stages(tool_calls: Sequence[dict]) -> Tuple[List[int], List[int]]:
    """Indexes of the calls to run first (reference) and second (the rest)."""
    first = [i for i, c in enumerate(tool_calls) if c.get("name") in REFERENCE_TOOLS]
    second = [i for i, c in enumerate(tool_calls) if c.get("name") not in REFERENCE_TOOLS]
    return first, second


def reference_context(outcomes: Sequence[Outcome]) -> str:
    """Plain-text summary of the reference tracks' answers, skipping errors."""
    parts = []
    for outcome in outcomes:
        if not outcome:
            continue
        name, result = outcome
        answer = (result or {}).get("answer")
        if (result or {}).get("error") or not isinstance(answer, str) or not answer.strip():
            continue
        text = answer.strip()
        if len(text) > MAX_CONTEXT_CHARS_PER_SOURCE:
            text = text[:MAX_CONTEXT_CHARS_PER_SOURCE].rstrip() + " ..."
        parts.append(f"[{_FRIENDLY.get(name, name)}]: {text}")
    return "\n".join(parts)


def with_reference_context(call: dict, context: str, original_question: str = "") -> dict:
    """Copy of ``call`` whose ``question`` carries the reference values."""
    if not context:
        return call
    new_call = copy.deepcopy(call)
    args = new_call.setdefault("args", {})
    question = (args.get("question") or original_question or "").strip()
    args["question"] = (
        f"{question}\n\nValues already obtained from other sources (use them directly "
        f"in the calculation where relevant; do not look for them in this source):\n{context}"
    )
    return new_call


def run_staged(
    tool_calls: Sequence[dict],
    run_batch: Callable[[List[dict]], List[Outcome]],
    original_question: str = "",
) -> Tuple[List[Outcome], str]:
    """Run reference calls, then the data calls with their values.

    ``run_batch`` executes a list of calls (in parallel when it can) and
    returns their outcomes in order. Returns the outcomes in the original
    call order plus the context text handed to the data tracks.
    """
    first_idx, second_idx = split_stages(tool_calls)
    outcomes: List[Outcome] = [None] * len(tool_calls)

    first = run_batch([tool_calls[i] for i in first_idx]) if first_idx else []
    for i, out in zip(first_idx, first):
        outcomes[i] = out

    context = reference_context(first)
    second_calls = [with_reference_context(tool_calls[i], context, original_question) for i in second_idx]
    second = run_batch(second_calls) if second_calls else []
    for i, out in zip(second_idx, second):
        outcomes[i] = out
    return outcomes, context
