# """
# DataVisualizerAgent - Generates chart configurations
# """
# from typing import Dict, Any, List
# from data_visualizer import DataVisualizerAgent as DataVisualizer


# class DataVisualizerAgent:
#     """
#     Agent responsible for data visualization.
#     Generates multiple chart type configurations (bar, line, pie).
#     """
    
#     def __init__(self, llm_url: str = "http://localhost:11434/api/generate", model: str = "llama3:latest", top_n: int = 20):
#         self.visualizer = DataVisualizer(llm_url=llm_url, model=model, top_n=top_n)
    
#     def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
#         """
#         Execute the agent: generate chart configurations.
        
#         Args:
#             state: Current state dictionary containing 'data' and 'columns'
            
#         Returns:
#             Updated state with 'chart_configs'
#         """
#         print(f"\n🤖 [DataVisualizerAgent] Starting...")
        
#         data = state.get("data", [])
#         columns = state.get("columns", [])
#         user_query = state.get("user_query", "")
        
#         # Generate multiple chart configurations
#         chart_configs = self.visualizer.generate_multiple_chart_configs(data, columns, user_query)
        
#         state["chart_configs"] = chart_configs
#         state["current_step"] = "data_visualizer"
        
#         print(f"✅ [DataVisualizerAgent] Generated chart types: {list(chart_configs.keys())}")
#         return state


"""
DataVisualizerAgent - Self-contained chart configuration generator
"""
from typing import Dict, Any, List, Optional
import requests
import json
import re

# Column-name heuristics used to tell a genuine numeric *measure* (an
# amount, quantity, price - something worth summing/plotting) apart from a
# numeric-looking *identifier* (a sales document number, customer ID, key)
# that happens to be stored as a number. Charting the latter (one bar per
# unique ID, count=1 each) is the "1000 bars of nothing" failure mode this
# gate exists to prevent.
ID_NAME_PATTERN = re.compile(
    r"(^id$|_id$|\bid\b|code$|_code$|number$|_no$|^no$|_num$|document|key$|_key$|uuid|guid)",
    re.IGNORECASE,
)
DATE_NAME_PATTERN = re.compile(
    r"(date|_dt$|timestamp|_at$|\bperiod\b|\bmonth\b|\byear\b|\bweek\b)",
    re.IGNORECASE,
)
MEASURE_NAME_HINTS = (
    "amount", "revenue", "value", "price", "qty", "quantity", "total",
    "sum", "cost", "net_value", "billed", "sales", "stock", "weight",
    "balance", "count",
)


