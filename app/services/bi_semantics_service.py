"""
BI Semantics layer - maps business entities (tables) to the measure and
aggregation that actually matters for them, so ambiguous questions like
"show me sales orders by customer" default to SUM(net_value) instead of a
row per order that only degenerates into a meaningless one-count-per-row
chart.

Built-in defaults below cover common SAP-style tables out of the box.
Per-user overrides/additions are stored in BiSemanticsConfig and take
priority over a built-in default for the same table - editable via the
/api/bi-semantics routes (see app/routes/bi_semantics_routes.py) and the
Settings > BI Semantics admin page, with no code change required to tune
"what matters" for a given entity.
"""
from typing import Dict, List, Optional

from app.models.bi_semantics_config import BiSemanticsConfig

# table_name -> {measure_column, aggregation, entity_label}
# Keys are matched case-insensitively against the tables a query touches.
DEFAULT_BI_SEMANTICS: Dict[str, Dict[str, str]] = {
    "vbak": {"measure_column": "net_value", "aggregation": "SUM", "entity_label": "Sales Orders"},
    "vbap": {"measure_column": "net_value", "aggregation": "SUM", "entity_label": "Sales Order Items"},
    "vbrk": {"measure_column": "billed_amount", "aggregation": "SUM", "entity_label": "Billing Documents"},
    "vbrp": {"measure_column": "net_value", "aggregation": "SUM", "entity_label": "Billing Items"},
    "likp": {"measure_column": "quantity", "aggregation": "SUM", "entity_label": "Deliveries"},
    "lips": {"measure_column": "quantity", "aggregation": "SUM", "entity_label": "Delivery Items"},
    "mseg": {"measure_column": "quantity", "aggregation": "SUM", "entity_label": "Material Movements"},
    "ekpo": {"measure_column": "net_value", "aggregation": "SUM", "entity_label": "Purchase Order Items"},
    "mara": {"measure_column": "stock_value", "aggregation": "SUM", "entity_label": "Materials"},
    "mard": {"measure_column": "stock_quantity", "aggregation": "SUM", "entity_label": "Storage Location Stock"},
    "mbew": {"measure_column": "stock_value", "aggregation": "SUM", "entity_label": "Material Valuation"},
    "bkpf": {"measure_column": "amount", "aggregation": "SUM", "entity_label": "Accounting Documents"},
    "bseg": {"measure_column": "amount", "aggregation": "SUM", "entity_label": "Accounting Line Items"},
    "kna1": {"measure_column": "*", "aggregation": "COUNT", "entity_label": "Customers"},
}


def get_bi_semantics(user_id: int = 1) -> Dict[str, Dict[str, str]]:
    """Built-in defaults, overlaid with this user's own DB-stored overrides
    (a user's own row for a table always wins over the built-in default for
    that same table)."""
    merged = {k.lower(): dict(v) for k, v in DEFAULT_BI_SEMANTICS.items()}
    try:
        rows = BiSemanticsConfig.query.filter_by(user_id=user_id).all()
    except Exception as e:
        print(f"⚠️ [BiSemantics] Could not load user overrides for user {user_id}: {e}")
        return merged

    for row in rows:
        merged[row.table_name.lower()] = {
            "measure_column": row.measure_column,
            "aggregation": (row.aggregation or "SUM").upper(),
            "entity_label": row.entity_label or row.table_name,
        }
    return merged


def build_measure_guidance(tables: List[str], query_sense_output: Optional[dict], user_id: int = 1) -> str:
    """
    Builds a prompt-injectable hint telling the SQL Generator which default
    measure/aggregation applies to the tables this question touches - but
    only when the question is actually ambiguous about what to measure
    (QuerySense found no explicit aggregation and no measure column already
    selected). Returns "" when there's nothing relevant to add, so callers
    can unconditionally append it to their prompt.
    """
    if not tables:
        return ""

    query_sense_output = query_sense_output or {}
    if query_sense_output.get("aggregations"):
        # The question already specifies what to aggregate - don't second-guess it.
        return ""

    semantics = get_bi_semantics(user_id)
    already_selected = {c.split(".", 1)[-1].lower() for c in (query_sense_output.get("columns") or [])}

    hints = []
    for table in tables:
        entry = semantics.get(str(table).lower())
        if not entry:
            continue
        measure_col = entry.get("measure_column")
        if not measure_col or measure_col == "*":
            continue
        if measure_col.lower() in already_selected:
            # Already explicitly selecting the measure column - nothing to add.
            continue
        agg = (entry.get("aggregation") or "SUM").upper()
        label = entry.get("entity_label") or table
        hints.append(f"- Table '{table}' ({label}): default measure is {agg}({measure_col}).")

    if not hints:
        return ""

    return (
        "\nBI SEMANTICS GUIDANCE:\n"
        "The user's question does not explicitly name a metric to aggregate. "
        "For the tables below, business users care about the aggregated measure, "
        "not a raw row count - add the listed aggregate as a SELECT column "
        "(grouped by whatever dimension column(s) the question is asking about) "
        "instead of returning unaggregated rows, unless the question is clearly "
        "asking to list/browse individual raw records.\n"
        + "\n".join(hints)
    )


def list_entries(user_id: int = 1) -> List[dict]:
    """All entries visible to this user: DB overrides first, then any
    built-in default not already overridden - the shape the admin settings
    grid renders."""
    overrides = {row.table_name.lower(): row for row in BiSemanticsConfig.query.filter_by(user_id=user_id).all()}

    entries = []
    for table_name, row in overrides.items():
        entries.append({**row.to_dict(), "source": "custom"})

    for table_name, defaults in DEFAULT_BI_SEMANTICS.items():
        if table_name.lower() in overrides:
            continue
        entries.append({
            "id": None,
            "user_id": user_id,
            "company_code": None,
            "table_name": table_name,
            "entity_label": defaults.get("entity_label"),
            "measure_column": defaults.get("measure_column"),
            "aggregation": defaults.get("aggregation"),
            "source": "default",
        })

    entries.sort(key=lambda e: e["table_name"])
    return entries
