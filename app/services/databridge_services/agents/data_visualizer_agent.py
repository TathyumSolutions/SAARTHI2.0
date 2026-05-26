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
from typing import Dict, Any, List
import requests
import json
import re
from collections import Counter

class DataVisualizerAgent:
    """
    Self-contained agent for data visualization.
    Generates multiple chart configurations (bar, line, pie) based on the data.
    """

    def __init__(self, llm_url: str = "http://ollama:11434/api/generate", model: str = "llama3:latest", top_n: int = 20):
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

        chart_configs = self.generate_multiple_chart_configs(data, columns, user_query)
        state["chart_configs"] = chart_configs
        state["current_step"] = "data_visualizer"

        chart_types = list(chart_configs.keys())
        if chart_types:
            state["steps"].append(
                f"Data Visualization: SUCCESS. Prepared interactive {', '.join(chart_types)} charts for analysis."
            )
        else:
            state["steps"].append(
                "Data Visualization: COMPLETED. Evaluated data for visual potential; no complex charts required."
            )
            
        query_sense_output = state.get("query_sense_output", {})
        query_sense_output["steps"] = state["steps"]
        state["query_sense_output"] = query_sense_output

        print(f"✅ [DataVisualizerAgent] Generated chart types: {list(chart_configs.keys())}")
        return state

    # -----------------------------
    # Chart generation logic
    # -----------------------------
    def generate_multiple_chart_configs(self, data: List[Dict[str, Any]], columns: List[str], user_query: str = "") -> Dict[str, Any]:
        if not data or not columns:
            return {"bar": {}, "line": {}, "pie": {}, "recommended": "bar"}

        first = data[0]
        col_types = {}
        for c in columns:
            v = first.get(c)
            if isinstance(v, (int, float)):
                col_types[c] = "numeric"
            elif isinstance(v, str):
                col_types[c] = "string"
            else:
                col_types[c] = "other"

        string_cols = [c for c, t in col_types.items() if t == "string"]
        numeric_cols = [c for c, t in col_types.items() if t == "numeric"]

        configs = {}
        recommended = "bar"

        if string_cols and numeric_cols:
            label_col = string_cols[0]
            data_col = numeric_cols[0]
            labels = [str(row.get(label_col, "")) for row in data]
            values = [row.get(data_col, 0) for row in data]
            unique_labels = len(set(labels))
            recommended = "bar" if unique_labels > 20 else "line" if "trend" in user_query.lower() else "bar"

            configs["bar"] = self._generate_bar_chart(labels, values, label_col, data_col)
            configs["line"] = self._generate_line_chart(labels, values, label_col, data_col)
            configs["pie"] = self._generate_pie_chart(labels[:15], values[:15], label_col, data_col)

        elif string_cols:
            label_col = string_cols[0]
            labels_raw = [str(row.get(label_col, "")) for row in data]
            counts = Counter(labels_raw)
            all_items = counts.most_common()
            labels = [t[0] for t in all_items]
            values = [t[1] for t in all_items]
            configs["bar"] = self._generate_bar_chart(labels, values, label_col, "Count")
            configs["line"] = self._generate_line_chart(labels, values, label_col, "Count")
            configs["pie"] = self._generate_pie_chart(labels[:15], values[:15], label_col, "Count")
            recommended = "bar"

        elif numeric_cols:
            num_col = numeric_cols[0]
            labels = [f"Row {i+1}" for i in range(len(data))]
            values = [row.get(num_col, 0) for row in data]
            configs["bar"] = self._generate_bar_chart(labels, values, "Row", num_col)
            configs["line"] = self._generate_line_chart(labels, values, "Row", num_col)
            configs["pie"] = {}
            recommended = "line"

        else:
            configs["bar"] = {}
            configs["line"] = {}
            configs["pie"] = {}

        configs["recommended"] = recommended
        return configs

    # -----------------------------
    # Helper chart generators
    # -----------------------------
    def _generate_bar_chart(self, labels: List[str], values: List[float], label_col: str, data_col: str) -> Dict[str, Any]:
        if not labels or not values:
            return {}
        dynamic_height = max(400, len(labels) * 25)
        return {
            "type": "bar",
            "data": {"labels": labels, "datasets": [{"label": f"{data_col}", "data": values, "backgroundColor": "rgba(54, 162, 235, 0.6)", "borderColor": "rgba(54, 162, 235, 1)", "borderWidth": 1}]},
            "options": {"indexAxis": "y" if len(labels) > 10 else "x", "responsive": True, "maintainAspectRatio": False},
            "height": dynamic_height
        }

    def _generate_line_chart(self, labels: List[str], values: List[float], label_col: str, data_col: str) -> Dict[str, Any]:
        if not labels or not values:
            return {}
        return {
            "type": "line",
            "data": {"labels": labels, "datasets": [{"label": f"{data_col}", "data": values, "fill": False, "borderColor": "rgba(75, 192, 192, 1)"}]},
            "options": {"responsive": True, "maintainAspectRatio": True}
        }

    def _generate_pie_chart(self, labels: List[str], values: List[float], label_col: str, data_col: str) -> Dict[str, Any]:
        if not labels or not values:
            return {}
        colors = ['rgba(255, 99, 132, 0.8)','rgba(54, 162, 235, 0.8)','rgba(255, 206, 86, 0.8)','rgba(75, 192, 192, 0.8)']
        return {
            "type": "pie",
            "data": {"labels": labels, "datasets": [{"label": f"{data_col}", "data": values, "backgroundColor": colors[:len(labels)]}]},
            "options": {"responsive": True, "maintainAspectRatio": True}
        }
