#!/usr/bin/env python3
"""
validation_api.py
==================
A small stub "external validation" API standing in for the third-party
services a real NBFC calls during onboarding/underwriting: PAN/GST format +
checksum-style validation, Aadhaar format validation, and a mock credit
bureau score lookup. It exists so Saarthi's API-connector datasource type
has something realistic to call against the lending demo data, alongside
the Postgres database and the Excel reference tables.

This is NOT a real government/bureau integration - there is no live PAN,
GST, or Aadhaar verification here, only format/structure validation plus a
deterministic mock lookup keyed off customer_id so results are stable
across calls. Do not point this at production data or treat its responses
as a real KYC verification.

Run:
    python validation_api.py                # http://localhost:8600
    LENDING_DATABASE_URL=... python validation_api.py

Endpoints:
    GET  /health
    POST /validate/pan          {"pan": "ABCDE1234F"}
    POST /validate/gstin        {"gstin": "27ABCDE1234F1Z5"}
    POST /validate/aadhaar      {"aadhaar_masked": "XXXX-XXXX-1234"}
    GET  /bureau/score/<customer_id>
    GET  /bureau/report/<customer_id>
"""
from __future__ import annotations

import hashlib
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
AADHAAR_MASKED_RE = re.compile(r"^XXXX-XXXX-[0-9]{4}$")

STATE_CODE_BY_GST_PREFIX = {
    "27": "Maharashtra", "29": "Karnataka", "33": "Tamil Nadu", "36": "Telangana",
    "24": "Gujarat", "19": "West Bengal", "08": "Rajasthan", "09": "Uttar Pradesh",
    "07": "Delhi", "06": "Haryana",
}


def db_url() -> str:
    base = os.getenv("LENDING_DATABASE_URL", "postgresql://saarthi:password@localhost:5432/postgres")
    parsed = urlparse(base)
    return parsed._replace(path="/lending_demo_db").geturl()


def get_conn():
    return psycopg2.connect(db_url(), cursor_factory=psycopg2.extras.RealDictCursor)


@app.get("/health")
def health():
    return jsonify(status="ok", service="lending-demo-validation-api")


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
        pan=pan, valid_format=valid,
        holder_type=holder_type,
        note="Format/structure check only - not a live Income Tax Department verification.",
    )


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


@app.post("/validate/aadhaar")
def validate_aadhaar():
    data = request.get_json(silent=True) or {}
    masked = (data.get("aadhaar_masked") or "").strip().upper()
    valid = bool(AADHAAR_MASKED_RE.match(masked))
    return jsonify(
        aadhaar_masked=masked, valid_format=valid,
        note="Format check on the masked value only - this stub never handles a full Aadhaar number.",
    )


def _deterministic_mock_score(customer_id: int, salt: str) -> int:
    h = hashlib.sha256(f"{customer_id}:{salt}".encode()).hexdigest()
    return 300 + (int(h[:8], 16) % 601)  # 300-900


@app.get("/bureau/score/<int:customer_id>")
def bureau_score(customer_id: int):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT customer_id, cibil_score FROM customers WHERE customer_id = %s", (customer_id,))
            row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        return jsonify(error="customer not found"), 404
    bureau = request.args.get("bureau", "CIBIL").upper()
    score = row["cibil_score"] if bureau == "CIBIL" else _deterministic_mock_score(customer_id, bureau)
    return jsonify(
        customer_id=customer_id, bureau=bureau, score=score,
        as_of=date.today().isoformat(),
        note="Mock bureau lookup for demo purposes - CIBIL score is read from the seeded customer "
             "record, other bureaus are a deterministic simulated variant of it.",
    )


@app.get("/bureau/report/<int:customer_id>")
def bureau_report(customer_id: int):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT c.customer_id, c.first_name, c.last_name, c.cibil_score,
                       count(l.loan_id) AS active_loans,
                       coalesce(sum(l.sanctioned_amount) FILTER (WHERE l.loan_status = 'Active'), 0) AS total_outstanding_estimate
                FROM customers c
                LEFT JOIN loans l ON l.customer_id = c.customer_id
                WHERE c.customer_id = %s
                GROUP BY c.customer_id, c.first_name, c.last_name, c.cibil_score
            """, (customer_id,))
            row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        return jsonify(error="customer not found"), 404
    return jsonify(
        customer_id=row["customer_id"],
        name=f"{row['first_name']} {row['last_name']}",
        cibil_score=row["cibil_score"],
        active_loans=row["active_loans"],
        total_outstanding_estimate=float(row["total_outstanding_estimate"]),
        report_date=date.today().isoformat(),
        note="Derived from the seeded lending_demo_db, not a real bureau report.",
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8600")), debug=False)
