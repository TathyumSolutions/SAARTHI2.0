#!/usr/bin/env python3
"""
validation_api.py
==================
A small stub "external validation" API standing in for the third-party
and internal-systems calls a real manufacturer makes during vendor/customer
onboarding and shop-floor operations: GSTIN/PAN format validation, a mock
machine health/status lookup, and a quality-inspection summary lookup keyed
off production_order_id. It exists so Saarthi's API-connector datasource
type has something realistic to call against the manufacturing demo data,
alongside the Postgres database and the Excel reference tables.

This is NOT a real GSTN/government integration - there is no live GSTIN
verification here, only format/structure validation plus deterministic
lookups against the seeded manufacturing_demo_db. Do not point this at
production data or treat its responses as a real compliance verification.

Run:
    python validation_api.py                # http://localhost:8601
    MANUFACTURING_DATABASE_URL=... python validation_api.py

Endpoints:
    GET  /health
    POST /validate/gstin                  {"gstin": "27ABCDE1234F1Z5"}
    POST /validate/pan                    {"pan": "ABCDE1234F"}
    GET  /machine/status/<machine_id>
    GET  /machine/health/<machine_id>
    GET  /quality/inspection/<production_order_id>
"""
from __future__ import annotations

import os
import re
from datetime import date
from urllib.parse import urlparse

import psycopg2
import psycopg2.extras
from flask import Flask, jsonify, request

app = Flask(__name__)

PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")

STATE_CODE_BY_GST_PREFIX = {
    "27": "Maharashtra", "07": "Delhi", "29": "Karnataka", "33": "Tamil Nadu",
    "36": "Telangana", "24": "Gujarat", "19": "West Bengal", "08": "Rajasthan",
    "09": "Uttar Pradesh", "10": "Bihar", "23": "Madhya Pradesh", "04": "Chandigarh",
    "03": "Punjab", "21": "Odisha", "18": "Assam", "20": "Jharkhand",
    "22": "Chhattisgarh", "32": "Kerala", "37": "Andhra Pradesh",
    "05": "Uttarakhand", "30": "Goa", "06": "Haryana",
}


def db_url() -> str:
    base = os.getenv("MANUFACTURING_DATABASE_URL", "postgresql://saarthi:password@localhost:5432/postgres")
    parsed = urlparse(base)
    return parsed._replace(path="/manufacturing_demo_db").geturl()


def get_conn():
    return psycopg2.connect(db_url(), cursor_factory=psycopg2.extras.RealDictCursor)


@app.get("/health")
def health():
    return jsonify(status="ok", service="manufacturing-demo-validation-api")


@app.post("/validate/gstin")
def validate_gstin():
    data = request.get_json(silent=True) or {}
    gstin = (data.get("gstin") or "").strip().upper()
    valid = bool(GSTIN_RE.match(gstin))
    state = STATE_CODE_BY_GST_PREFIX.get(gstin[:2]) if valid else None
    pan_component = gstin[2:12] if valid else None
    return jsonify(
        gstin=gstin, valid_format=valid, state_code=gstin[:2] if valid else None,
        state=state, embedded_pan=pan_component,
        note="Format/structure check only - not a live GSTN verification.",
    )


@app.post("/validate/pan")
def validate_pan():
    data = request.get_json(silent=True) or {}
    pan = (data.get("pan") or "").strip().upper()
    valid = bool(PAN_RE.match(pan))
    fourth_char_map = {
        "P": "Individual", "C": "Company", "H": "HUF", "F": "Firm/LLP",
        "A": "AOP", "T": "Trust", "B": "BOI", "L": "Local Authority",
        "J": "Artificial Judicial Person", "G": "Government",
    }
    holder_type = fourth_char_map.get(pan[3], "Unknown") if valid else None
    return jsonify(
        pan=pan, valid_format=valid, holder_type=holder_type,
        note="Format/structure check only - not a live Income Tax Department verification.",
    )


@app.get("/machine/status/<int:machine_id>")
def machine_status(machine_id: int):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT machine_id, machine_code, machine_name, machine_type, plant_id,
                       manufacturer, installed_date, capacity_units_per_hour, status
                FROM machines WHERE machine_id = %s
            """, (machine_id,))
            row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        return jsonify(error="machine not found"), 404
    return jsonify(
        machine_id=row["machine_id"], machine_code=row["machine_code"],
        machine_name=row["machine_name"], machine_type=row["machine_type"],
        plant_id=row["plant_id"], manufacturer=row["manufacturer"],
        installed_date=row["installed_date"].isoformat(),
        capacity_units_per_hour=float(row["capacity_units_per_hour"]),
        status=row["status"], as_of=date.today().isoformat(),
    )


@app.get("/machine/health/<int:machine_id>")
def machine_health(machine_id: int):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT machine_id, status FROM machines WHERE machine_id = %s", (machine_id,))
            machine = cur.fetchone()
            if not machine:
                return jsonify(error="machine not found"), 404
            cur.execute("""
                SELECT count(*) AS event_count,
                       coalesce(sum(downtime_hours), 0) AS total_downtime_hours,
                       coalesce(sum(maintenance_cost), 0) AS total_maintenance_cost,
                       count(*) FILTER (WHERE criticality IN ('High', 'Critical')) AS high_criticality_events
                FROM machine_downtime
                WHERE machine_id = %s AND as_of_date >= (CURRENT_DATE - INTERVAL '180 days')
            """, (machine_id,))
            summary = cur.fetchone()
    finally:
        conn.close()
    high_events = summary["high_criticality_events"]
    health_rating = "Critical" if high_events >= 3 else ("Watch" if high_events >= 1 else "Healthy")
    return jsonify(
        machine_id=machine_id, current_status=machine["status"],
        trailing_180d_downtime_events=summary["event_count"],
        trailing_180d_downtime_hours=float(summary["total_downtime_hours"]),
        trailing_180d_maintenance_cost=float(summary["total_maintenance_cost"]),
        trailing_180d_high_criticality_events=high_events,
        health_rating=health_rating,
        note="Derived from the seeded manufacturing_demo_db machine_downtime log, not a live IoT/condition-monitoring feed.",
    )


@app.get("/quality/inspection/<int:production_order_id>")
def quality_inspection(production_order_id: int):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT inspection_id, inspection_date, inspection_stage, sample_size,
                       defects_found, defect_rate_pct, result
                FROM quality_inspection_records
                WHERE production_order_id = %s
                ORDER BY inspection_date
            """, (production_order_id,))
            records = cur.fetchall()
    finally:
        conn.close()
    if not records:
        return jsonify(error="no inspection records found for this production order"), 404
    overall = "Fail" if any(r["result"] == "Fail" for r in records) else (
        "Rework" if any(r["result"] == "Rework" for r in records) else "Pass"
    )
    return jsonify(
        production_order_id=production_order_id,
        overall_result=overall,
        inspections=[
            dict(
                inspection_id=r["inspection_id"], inspection_date=r["inspection_date"].isoformat(),
                inspection_stage=r["inspection_stage"], sample_size=r["sample_size"],
                defects_found=r["defects_found"], defect_rate_pct=float(r["defect_rate_pct"]),
                result=r["result"],
            )
            for r in records
        ],
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8601")), debug=False)