class DataVisualizerAgent:
    """
    Self-contained agent for data visualization.

    Before picking a chart type, this agent first decides whether the
    result set is chart-worthy at all: a chart needs at least one genuine
    numeric measure column to plot. Two ID/text columns (e.g. a sales
    document number joined to a customer name) is a lookup mapping, not
    something a bar/line/pie chart can meaningfully represent - so that
    case is routed to a table instead of forcing one bar per row.
    """

    def __init__(self, llm_url: str = "http://ollama:11434/api/generate", model: str = "llama3", top_n: int = 20):
        self.llm_url = llm_url
        self.model = model
        self.top_n = top_n

    # -----------------------------
    # Public interface
    # -----------------------------
    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        print(f"\n🤖 [DataVisualizerAgent] Starting...")
        if "steps" not in state or state.get("steps") is None:
            state["steps"] = []
        data = state.get("data", [])
        columns = state.get("columns", [])
        user_query = state.get("user_query", "")

        chosen_model = state.get("model_name", self.model)

        chart_configs = self.generate_multiple_chart_configs(data, columns, user_query, target_model=chosen_model)
        state["chart_configs"] = chart_configs
        state["current_step"] = "data_visualizer"

        note = chart_configs.get("note") or ""
        if chart_configs.get("chart_worthy"):
            recommended = chart_configs.get("recommended")
            state["steps"].append(
                f"Data Visualization: SUCCESS. Recommended a {recommended} chart. {note}".strip()
            )
        else:
            # No genuine measure column in the result - don't leave the
            # row-count-only format decision made earlier (QueryFormatterAgent,
            # which has no idea what the columns actually mean) stuck on
            # "chart" when there's nothing numeric to plot.
            state["steps"].append(
                f"Data Visualization: SKIPPED. {note or 'Data has no numeric measure column, so it is not chart-worthy.'}"
            )
            if state.get("format") == "chart":
                state["format"] = "table"

        query_sense_output = state.get("query_sense_output", {})
        query_sense_output["steps"] = state["steps"]
        state["query_sense_output"] = query_sense_output

        print(f"✅ [DataVisualizerAgent] chart_worthy={chart_configs.get('chart_worthy')} recommended={chart_configs.get('recommended')}")
        return state

    # -----------------------------
    # Column classification
    # -----------------------------
    def _looks_like_date_value(self, v: Any) -> bool:
        if isinstance(v, str):
            return bool(re.match(r"^\d{4}-\d{2}-\d{2}", v)) or bool(re.match(r"^\d{2}/\d{2}/\d{4}", v))
        return False

    def _classify_columns(self, data: List[Dict[str, Any]], columns: List[str]) -> Dict[str, Dict[str, Any]]:
        n = len(data)
        info = {}
        for c in columns:
            non_null = [row.get(c) for row in data if row.get(c) is not None]
            distinct = len({str(v) for v in non_null})
            is_numeric = bool(non_null) and all(
                isinstance(v, (int, float)) and not isinstance(v, bool) for v in non_null
            )
            is_date = (not is_numeric) and (
                bool(DATE_NAME_PATTERN.search(c)) or (bool(non_null) and all(self._looks_like_date_value(v) for v in non_null))
            )
            # A column reads as an identifier either by name (sales_document,
            # customer_id, ...) or by shape - nearly one distinct value per
            # row, i.e. a unique/near-unique key rather than something worth
            # grouping or summing.
            looks_like_id = bool(ID_NAME_PATTERN.search(c)) or (n > 1 and distinct >= max(2, int(n * 0.9)))
            info[c] = {
                "numeric": is_numeric,
                "date": is_date,
                "distinct": distinct,
                "looks_like_id": looks_like_id,
            }
        return info

    def _pick_measure_column(self, columns_info: Dict[str, Dict[str, Any]]) -> Optional[str]:
        candidates = [c for c, i in columns_info.items() if i["numeric"] and not i["looks_like_id"]]
        if not candidates:
            return None

        def score(c: str):
            cl = c.lower()
            return (0 if any(h in cl for h in MEASURE_NAME_HINTS) else 1, c)

        return sorted(candidates, key=score)[0]

    def _pick_date_column(self, columns_info: Dict[str, Dict[str, Any]]) -> Optional[str]:
        dates = [c for c, i in columns_info.items() if i["date"]]
        return dates[0] if dates else None

    def _pick_dimension_columns(self, columns_info: Dict[str, Dict[str, Any]], exclude: str) -> List[str]:
        return [c for c, i in columns_info.items() if c != exclude and not i["numeric"] and not i["date"]]

    # -----------------------------
    # Aggregation helpers
    # -----------------------------
    def _numeric(self, raw_val: Any) -> float:
        try:
            return float(raw_val) if raw_val is not None else 0.0
        except (TypeError, ValueError):
            return 0.0

    def _aggregate_topn(self, data: List[Dict[str, Any]], dim_col: str, measure_col: str, top_n: int = 15, agg: str = "sum"):
        """Group rows by dim_col, aggregate measure_col, and keep only the
        top N groups by aggregate value (descending), folding the rest into
        a single 'Others' bucket - rather than rendering one bar per raw row
        for a high-cardinality dimension like a unique customer name."""
        groups: Dict[str, float] = {}
        for row in data:
            raw_key = row.get(dim_col)
            key = str(raw_key) if raw_key is not None else "Unknown"
            groups[key] = groups.get(key, 0.0) + (1.0 if agg == "count" else self._numeric(row.get(measure_col)))

        items = sorted(groups.items(), key=lambda kv: kv[1], reverse=True)
        if len(items) > top_n:
            top = items[:top_n]
            others_total = sum(v for _, v in items[top_n:])
            if others_total:
                top.append(("Others", others_total))
            items = top
        return [k for k, _ in items], [v for _, v in items]

    def _aggregate_by_date(self, data: List[Dict[str, Any]], date_col: str, measure_col: str):
        groups: Dict[str, float] = {}
        for row in data:
            key = str(row.get(date_col))
            groups[key] = groups.get(key, 0.0) + self._numeric(row.get(measure_col))
        labels = sorted(groups.keys())
        return labels, [groups[l] for l in labels]

    # -----------------------------
    # Chart generation logic
    # -----------------------------
    def generate_multiple_chart_configs(self, data: List[Dict[str, Any]], columns: List[str], user_query: str = "", target_model: str = None) -> Dict[str, Any]:
        not_chart_worthy = {"bar": {}, "line": {}, "pie": {}, "recommended": None, "chart_worthy": False}

        if not data or not columns:
            return {**not_chart_worthy, "note": "No data was returned to visualize."}

        row_count = len(data)
        columns_info = self._classify_columns(data, columns)
        measure_col = self._pick_measure_column(columns_info)

        # ---- Chart-worthiness gate ----
        # No genuine numeric measure column (aggregate/amount/quantity/price)
        # in the result set at all - only identifiers and/or free text. This
        # is a lookup/mapping result (e.g. sales_document -> customer name),
        # not something a bar/line/pie chart can represent: charting it would
        # mean one bar per row, each with count=1. Skip charting and let the
        # data render as a table instead.
        if not measure_col:
            return {
                **not_chart_worthy,
                "note": (
                    "This is a lookup mapping, not something that visualizes well as a "
                    "chart - here's the data as a table instead."
                ),
            }

        date_col = self._pick_date_column(columns_info)
        dim_candidates = self._pick_dimension_columns(columns_info, exclude=measure_col)
        non_id_dims = [c for c in dim_candidates if not columns_info[c]["looks_like_id"]]
        # Prefer a dimension whose cardinality is meaningfully below the row
        # count (a real grouping column); fall back to any non-identifier
        # dimension (even high-cardinality, like a unique customer name) so
        # it can still be aggregated/top-N'd below rather than dropped.
        low_card_dims = [c for c in non_id_dims if columns_info[c]["distinct"] < row_count]
        usable_dims = low_card_dims or non_id_dims

        configs: Dict[str, Any] = {}

        if date_col:
            labels, values = self._aggregate_by_date(data, date_col, measure_col)
            configs["line"] = self._generate_line_chart(labels, values, date_col, measure_col)
            configs["bar"] = self._generate_bar_chart(labels, values, date_col, measure_col)
            configs["pie"] = {}
            recommended = "line"
            note = f"Aggregated {measure_col} over {date_col} across {len(labels)} time bucket(s)."

        elif usable_dims:
            dim_col = usable_dims[0]
            distinct = columns_info[dim_col]["distinct"]
            if distinct <= 20:
                labels, values = self._aggregate_topn(data, dim_col, measure_col, top_n=20)
                configs["bar"] = self._generate_bar_chart(labels, values, dim_col, measure_col)
                configs["line"] = self._generate_line_chart(labels, values, dim_col, measure_col)
                configs["pie"] = self._generate_pie_chart(labels, values, dim_col, measure_col) if distinct <= 8 else {}
                recommended = "bar"
                note = f"Grouped {row_count} row(s) by {dim_col} and aggregated {measure_col} across {distinct} categories, sorted descending."
            else:
                labels, values = self._aggregate_topn(data, dim_col, measure_col, top_n=15)
                configs["bar"] = self._generate_bar_chart(labels, values, dim_col, measure_col)
                configs["line"] = {}
                configs["pie"] = {}
                recommended = "bar"
                note = (
                    f"{dim_col} has {distinct} distinct values, so rows were grouped by {dim_col} and "
                    f"aggregated on {measure_col}, keeping only the top {min(15, len(labels))} plus an "
                    f"'Others' bucket instead of charting all {row_count} raw rows."
                )
        else:
            # Only a measure column, no usable grouping dimension - plot it
            # across rows rather than forcing a bar-per-row chart.
            labels = [f"Row {i + 1}" for i in range(row_count)]
            values = [self._numeric(row.get(measure_col)) for row in data]
            configs["line"] = self._generate_line_chart(labels, values, "Row", measure_col)
            configs["bar"] = {}
            configs["pie"] = {}
            recommended = "line"
            note = f"Plotted {measure_col} across {row_count} row(s) (no grouping dimension in the result)."

        configs["recommended"] = recommended
        configs["chart_worthy"] = True
        configs["measure"] = measure_col
        configs["note"] = note
        return configs

    # -----------------------------
    # Helper chart generators
    # -----------------------------
    # A wider, more vibrant palette than the old 4-color list, so charts
    # with more than a handful of categories don't run out of colors (which
    # left later slices/bars undefined/blank) and don't read as flat and
    # monochrome. Cycled with modulo so any number of labels is covered.
    PALETTE = [
        'rgba(255, 99, 132, 0.85)',   # red/pink
        'rgba(54, 162, 235, 0.85)',   # blue
        'rgba(255, 206, 86, 0.85)',   # yellow
        'rgba(75, 192, 192, 0.85)',   # teal
        'rgba(153, 102, 255, 0.85)',  # purple
        'rgba(255, 159, 64, 0.85)',   # orange
        'rgba(46, 204, 113, 0.85)',   # green
        'rgba(231, 76, 60, 0.85)',    # dark red
        'rgba(52, 152, 219, 0.85)',   # light blue
        'rgba(241, 196, 15, 0.85)',   # gold
        'rgba(155, 89, 182, 0.85)',   # violet
        'rgba(26, 188, 156, 0.85)',   # turquoise
    ]

    def _palette(self, n: int) -> List[str]:
        return [self.PALETTE[i % len(self.PALETTE)] for i in range(n)]

    def _generate_bar_chart(self, labels: List[str], values: List[float], label_col: str, data_col: str) -> Dict[str, Any]:
        if not labels or not values:
            return {}
        dynamic_height = max(400, len(labels) * 25)
        colors = self._palette(len(labels))
        return {
            "type": "bar",
            "data": {"labels": labels, "datasets": [{
                "label": f"{data_col}",
                "data": values,
                "backgroundColor": colors,
                "borderColor": [c.replace(', 0.85)', ', 1)') for c in colors],
                "borderWidth": 1,
                "borderRadius": 4,
            }]},
            "options": {"indexAxis": "y" if len(labels) > 10 else "x", "responsive": True, "maintainAspectRatio": False},
            "height": dynamic_height
        }

    def _generate_line_chart(self, labels: List[str], values: List[float], label_col: str, data_col: str) -> Dict[str, Any]:
        if not labels or not values:
            return {}
        return {
            "type": "line",
            "data": {"labels": labels, "datasets": [{
                "label": f"{data_col}",
                "data": values,
                "fill": True,
                "backgroundColor": "rgba(153, 102, 255, 0.15)",
                "borderColor": "rgba(153, 102, 255, 1)",
                "pointBackgroundColor": "rgba(255, 99, 132, 1)",
                "pointBorderColor": "#fff",
                "pointRadius": 4,
                "tension": 0.3,
            }]},
            "options": {"responsive": True, "maintainAspectRatio": True}
        }

    def _generate_pie_chart(self, labels: List[str], values: List[float], label_col: str, data_col: str) -> Dict[str, Any]:
        if not labels or not values:
            return {}
        colors = self._palette(len(labels))
        return {
            "type": "pie",
            "data": {"labels": labels, "datasets": [{
                "label": f"{data_col}",
                "data": values,
                "backgroundColor": colors,
                "borderColor": "#1E1E1E",
                "borderWidth": 2,
            }]},
            "options": {"responsive": True, "maintainAspectRatio": True}
        }
