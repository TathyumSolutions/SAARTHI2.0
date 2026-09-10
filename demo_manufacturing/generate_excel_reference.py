#!/usr/bin/env python3
"""
generate_excel_reference.py
============================
Builds the "external data" Excel workbooks that live alongside the
manufacturing demo database - the kind of reference data a real factory
keeps in spreadsheets rather than the core ERP/MES system, and that
Saarthi should be able to cross-check core DB figures against via its
spreadsheet connector (app/services/spreadsheet_service.py).

Reads plant/product/raw-material context straight out of the
already-loaded manufacturing_demo_db so the workbooks are consistent with
whatever --scale was used for db_manufacturing.py, then writes 4 workbooks
under demo_manufacturing/output/excel/:

  01_raw_material_price_benchmarks.xlsx - market benchmark prices used to
                                           sanity-check standard costing
  02_plant_master.xlsx                  - plant roster + staffing/machine
                                           summary
  03_vendor_rating_card.xlsx            - supplier quality-rating slab
                                           criteria and empanelment tiers
  04_machine_maintenance_schedule.xlsx  - preventive maintenance interval
                                           reference by machine type

Usage:
    python generate_excel_reference.py --db-url postgresql://saarthi:password@localhost:5432/postgres
"""
from __future__ import annotations

import argparse
import os

import psycopg2
import psycopg2.extras
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from urllib.parse import urlparse

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output", "excel")

HEADER_FILL = PatternFill(start_color="1F3864", end_color="1F3864", fill_type="solid")
HEADER_FONT = Font(color="FFFFFF", bold=True)
TITLE_FONT = Font(bold=True, size=14, color="1F3864")
NOTE_FONT = Font(italic=True, size=9, color="808080")


def derive_db_url(base_url: str, db_name: str) -> str:
    parsed = urlparse(base_url)
    return parsed._replace(path=f"/{db_name}").geturl()


def style_header_row(ws, row_idx: int, ncols: int):
    for c in range(1, ncols + 1):
        cell = ws.cell(row=row_idx, column=c)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def autosize(ws, ncols: int, min_width=10, max_width=45):
    for c in range(1, ncols + 1):
        letter = get_column_letter(c)
        max_len = min_width
        for cell in ws[letter]:
            if cell.value is not None:
                max_len = max(max_len, len(str(cell.value)))
        ws.column_dimensions[letter].width = min(max_width, max_len + 2)


def write_title_block(ws, title: str, subtitle: str, start_row: int = 1) -> int:
    ws.cell(row=start_row, column=1, value=title).font = TITLE_FONT
    ws.cell(row=start_row + 1, column=1, value=subtitle).font = NOTE_FONT
    return start_row + 3


# ---------------------------------------------------------------------
# Workbook 1: Raw material price benchmarks
# ---------------------------------------------------------------------

def build_material_benchmark_workbook(materials: list[dict]):
    wb = Workbook()
    ws = wb.active
    ws.title = "Material Benchmarks"
    row = write_title_block(
        ws, "Raw Material Market Price Benchmarks - Reference Card",
        "Illustrative market reference prices for cross-checking standard costing against current "
        "commodity/market rates. Synthetic data for demo/testing purposes only.",
    )
    ws.cell(row=row, column=1, value="Commodity Index Snapshot").font = Font(bold=True, size=12)
    row += 1
    index_rows = [
        ("Steel (HR Coil) Index", "+3.2% MoM", "National average, ex-works"),
        ("Aluminium (LME-linked) Index", "-1.8% MoM", "Includes import duty component"),
        ("Copper Index", "+2.1% MoM", ""),
        ("Polymer/Resin Index", "+0.6% MoM", "Crude-linked, tracks Brent with a lag"),
    ]
    headers = ["Index", "MoM Change", "Notes"]
    for c, h in enumerate(headers, start=1):
        ws.cell(row=row, column=c, value=h)
    style_header_row(ws, row, len(headers))
    row += 1
    for r in index_rows:
        for c, v in enumerate(r, start=1):
            ws.cell(row=row, column=c, value=v)
        row += 1

    row += 2
    ws.cell(row=row, column=1, value="Material Standard Cost vs Market Benchmark").font = Font(bold=True, size=12)
    row += 1
    headers = ["Material Code", "Material Name", "Category", "Standard Unit Price (Rs)",
               "Market Benchmark Low (Rs)", "Market Benchmark High (Rs)", "Within Benchmark?"]
    for c, h in enumerate(headers, start=1):
        ws.cell(row=row, column=c, value=h)
    style_header_row(ws, row, len(headers))
    row += 1
    # Market benchmark = standard price nudged, to give a realistic "mostly in
    # band, a couple drifting outside" check for Saarthi demos.
    for mtl in materials:
        bench_low = round(mtl["price"] * 0.90, 2)
        bench_high = round(mtl["price"] * 1.10, 2)
        within = "Yes"
        if mtl["code"] in ("CU-WIRE", "ELE-PCB"):
            bench_high = round(mtl["price"] * 0.85, 2)  # deliberately flag these as priced above market
            within = "Review - above benchmark"
        ws.cell(row=row, column=1, value=mtl["code"])
        ws.cell(row=row, column=2, value=mtl["name"])
        ws.cell(row=row, column=3, value=mtl["category"])
        ws.cell(row=row, column=4, value=mtl["price"])
        ws.cell(row=row, column=5, value=bench_low)
        ws.cell(row=row, column=6, value=bench_high)
        ws.cell(row=row, column=7, value=within)
        row += 1

    autosize(ws, len(headers))
    return wb


