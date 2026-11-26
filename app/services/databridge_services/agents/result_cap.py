"""
Safety cap on how many rows a generated query may bring back - and,
crucially, *knowing* when that cap cut the result short.

The old behaviour appended ``LIMIT 1000`` to any query without a LIMIT and
then treated the 1,000 rows as the whole answer, so counts, means and
"most common" values computed downstream described an arbitrary sample as
if it were the full table. Here the query is fetched with one row more
than the cap: if that extra row comes back, the result is flagged as
truncated and every later step can say so.
"""
from __future__ import annotations

import re
from typing import Tuple

ROW_CAP = 1000

_HAS_LIMIT = re.compile(r"(?i)\bLIMIT\s+\d+\b|\bFETCH\s+(FIRST|NEXT)\s+\d+")


def apply_row_cap(normalized_sql: str, cap: int = ROW_CAP) -> Tuple[str, bool]:
    """Return ``(sql_to_run, cap_applied)``.

    ``normalized_sql`` must already be stripped of its trailing ``;``. A
    query that sets its own LIMIT is left alone (the author chose that
    size, so it is not a hidden truncation); otherwise ``cap + 1`` rows are
    requested so truncation can be detected.
    """
    if _HAS_LIMIT.search(normalized_sql):
        return normalized_sql, False
    return f"{normalized_sql} LIMIT {cap + 1};", True


def trim_to_cap(df, cap_applied: bool, cap: int = ROW_CAP):
    """Return ``(df, truncated)``, dropping the probe row when present."""
    if cap_applied and len(df) > cap:
        return df.head(cap).reset_index(drop=True), True
    return df, False


def truncation_note(row_count: int, cap: int = ROW_CAP) -> str:
    """User-facing sentence for a truncated result."""
    return (
        f"Only the first {cap:,} rows were returned (the full result is larger), so the "
        f"{row_count:,} rows shown are a sample: counts, totals and averages below describe "
        f"that sample, not the whole dataset. Ask for a grouped summary (e.g. 'per product') "
        f"to get exact figures."
    )


def insight_guard(truncated: bool, row_count: int, cap: int = ROW_CAP) -> str:
    """Extra instruction for the insight prompt when the data was capped."""
    if not truncated:
        return ""
    return (
        f"IMPORTANT: this data is only the first {cap:,} rows of a larger result ({row_count:,} rows "
        f"shown). Do NOT present counts, frequencies, totals or averages as if they cover the whole "
        f"dataset - say they are based on a {cap:,}-row sample."
    )
