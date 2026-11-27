"""
Tests for automated_metamind._infer_db_relations.

Run against the demo lending/manufacturing schemas, the inference used to
hand QuerySenseAgent 39 and 56 "relations" that were almost all wrong:
sibling foreign keys (agents.branch_id <-> loans.branch_id, which pairs
every agent with every loan of a branch - the wrong path for "loans by
agent", which goes through loan_applications), plain attributes that
share a name (order_date, unit_price, category, mobile, gstin,
is_active), and "paid_date" accepted as an id because "paid" contains
"id". Real undeclared foreign keys must still be found.
"""
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app.services.automated_metamind import _infer_db_relations, _looks_like_join_key


def _col(name, samples=None, unique_values=None, null_count=0):
    return {"name": name, "data_type": "integer", "sample_values": samples or [],
            "unique_values": unique_values, "null_count": null_count}


def _table(columns, pk=None, unique=None, fks=None, row_count=100):
    return {
        "row_count": row_count,
        "constraints": {
            "primary_key": pk or [],
            "unique_columns": unique or [],
            "foreign_keys": [
                {"column": c, "references_table": t, "references_column": rc} for c, t, rc in (fks or [])
            ],
        },
        "columns": columns,
    }


def _pairs(relations):
    return {(r["from_table"], r["from_column"], r["to_table"], r["to_column"]) for r in relations}


def test_whole_token_key_names():
    assert _looks_like_join_key("material_id")
    assert _looks_like_join_key("customerId")
    assert _looks_like_join_key("po_number")
    assert _looks_like_join_key("matid")
    assert not _looks_like_join_key("paid_date")
    assert not _looks_like_join_key("annotation")
    assert not _looks_like_join_key("is_active")
    assert not _looks_like_join_key("mobile")


def test_sibling_foreign_keys_are_not_a_relation():
    tables = {
        "branches": _table([_col("branch_id")], pk=["branch_id"]),
        "agents": _table([_col("agent_id"), _col("branch_id")], pk=["agent_id"],
                         fks=[("branch_id", "branches", "branch_id")]),
        "loans": _table([_col("loan_id"), _col("branch_id")], pk=["loan_id"],
                        fks=[("branch_id", "branches", "branch_id")]),
    }
    assert _infer_db_relations(tables) == []


def test_shared_attribute_names_are_not_a_relation():
    tables = {
        "production_orders": _table(
            [_col("production_order_id"), _col("order_date", ["2026-01-01"]), _col("unit_price", [10])],
            pk=["production_order_id"]),
        "purchase_orders": _table(
            [_col("po_id"), _col("order_date", ["2026-01-01"]), _col("unit_price", [10]),
             _col("paid_date", ["2026-01-02"])],
            pk=["po_id"]),
        "repayment_schedule": _table([_col("schedule_id"), _col("paid_date", ["2026-01-02"])],
                                     pk=["schedule_id"]),
    }
    assert _infer_db_relations(tables) == []


def test_unique_attribute_without_matching_values_is_not_a_relation():
    tables = {
        "customers": _table([_col("customer_id"), _col("gstin", ["27AAA"])], pk=["customer_id"], unique=["gstin"]),
        "suppliers": _table([_col("supplier_id"), _col("gstin", ["29BBB"])], pk=["supplier_id"], unique=["gstin"]),
    }
    assert _infer_db_relations(tables) == []


def test_undeclared_fk_to_a_primary_key_is_found_and_points_at_the_key():
    tables = {
        "bill_of_materials": _table([_col("bom_id"), _col("material_id", [1, 2, 3])], pk=["bom_id"]),
        "raw_materials": _table([_col("material_id", [1, 2, 3])], pk=["material_id"]),
    }
    assert _pairs(_infer_db_relations(tables)) == {
        ("bill_of_materials", "material_id", "raw_materials", "material_id"),
    }


def test_sap_style_names_join_through_a_declared_key():
    tables = {
        "mara": _table([_col("MATNR", ["M1", "M2"])], pk=["MATNR"]),
        "marc": _table([_col("MATNR", ["M1", "M2"]), _col("WERKS", ["P1"])], pk=["MATNR", "WERKS"]),
        "mbew": _table([_col("MATNR", ["M1"]), _col("BWKEY", ["P1"])]),
    }
    pairs = _pairs(_infer_db_relations(tables))
    assert ("mbew", "MATNR", "mara", "MATNR") in pairs


def test_unannotated_schema_keeps_id_name_matches():
    tables = {
        "orders": _table([_col("order_id"), _col("customer_id", [1, 2])]),
        "customers": _table([_col("customer_id", [1, 2]), _col("city", ["Pune"])]),
        "suppliers": _table([_col("supplier_id"), _col("city", ["Pune"])]),
    }
    pairs = {frozenset({(a, b), (c, d)}) for a, b, c, d in _pairs(_infer_db_relations(tables))}
    assert frozenset({("orders", "customer_id"), ("customers", "customer_id")}) in pairs
    assert not any(("customers", "city") in p for p in pairs)


def test_profiled_unique_id_column_counts_as_a_key():
    tables = {
        "employees": _table([_col("employee_id", [1, 2], unique_values=100)], row_count=100),
        "shipments": _table([_col("shipment_id"), _col("employee_id", [1, 2], unique_values=40)],
                            pk=["shipment_id"], row_count=500),
    }
    assert _pairs(_infer_db_relations(tables)) == {
        ("shipments", "employee_id", "employees", "employee_id"),
    }
