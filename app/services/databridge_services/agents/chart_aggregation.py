"""
How to combine several rows of one measure into a single chart value.

Adding up is right for amounts and counts, but wrong for rates,
percentages and scores: summing interest_rate_max over ~100 loan rows per
product produced bars of "2,850%". The column name decides:

* name says max / min          -> MAX / MIN
* rate, %, ratio, score, ...   -> AVERAGE
* anything else                -> SUM (amounts, counts, quantities)
"""
from __future__ import annotations

import re
from typing import Iterable, List

SUM = "sum"
AVG = "avg"
MAX = "max"
MIN = "min"
COUNT = "count"

_MAX_TOKENS = {"max", "maximum", "highest", "peak"}
_MIN_TOKENS = {"min", "minimum", "lowest"}
_AVG_TOKENS = {
    "rate", "rates", "pct", "percent", "percentage", "ratio", "score", "scores",
    "avg", "average", "mean", "median", "yield", "roi", "irr", "apr", "share",
    "probability", "likelihood", "utilization", "utilisation", "dpd", "tenure", "age",
}
_AVG_SUFFIXES = ("_pct", "_percent", "_rate", "_ratio", "_score", "_avg")

_TOKEN_SPLIT = re.compile(r"[^a-z0-9%]+")

_LABEL_PREFIX = {AVG: "Average", MAX: "Max", MIN: "Min"}


def _tokens(column_name: str) -> List[str]:
    return [t for t in _TOKEN_SPLIT.split(str(column_name or "").lower()) if t]


def choose_aggregation(column_name: str) -> str:
    """Pick SUM / AVG / MAX / MIN for a measure column from its name."""
    tokens = set(_tokens(column_name))
    if tokens & _MAX_TOKENS:
        return MAX
    if tokens & _MIN_TOKENS:
        return MIN
    lowered = str(column_name or "").lower()
    if "%" in lowered or tokens & _AVG_TOKENS or lowered.endswith(_AVG_SUFFIXES):
        return AVG
    return SUM


def combine(values: Iterable[float], how: str) -> float:
    """Combine one group's numeric values the way ``how`` says."""
    vals = list(values)
    if how == COUNT:
        return float(len(vals))
    if not vals:
        return 0.0
    if how == AVG:
        return sum(vals) / len(vals)
    if how == MAX:
        return max(vals)
    if how == MIN:
        return min(vals)
    return float(sum(vals))


def label_for(measure_label: str, how: str, aggregated: bool) -> str:
    """Chart wording for the measure, e.g. "Average Interest Rate".

    Unchanged when no group combined more than one row, for SUM (kept as
    the plain column name, as before), or when the name already says it
    (an "Interest Rate Max" column shown as MAX).
    """
    prefix = _LABEL_PREFIX.get(how)
    if not aggregated or not prefix:
        return measure_label
    if prefix.lower() in {t.lower() for t in _tokens(measure_label)}:
        return measure_label
    if how == MAX and set(_tokens(measure_label)) & _MAX_TOKENS:
        return measure_label
    if how == MIN and set(_tokens(measure_label)) & _MIN_TOKENS:
        return measure_label
    return f"{prefix} {measure_label}"
