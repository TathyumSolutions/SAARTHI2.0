"""
Merge router tool calls that target the same single data source.

The router LLM sometimes splits one database question into several
query_database calls (e.g. "on-time % per supplier" and "home plant per
supplier"), even though one SQL query can join those tables. Each extra call
runs a whole separate data-bridge pipeline: the halves can't be joined
reliably afterwards, and on a local Ollama with OLLAMA_NUM_PARALLEL=1 the
parallel runs queue behind each other until they time out.

Only calls to the SAME tool are merged, so genuine cross-source questions
(database + spreadsheet, database + API, ...) keep one call per source.
"""
from typing import Iterable

# Tools whose calls all hit one backing source that can answer a combined
# question in a single run. The DB track's SQL agent joins across tables via
# foreign keys, so every query_database call goes to the same database.
DEFAULT_MERGEABLE_TOOLS = ("query_database",)


def _ordered_union(lists: Iterable[list]) -> list:
    seen, out = set(), []
    for items in lists:
        for item in items or []:
            if item not in seen:
                seen.add(item)
                out.append(item)
    return out


def merge_same_source_calls(
    tool_calls: list,
    user_query: str,
    mergeable_tools: Iterable[str] = DEFAULT_MERGEABLE_TOOLS,
) -> tuple[list, list]:
    """Collapse multiple calls to a mergeable tool into one call.

    The merged call keeps the position of the first call, asks the full
    original question and carries the union of the `tables` hints.

    Returns (new_tool_calls, merged_tool_names).
    """
    mergeable = set(mergeable_tools)
    groups: dict = {}
    for call in tool_calls:
        if call.get("name") in mergeable:
            groups.setdefault(call["name"], []).append(call)

    to_merge = {name for name, calls in groups.items() if len(calls) > 1}
    if not to_merge:
        return list(tool_calls), []

    result, emitted = [], set()
    for call in tool_calls:
        name = call.get("name")
        if name not in to_merge:
            result.append(call)
            continue
        if name in emitted:
            continue
        emitted.add(name)
        group = groups[name]
        merged = dict(group[0])
        merged["args"] = {
            **(group[0].get("args") or {}),
            "question": user_query,
            "tables": _ordered_union((c.get("args") or {}).get("tables") for c in group),
        }
        result.append(merged)

    return result, sorted(to_merge)
