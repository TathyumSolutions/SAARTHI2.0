"""
Rules appended to every data-insight prompt, so insights answer the
user's question instead of describing whatever numeric column happened
to be in the result (e.g. processing-fee statistics for a question about
spread and acquisition cost), and are honest about capped samples.

Shared by both insight generators (the graph's DataInsightGeneratorAgent
and the one inside QueryFormatterAgent).
"""
from __future__ import annotations

from .result_cap import insight_guard

_BASE_RULES = """
RULES FOR INSIGHTS:
- Insights must answer the User Query. Talk about the measures the question asks for, not about unrelated columns.
- If the data does not contain something the question asks for (a figure from another data source, or a column that is not in the result), say so plainly in the first insight instead of describing other columns.
- Do not speculate beyond the data: no claims about lenders, companies, regions or time periods that are not in the result.
- Rates, percentages and scores are averaged, never added up.
"""


def build_insight_rules(truncated: bool = False, row_count: int = 0) -> str:
    """Prompt text with the base rules plus the sample warning when needed."""
    guard = insight_guard(truncated, row_count)
    return _BASE_RULES + (f"- {guard}\n" if guard else "")
