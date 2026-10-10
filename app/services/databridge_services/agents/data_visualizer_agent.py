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
        top_n = self.chart_top_n_from_instructions(state.get("system_instructions", ""))

        chart_configs = self.generate_multiple_chart_configs(
            data, columns, user_query, target_model=chosen_model, top_n=top_n,
            preferred_measure=state.get("preferred_measure"),
        )
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
                "fractional": is_numeric and any(isinstance(v, float) and not v.is_integer() for v in non_null),
                "date": is_date,
                "distinct": distinct,
                "looks_like_id": looks_like_id,
            }
        return info

    def _pick_measure_column(self, columns_info: Dict[str, Dict[str, Any]]) -> Optional[str]:
        # The near-unique "shape" test can't disqualify a column whose name
        # says it's a measure, or one holding fractional values (ids are
        # whole numbers): grouped totals are usually all different, so
        # "amount by region" over 3 regions would otherwise have no measure.
        def is_measure(c: str, i: Dict[str, Any]) -> bool:
            if not i["numeric"] or ID_NAME_PATTERN.search(c):
                return False
            if any(h in c.lower() for h in MEASURE_NAME_HINTS) or i.get("fractional"):
                return True
            return not i["looks_like_id"]

        candidates = [c for c, i in columns_info.items() if is_measure(c, i)]
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
        # A numeric column that looks like an id (branch_id, customer_id, ...)
        # is still a legitimate grouping key even though it fails the numeric
        # "measure" test - only genuinely numeric measures (amounts, counts)
        # should be excluded here. Readable labels (branch_name) sort ahead of
        # ids (branch_id) so a result carrying both is charted by name.
        dims = [
            c for c, i in columns_info.items()
            if c != exclude and not i["date"] and (not i["numeric"] or i["looks_like_id"])
        ]
        # Sorted on the name pattern, not looks_like_id - a name column with one
        # row per branch is near-unique too and would tie with the id.
        return sorted(dims, key=lambda c: bool(ID_NAME_PATTERN.search(c)))

    # -----------------------------
    # Aggregation helpers
    # -----------------------------
    def _numeric(self, raw_val: Any) -> float:
        try:
            return float(raw_val) if raw_val is not None else 0.0
        except (TypeError, ValueError):
            return 0.0

    def _aggregate_topn(self, data: List[Dict[str, Any]], dim_col: str, measure_col: str, top_n: int = 5, agg: str = "sum"):
        """Group rows by dim_col, aggregate measure_col, and keep only the top
        N groups by value (descending, ties broken by label so the cut is
        stable). Returns (labels, values, total_group_count). No 'Others'
        bucket: one bar summing 100+ categories dwarfs the real bars and
        reads as the biggest category - the full list goes to the Excel
        download instead."""
        groups: Dict[str, float] = {}
        for row in data:
            raw_key = row.get(dim_col)
            key = str(raw_key) if raw_key is not None else "Unknown"
            groups[key] = groups.get(key, 0.0) + (1.0 if agg == "count" else self._numeric(row.get(measure_col)))

        items = sorted(groups.items(), key=lambda kv: (-kv[1], kv[0]))
        return [k for k, _ in items[:top_n]], [v for _, v in items[:top_n]], len(items)

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
    # Readability guidelines, applied to every chart built here:
    #  - Categorical bars show only the top N categories (CHART_TOP_N, or
    #    the number in the user's Query Instructions - see
    #    chart_top_n_from_instructions), sorted descending; the rest is
    #    offered as an Excel download in the chat.
    #  - One series = one color, no legend (the axis titles say what it is).
    #  - Axis titles and a chart title in plain words ("Branch Name", not
    #    "branch_name"); long category labels are shortened, with the full
    #    text kept in the tooltip.
    #  - Long labels or many bars go horizontal so labels stay readable.
    #  - Pie only for a complete set of <= PIE_MAX_SLICES slices - a pie of
    #    the top 5 out of 110 would misrepresent the shares.
    #  - Time series keep every period (dropping months would be misleading).
    CHART_TOP_N = 5          # default; a user's Query Instructions can override it
    CHART_TOP_N_MAX = 50
    PIE_MAX_SLICES = 5       # more slices than this stop being comparable
    MAX_LABEL_CHARS = 24
    SERIES_COLOR = "rgba(124, 58, 237, 0.85)"
    SERIES_BORDER = "rgba(124, 58, 237, 1)"
    AXIS_TEXT_COLOR = "#CBD5E1"
    GRID_COLOR = "rgba(255, 255, 255, 0.08)"

    _NUMBER_WORDS = {
        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
        "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20,
    }
    _CHART_WORDS = re.compile(r"\b(chart|charts|graph|graphs|bar|bars|visual|visuals|visualization|plot|plots)\b", re.I)
    _TOP_N = re.compile(r"\btop[\s-]+(\d{1,3}|" + "|".join(_NUMBER_WORDS) + r")\b", re.I)
    _N_BARS = re.compile(r"\b(\d{1,3}|" + "|".join(_NUMBER_WORDS) + r")\s+(bars|categories|items)\b", re.I)

    @classmethod
    def chart_top_n_from_instructions(cls, instructions: str) -> int:
        """How many categories a bar chart shows, read from the user's Query
        Instructions (Settings page) - e.g. "Show top 10 in charts" or
        "Charts: 8 bars". Only a sentence that talks about charts counts, so
        "For top 3 questions, rank by sales" doesn't change the chart.
        Falls back to CHART_TOP_N when nothing applies."""
        for sentence in re.split(r"[.;\n]+", instructions or ""):
            if not cls._CHART_WORDS.search(sentence):
                continue
            match = cls._TOP_N.search(sentence) or cls._N_BARS.search(sentence)
            if match:
                raw = match.group(1).lower()
                n = int(raw) if raw.isdigit() else cls._NUMBER_WORDS[raw]
                if n >= 1:
                    return min(n, cls.CHART_TOP_N_MAX)
        return cls.CHART_TOP_N

    @staticmethod
    def _pretty(col: str) -> str:
        return re.sub(r"[_\s]+", " ", str(col or "")).strip().title()

    def generate_multiple_chart_configs(self, data: List[Dict[str, Any]], columns: List[str], user_query: str = "", target_model: str = None, top_n: Optional[int] = None,
                                        preferred_measure: Optional[str] = None) -> Dict[str, Any]:
        top_n = top_n or self.CHART_TOP_N
        not_chart_worthy = {"bar": {}, "line": {}, "pie": {}, "recommended": None, "chart_worthy": False}

        if not data or not columns:
            return {**not_chart_worthy, "note": "No data was returned to visualize."}

        row_count = len(data)
        columns_info = self._classify_columns(data, columns)
        measure_col = self._pick_measure_column(columns_info)
        # A caller that knows which figure the question is about (e.g. the
        # Result Combiner's computed commission column) can ask for it to be
        # the one plotted, as long as it's genuinely numeric.
        if preferred_measure and columns_info.get(preferred_measure, {}).get("numeric"):
            measure_col = preferred_measure

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
        # A text column is a label unless its NAME says it's an identifier.
        # Its shape can't be trusted here: a grouped result has exactly one
        # row per branch, so branch_name is unique per row and would
        # otherwise be mistaken for an id - leaving nothing to chart by.
        label_dims = [c for c in dim_candidates
                      if not columns_info[c]["numeric"] and not ID_NAME_PATTERN.search(c)]
        usable_dims = label_dims or dim_candidates

        configs: Dict[str, Any] = {}
        measure_label = self._pretty(measure_col)
        truncated = False
        total_categories = None

        if date_col:
            labels, values = self._aggregate_by_date(data, date_col, measure_col)
            title = f"{measure_label} by {self._pretty(date_col)}"
            configs["line"] = self._generate_line_chart(labels, values, date_col, measure_col, title=title)
            configs["bar"] = self._generate_bar_chart(labels, values, date_col, measure_col, title=title)
            configs["pie"] = {}
            recommended = "line"
            note = f"Aggregated {measure_col} over {date_col} across {len(labels)} time bucket(s)."

        elif usable_dims:
            dim_col = usable_dims[0]
            labels, values, total_categories = self._aggregate_topn(data, dim_col, measure_col, top_n=top_n)
            truncated = total_categories > len(labels)
            dim_label = self._pretty(dim_col)
            title = (f"Top {len(labels)} {dim_label} by {measure_label}" if truncated
                     else f"{measure_label} by {dim_label}")
            configs["bar"] = self._generate_bar_chart(labels, values, dim_col, measure_col, title=title)
            configs["line"] = {}
            configs["pie"] = {} if truncated or len(labels) > self.PIE_MAX_SLICES else self._generate_pie_chart(labels, values, dim_col, measure_col, title=title)
            recommended = "bar"
            if truncated:
                note = (
                    f"Showing the top {len(labels)} of {total_categories} {dim_label} values by "
                    f"{measure_label} to keep the chart readable."
                )
            else:
                note = f"Grouped {row_count} row(s) by {dim_col} and aggregated {measure_col} across {total_categories} categories, sorted descending."
        else:
            # Only a measure column, no usable grouping dimension - plot it
            # across rows rather than forcing a bar-per-row chart.
            labels = [f"Row {i + 1}" for i in range(row_count)]
            values = [self._numeric(row.get(measure_col)) for row in data]
            configs["line"] = self._generate_line_chart(labels, values, "Row", measure_col, title=measure_label)
            configs["bar"] = {}
            configs["pie"] = {}
            recommended = "line"
            note = f"Plotted {measure_col} across {row_count} row(s) (no grouping dimension in the result)."

        configs["recommended"] = recommended
        configs["chart_worthy"] = True
        configs["measure"] = measure_col
        configs["note"] = note
        # Read by the chat UI to offer the full result as an Excel download
        # when the chart only shows part of it.
        configs["truncated"] = truncated
        configs["total_categories"] = total_categories
        return configs

    # -----------------------------
    # Helper chart generators
    # -----------------------------
    # Multi-color palette, only for pie slices - where color is the only way
    # to tell categories apart. Bars use the single SERIES_COLOR.
    PALETTE = [
        'rgba(124, 58, 237, 0.85)',   # violet
        'rgba(54, 162, 235, 0.85)',   # blue
        'rgba(75, 192, 192, 0.85)',   # teal
        'rgba(255, 159, 64, 0.85)',   # orange
        'rgba(255, 99, 132, 0.85)',   # pink
        'rgba(255, 206, 86, 0.85)',   # yellow
        'rgba(46, 204, 113, 0.85)',   # green
        'rgba(155, 89, 182, 0.85)',   # purple
    ]

    def _palette(self, n: int) -> List[str]:
        return [self.PALETTE[i % len(self.PALETTE)] for i in range(n)]

    def _short_label(self, label: Any) -> str:
        text = str(label)
        return text if len(text) <= self.MAX_LABEL_CHARS else text[: self.MAX_LABEL_CHARS - 1] + "…"

    @staticmethod
    def _all_integers(values: List[float]) -> bool:
        return all(float(v).is_integer() for v in values)

    def _axis(self, title: str, integer_ticks: bool = False, begin_at_zero: bool = False) -> Dict[str, Any]:
        axis: Dict[str, Any] = {
            "title": {"display": bool(title), "text": title, "color": self.AXIS_TEXT_COLOR},
            "ticks": {"color": self.AXIS_TEXT_COLOR},
            "grid": {"color": self.GRID_COLOR},
        }
        if begin_at_zero:
            axis["beginAtZero"] = True
        if integer_ticks:
            axis["ticks"]["precision"] = 0
        return axis

    def _title_plugin(self, title: str) -> Dict[str, Any]:
        return {"display": bool(title), "text": title, "color": "#F1F5F9", "font": {"size": 14, "weight": "600"}}

    def _generate_bar_chart(self, labels: List[str], values: List[float], label_col: str, data_col: str, title: str = "") -> Dict[str, Any]:
        if not labels or not values:
            return {}
        full_labels = [str(l) for l in labels]
        short_labels = [self._short_label(l) for l in full_labels]
        horizontal = len(labels) > 8 or any(len(l) > 12 for l in full_labels)
        value_axis = self._axis(self._pretty(data_col), integer_ticks=self._all_integers(values), begin_at_zero=True)
        category_axis = self._axis(self._pretty(label_col))
        return {
            "type": "bar",
            "data": {"labels": short_labels, "datasets": [{
                "label": self._pretty(data_col),
                "data": values,
                "backgroundColor": self.SERIES_COLOR,
                "borderColor": self.SERIES_BORDER,
                "borderWidth": 1,
                "borderRadius": 4,
                "maxBarThickness": 36,
            }]},
            "options": {
                "indexAxis": "y" if horizontal else "x",
                "responsive": True,
                "maintainAspectRatio": False,
                "plugins": {"legend": {"display": False}, "title": self._title_plugin(title)},
                "scales": {
                    "x": value_axis if horizontal else category_axis,
                    "y": category_axis if horizontal else value_axis,
                },
            },
            # Untruncated labels for tooltips - Chart.js options are plain
            # JSON here, so the frontend reads this to show the full name.
            "full_labels": full_labels,
            "height": max(240, len(labels) * 40) if horizontal else 280,
        }

    def _generate_line_chart(self, labels: List[str], values: List[float], label_col: str, data_col: str, title: str = "") -> Dict[str, Any]:
        if not labels or not values:
            return {}
        return {
            "type": "line",
            "data": {"labels": [str(l) for l in labels], "datasets": [{
                "label": self._pretty(data_col),
                "data": values,
                "fill": True,
                "backgroundColor": "rgba(124, 58, 237, 0.15)",
                "borderColor": self.SERIES_BORDER,
                "pointBackgroundColor": self.SERIES_BORDER,
                "pointBorderColor": "#fff",
                "pointRadius": 3,
                "tension": 0.3,
            }]},
            "options": {
                "responsive": True,
                "maintainAspectRatio": False,
                "plugins": {"legend": {"display": False}, "title": self._title_plugin(title)},
                "scales": {
                    "x": self._axis(self._pretty(label_col)),
                    "y": self._axis(self._pretty(data_col), integer_ticks=self._all_integers(values)),
                },
            },
            "height": 280,
        }

    def _generate_pie_chart(self, labels: List[str], values: List[float], label_col: str, data_col: str, title: str = "") -> Dict[str, Any]:
        if not labels or not values or len(labels) > self.PIE_MAX_SLICES:
            return {}
        colors = self._palette(len(labels))
        return {
            "type": "pie",
            "data": {"labels": [self._short_label(l) for l in labels], "datasets": [{
                "label": self._pretty(data_col),
                "data": values,
                "backgroundColor": colors,
                "borderColor": "#1E1E1E",
                "borderWidth": 2,
            }]},
            "options": {
                "responsive": True,
                "maintainAspectRatio": False,
                "plugins": {
                    "legend": {"display": True, "position": "right", "labels": {"color": self.AXIS_TEXT_COLOR}},
                    "title": self._title_plugin(title),
                },
            },
            "full_labels": [str(l) for l in labels],
            "height": 280,
        }