# ---------------------------------------------------------------------
# Workbook 2: Plant master
# ---------------------------------------------------------------------

def build_plant_master_workbook(plants: list[dict], staffing: dict[int, dict]):
    wb = Workbook()
    ws = wb.active
    ws.title = "Plant Master"
    row = write_title_block(
        ws, "Plant Network Master",
        "Plant roster with staffing and machine-count summary, maintained outside the core ERP as the "
        "operations team's working file.",
    )
    headers = ["Plant Code", "Plant Name", "City", "State", "Region", "Pincode", "Plant Type",
               "Opened Date", "Active?", "Employee Count", "Machine Count"]
    for c, h in enumerate(headers, start=1):
        ws.cell(row=row, column=c, value=h)
    style_header_row(ws, row, len(headers))
    row += 1
    for p in plants:
        st = staffing.get(p["plant_id"], {"employees": 0, "machines": 0})
        ws.cell(row=row, column=1, value=p["plant_code"])
        ws.cell(row=row, column=2, value=p["plant_name"])
        ws.cell(row=row, column=3, value=p["city"])
        ws.cell(row=row, column=4, value=p["state"])
        ws.cell(row=row, column=5, value=p["region"])
        ws.cell(row=row, column=6, value=p["pincode"])
        ws.cell(row=row, column=7, value=p["plant_type"])
        ws.cell(row=row, column=8, value=p["opened_date"].isoformat())
        ws.cell(row=row, column=9, value="Yes" if p["is_active"] else "No")
        ws.cell(row=row, column=10, value=st["employees"])
        ws.cell(row=row, column=11, value=st["machines"])
        row += 1
    autosize(ws, len(headers))
    return wb


# ---------------------------------------------------------------------
# Workbook 3: Vendor rating card
# ---------------------------------------------------------------------

def build_vendor_rating_workbook():
    wb = Workbook()
    ws = wb.active
    ws.title = "Vendor Rating"
    row = write_title_block(
        ws, "Supplier / Vendor Quality Rating Card",
        "Empanelment tiers and the quarterly scorecard criteria used to rate raw-material suppliers, "
        "combined into the quality_rating figure stored on each supplier's master record.",
    )
    headers = ["Rating Band", "Score Range", "Empanelment Tier", "PO Priority", "Payment Terms"]
    for c, h in enumerate(headers, start=1):
        ws.cell(row=row, column=c, value=h)
    style_header_row(ws, row, len(headers))
    row += 1
    tiers = [
        ("Excellent", "4.5 - 5.0", "Preferred / Strategic", "First allocation on urgent POs", "45 days"),
        ("Good", "3.5 - 4.4", "Approved", "Standard allocation", "30 days"),
        ("Acceptable", "2.5 - 3.4", "Approved (Watch List)", "Standard allocation, dual-sourced", "15 days"),
        ("Below Threshold", "< 2.5", "Under Review / Suspended", "No new POs until re-audit", "Advance payment only"),
    ]
    for r in tiers:
        for c, v in enumerate(r, start=1):
            ws.cell(row=row, column=c, value=v)
        row += 1

    row += 2
    ws.cell(row=row, column=1, value="Scorecard Weightage").font = Font(bold=True, size=12)
    row += 1
    headers2 = ["Criterion", "Weightage"]
    for c, h in enumerate(headers2, start=1):
        ws.cell(row=row, column=c, value=h)
    style_header_row(ws, row, len(headers2))
    row += 1
    for crit, weight in [
        ("On-time delivery (OTD %)", "35%"), ("Incoming quality acceptance rate", "35%"),
        ("Price competitiveness vs benchmark", "15%"), ("Responsiveness / documentation compliance", "15%"),
    ]:
        ws.cell(row=row, column=1, value=crit)
        ws.cell(row=row, column=2, value=weight)
        row += 1

    autosize(ws, len(headers))
    return wb


# ---------------------------------------------------------------------
# Workbook 4: Machine maintenance schedule
# ---------------------------------------------------------------------

def build_maintenance_schedule_workbook(machine_type_counts: dict[str, int]):
    wb = Workbook()
    ws = wb.active
    ws.title = "Maintenance Schedule"
    row = write_title_block(
        ws, "Preventive Maintenance Interval Reference",
        "Recommended preventive-maintenance frequency and estimated downtime by machine type, "
        "maintained by the Plant Engineering / Maintenance Planning team.",
    )
    headers = ["Machine Type", "Machines in Fleet", "PM Frequency", "Est. PM Downtime (hrs)",
               "Lubrication Interval", "Overhaul Interval"]
    for c, h in enumerate(headers, start=1):
        ws.cell(row=row, column=c, value=h)
    style_header_row(ws, row, len(headers))
    row += 1
    # Illustrative maintenance cadence by machine type - not any specific
    # OEM's actual service manual.
    cadence = {
        "CNC Lathe": ("Monthly", 4, "Weekly", "3 years"),
        "CNC Milling (VMC)": ("Monthly", 4, "Weekly", "3 years"),
        "Injection Molding Machine": ("Bi-Monthly", 6, "Weekly", "5 years"),
        "Press Brake": ("Quarterly", 3, "Monthly", "7 years"),
        "Hydraulic Press": ("Quarterly", 5, "Monthly", "7 years"),
        "Welding Robot": ("Monthly", 3, "Weekly", "6 years"),
        "Induction Furnace": ("Monthly", 8, "Weekly", "10 years"),
        "Surface Grinder": ("Bi-Monthly", 3, "Monthly", "5 years"),
        "Laser Cutting Machine": ("Monthly", 5, "Weekly", "6 years"),
        "Powder Coating Line": ("Quarterly", 6, "Monthly", "8 years"),
        "Assembly Line Station": ("Quarterly", 2, "Monthly", "10 years"),
        "Testing Rig": ("Bi-Monthly", 2, "Monthly", "8 years"),
    }
    for mtype, (freq, hrs, lube, overhaul) in cadence.items():
        ws.cell(row=row, column=1, value=mtype)
        ws.cell(row=row, column=2, value=machine_type_counts.get(mtype, 0))
        ws.cell(row=row, column=3, value=freq)
        ws.cell(row=row, column=4, value=hrs)
        ws.cell(row=row, column=5, value=lube)
        ws.cell(row=row, column=6, value=overhaul)
        row += 1
    autosize(ws, len(headers))
    return wb


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-url", default=os.getenv("MANUFACTURING_DATABASE_URL", "postgresql://saarthi:password@localhost:5432/postgres"))
    parser.add_argument("--db-name", default="manufacturing_demo_db")
    args = parser.parse_args()

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    conn = psycopg2.connect(derive_db_url(args.db_url, args.db_name))
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("""
        SELECT material_id, material_code AS code, material_name AS name, category,
               standard_unit_price AS price
        FROM raw_materials ORDER BY material_id
    """)
    materials = [dict(r) for r in cur.fetchall()]
    for mtl in materials:
        mtl["price"] = float(mtl["price"])

    cur.execute("""
        SELECT plant_id, plant_code, plant_name, city, state, region, pincode, plant_type,
               opened_date, is_active
        FROM plants ORDER BY plant_id
    """)
    plants = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT plant_id, count(*) AS n FROM employees GROUP BY plant_id")
    emp_counts = {r["plant_id"]: r["n"] for r in cur.fetchall()}
    cur.execute("SELECT plant_id, count(*) AS n FROM machines GROUP BY plant_id")
    machine_counts = {r["plant_id"]: r["n"] for r in cur.fetchall()}
    staffing = {
        p["plant_id"]: {"employees": emp_counts.get(p["plant_id"], 0), "machines": machine_counts.get(p["plant_id"], 0)}
        for p in plants
    }

    cur.execute("SELECT machine_type, count(*) AS n FROM machines GROUP BY machine_type")
    machine_type_counts = {r["machine_type"]: r["n"] for r in cur.fetchall()}
    conn.close()

    build_material_benchmark_workbook(materials).save(os.path.join(OUTPUT_DIR, "01_raw_material_price_benchmarks.xlsx"))
    build_plant_master_workbook(plants, staffing).save(os.path.join(OUTPUT_DIR, "02_plant_master.xlsx"))
    build_vendor_rating_workbook().save(os.path.join(OUTPUT_DIR, "03_vendor_rating_card.xlsx"))
    build_maintenance_schedule_workbook(machine_type_counts).save(os.path.join(OUTPUT_DIR, "04_machine_maintenance_schedule.xlsx"))

    print(f"Wrote 4 workbooks to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
