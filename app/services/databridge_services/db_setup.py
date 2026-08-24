"""
Consolidated SAP-style demo dataset builder for Saarthi.

Merges three previously separate pieces into ONE script / ONE run:
  1. db.py                       - original 8-table SAP core (kna1, lfa1,
                                    mara, ska1, skb1, vbak, vbap, likp,
                                    lips, vbrk, vbrp, bkpf, bseg)
  2. vbak_region_orders.sql      - region-wise order breakdown (vbak_region)
  3. sap_extension_6_tables.sql  - plant/valuation/purchasing/movement
                                    (t001w, marc, mbew, ekko, ekpo, mseg)

WHY THIS IS ONE FILE AND NOT "run the extension SQL on top":
While consolidating, three ID/format mismatches turned up between what
db.py actually generates and what material_lookup.xlsx, code_lookup.xlsx,
and product_composition_process.docx expect. Left alone, these silently
break every cross-source join the demo depends on:

  - material_id: db.py made "M00001"; the Excel/docx sources use
    "MAT-00001". -> mara.material_id is now "MAT-00001" etc., and the
    FIRST 30 ROWS are an exact match to material_lookup.xlsx (including
    the FG01 finished-goods rows used in product_composition_process.docx),
    so BOM % lookups and commodity-category joins actually resolve.
  - ska1.account_group: db.py used ['1000','2000','3000']; code_lookup.xlsx's
    gl_account_group_lookup expects ['A1','B2','C3']. -> fixed.
  - kna1.country: db.py used fake.country_code() (alpha-2, ~250 possible
    values); vbak_region_orders.sql's region CASE matches alpha-3 codes
    from a fixed 17-country list, with everything else falling into an
    'APAC' catch-all. Left as-is, ~every customer would land in APAC
    regardless of where they actually are. -> customers/vendors are now
    drawn from that same 17-country list so regions genuinely vary.

  Also: vbak_region_orders.sql selected `vbap.net_value`, a column that
  doesn't exist in db.py's vbap table - that script would have errored
  outright. order_value is now computed directly when vbak_region rows
  are built, so no schema change to vbap is needed.

Run standalone:
    python db_setup.py            # build only if the DB is currently empty
    python db_setup.py --reset    # drop every table this script owns, then rebuild
    RESET_DB=yes python db_setup.py   # same as --reset, via env var

Needs DATABRIDGE_TARGET_HOST/PORT/DBNAME/USER/PASSWORD set, exactly like
the original db.py - no default host, this only ever touches the external
target DB, never the app's own database.
"""
import sys
import psycopg2
import os
import random
import base64
from psycopg2.extras import execute_values
from collections import defaultdict
from faker import Faker
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()

_REQUIRED_ENV_VARS = ("DATABRIDGE_TARGET_HOST", "DATABRIDGE_TARGET_DBNAME", "DATABRIDGE_TARGET_USER")
_missing = [v for v in _REQUIRED_ENV_VARS if not os.getenv(v)]
if _missing:
    sys.exit(
        f"Missing required environment variable(s): {', '.join(_missing)}. "
        "This script seeds an external database and has no default host - "
        "set DATABRIDGE_TARGET_HOST/PORT/DBNAME/USER/PASSWORD first."
    )

DB_CONFIG = {
    "host": os.getenv("DATABRIDGE_TARGET_HOST"),
    "port": os.getenv("DATABRIDGE_TARGET_PORT", "5432"),
    "dbname": os.getenv("DATABRIDGE_TARGET_DBNAME"),
    "user": os.getenv("DATABRIDGE_TARGET_USER"),
    "password": os.getenv("DATABRIDGE_TARGET_PASSWORD", ""),
}

fake = Faker()
Faker.seed(42)
random.seed(42)

# ---------------------------------------------------------------------
# Region-aware country list - MUST match the CASE mapping that produced
# vbak_region.region_code, or every customer falls into the ELSE branch.
# ---------------------------------------------------------------------
REGION_COUNTRIES = [
    ("USA", "NA"), ("CAN", "NA"),
    ("DEU", "EU"), ("GBR", "EU"), ("FRA", "EU"), ("ITA", "EU"), ("ESP", "EU"),
    ("IND", "APAC"), ("CHN", "APAC"), ("JPN", "APAC"), ("AUS", "APAC"), ("SGP", "APAC"),
    ("ARE", "MEA"), ("ZAF", "MEA"), ("SAU", "MEA"),
    ("BRA", "LATAM"), ("MEX", "LATAM"),
]

# ---------------------------------------------------------------------
# Curated materials 1-30 - EXACT match to material_lookup.xlsx so the
# BOM percentages in product_composition_process.docx resolve to real
# rows. Tuple = (material_id, name, material_group_code, base_unit_code).
# ---------------------------------------------------------------------
CURATED_MATERIALS = [
    ("MAT-00001", "Steel Sheet 2mm", "RM01", "KG"),
    ("MAT-00002", "Steel Rod 12mm", "RM01", "KG"),
    ("MAT-00003", "Steel Casting - Housing", "RM01", "EA"),
    ("MAT-00004", "Aluminum Sheet 1.5mm", "RM02", "KG"),
    ("MAT-00005", "Aluminum Extrusion Profile", "RM02", "MTR"),
    ("MAT-00006", "Aluminum Die Cast Bracket", "RM02", "EA"),
    ("MAT-00007", "Copper Winding Wire", "RM03", "KG"),
    ("MAT-00008", "Copper Busbar", "RM03", "KG"),
    ("MAT-00009", "Copper Terminal Lug", "RM03", "EA"),
    ("MAT-00010", "Zinc Alloy Fitting", "RM04", "EA"),
    ("MAT-00011", "Galvanized Zinc Sheet", "RM04", "KG"),
    ("MAT-00012", "ABS Polymer Housing Shell", "PLST", "EA"),
    ("MAT-00013", "Nylon Gear Component", "PLST", "EA"),
    ("MAT-00014", "Rubber Gasket Seal", "PLST", "EA"),
    ("MAT-00015", "PVC Insulated Cable 2mm", "PLST", "MTR"),
    ("MAT-00016", "Corrugated Carton - Medium", "PKG1", "EA"),
    ("MAT-00017", "Wooden Pallet - Standard", "PKG1", "EA"),
    ("MAT-00018", "Stretch Wrap Film", "PKG1", "MTR"),
    ("MAT-00019", "Foam Packaging Insert", "PKG1", "EA"),
    ("MAT-00020", "Control PCB Assembly", "ELEC", "EA"),
    ("MAT-00021", "Motor Control Relay", "ELEC", "EA"),
    ("MAT-00022", "Sensor Module - Temp/Pressure", "ELEC", "EA"),
    ("MAT-00023", "Wiring Harness Assembly", "ELEC", "EA"),
    ("MAT-00024", "Display Panel Unit", "ELEC", "EA"),
    ("MAT-00025", "Industrial Pump Assembly", "FG01", "EA"),
    ("MAT-00026", "Motor Drive Unit", "FG01", "EA"),
    ("MAT-00027", "Control Panel Enclosure", "FG01", "EA"),
    ("MAT-00028", "Conveyor Roller Assembly", "FG01", "EA"),
    ("MAT-00029", "Hydraulic Valve Block", "FG01", "EA"),
    ("MAT-00030", "Cooling Fan Assembly", "FG01", "EA"),
]
RANDOM_MATERIAL_GROUPS = ["RM01", "RM02", "RM03", "RM04", "PLST", "PKG1", "ELEC"]
RANDOM_MATERIAL_UNITS = ["KG", "EA", "MTR", "L"]
TOTAL_MATERIALS = 3000  # curated 30 + this many more, for volume/realism

PLANTS = ["PL01", "PL02", "PL03"]

# ---------------------------------------------------------------------
# Sizing. TOTAL_SALES_DOCS is the single biggest lever on database size -
# each sales doc fans out into vbak/likp/vbrk header rows plus several
# vbap/lips/vbrp/vbak_region item rows. These counts were picked to give
# a realistically full dataset (~1M rows) without the memory/runtime
# cost of pushing into the tens of millions. To reliably reach an exact
# byte target on top of that (bytes-per-row vary with Postgres version,
# TOAST/compression, and checksum settings), see pad_database_to_target_size()
# below, which measures actual size and tops up deterministically.
# ---------------------------------------------------------------------
TOTAL_CUSTOMERS = 3000
TOTAL_VENDORS = 1500
TOTAL_GL_ACCOUNTS = 2000
TOTAL_SALES_DOCS = 60000
TOTAL_BKPF_DOCS = 15000
TOTAL_EKKO = 6000
TOTAL_MSEG = 20000

TARGET_DB_SIZE_BYTES = 1_100_000_000  # ~1.02 GiB - comfortably clears "at least 1GB" either way it's defined
PAD_TABLE_NAME = "_db_size_padding"
PAD_ROW_RANDOM_BYTES = 6000  # -> ~8000 chars of base64 text per padding row
PAD_BATCH_SIZE = 2000  # rows inserted between size checks (~16 MB/batch)

# ---------------------------------------------------------------------
# SCHEMA - all 20 tables, in dependency order (parents before children).
# create_tables() below is generic and just walks this dict in order.
# ---------------------------------------------------------------------
schema = {
    "tables": {
        "kna1": {
            "columns": {
                "customer_id": {"type": "character varying(10)", "nullable": False},
                "name": {"type": "character varying(100)", "nullable": True},
                "country": {"type": "character varying(3)", "nullable": True},
                "city": {"type": "character varying(50)", "nullable": True},
                "postal_code": {"type": "character varying(10)", "nullable": True},
            },
            "primary_key": ["customer_id"],
        },
        "lfa1": {
            "columns": {
                "vendor_id": {"type": "character varying(10)", "nullable": False},
                "name": {"type": "character varying(100)", "nullable": True},
                "country": {"type": "character varying(3)", "nullable": True},
                "city": {"type": "character varying(50)", "nullable": True},
                "postal_code": {"type": "character varying(10)", "nullable": True},
            },
            "primary_key": ["vendor_id"],
        },
        "mara": {
            "columns": {
                "material_id": {"type": "character varying(18)", "nullable": False},
                "description": {"type": "character varying(100)", "nullable": True},
                "base_unit": {"type": "character varying(3)", "nullable": True},
                "material_group": {"type": "character varying(4)", "nullable": True},
            },
            "primary_key": ["material_id"],
        },
        "ska1": {
            "columns": {
                "gl_account": {"type": "character varying(10)", "nullable": False},
                "account_name": {"type": "character varying(100)", "nullable": True},
                "account_group": {"type": "character varying(4)", "nullable": True},
            },
            "primary_key": ["gl_account"],
        },
        "skb1": {
            "columns": {
                "gl_account": {"type": "character varying(10)", "nullable": False},
                "company_code": {"type": "character varying(4)", "nullable": False},
                "currency": {"type": "character varying(3)", "nullable": True},
            },
            "primary_key": ["gl_account", "company_code"],
            "foreign_keys": [{"column": "gl_account", "references": "ska1.gl_account"}],
        },
        "t001w": {
            "columns": {
                "plant": {"type": "character varying(4)", "nullable": False},
                "plant_name": {"type": "character varying(60)", "nullable": True},
                "city": {"type": "character varying(50)", "nullable": True},
                "country": {"type": "character varying(3)", "nullable": True},
            },
            "primary_key": ["plant"],
        },
        "vbak": {
            "columns": {
                "sales_document": {"type": "character varying(10)", "nullable": False},
                "customer_id": {"type": "character varying(10)", "nullable": True},
                "document_date": {"type": "date", "nullable": True},
                "total_amount": {"type": "numeric", "nullable": True},
            },
            "primary_key": ["sales_document"],
            "foreign_keys": [{"column": "customer_id", "references": "kna1.customer_id"}],
        },
        "vbap": {
            "columns": {
                "sales_document": {"type": "character varying(10)", "nullable": False},
                "item_number": {"type": "integer", "nullable": False},
                "material_id": {"type": "character varying(18)", "nullable": True},
                "quantity": {"type": "numeric", "nullable": True},
            },
            "primary_key": ["sales_document", "item_number"],
            "foreign_keys": [
                {"column": "sales_document", "references": "vbak.sales_document"},
                {"column": "material_id", "references": "mara.material_id"},
            ],
        },
        "likp": {
            "columns": {
                "delivery_number": {"type": "character varying(10)", "nullable": False},
                "sales_document": {"type": "character varying(10)", "nullable": True},
                "delivery_date": {"type": "date", "nullable": True},
            },
            "primary_key": ["delivery_number"],
            "foreign_keys": [{"column": "sales_document", "references": "vbak.sales_document"}],
        },
        "lips": {
            "columns": {
                "delivery_number": {"type": "character varying(10)", "nullable": False},
                "item_number": {"type": "integer", "nullable": False},
                "material_id": {"type": "character varying(18)", "nullable": True},
                "quantity": {"type": "numeric", "nullable": True},
            },
            "primary_key": ["delivery_number", "item_number"],
            "foreign_keys": [
                {"column": "delivery_number", "references": "likp.delivery_number"},
                {"column": "material_id", "references": "mara.material_id"},
            ],
        },
        "vbrk": {
            "columns": {
                "billing_number": {"type": "character varying(10)", "nullable": False},
                "sales_document": {"type": "character varying(10)", "nullable": True},
                "billing_date": {"type": "date", "nullable": True},
                "total_amount": {"type": "numeric", "nullable": True},
            },
            "primary_key": ["billing_number"],
            "foreign_keys": [{"column": "sales_document", "references": "vbak.sales_document"}],
        },
        "vbrp": {
            "columns": {
                "billing_number": {"type": "character varying(10)", "nullable": False},
                "item_number": {"type": "integer", "nullable": False},
                "material_id": {"type": "character varying(18)", "nullable": True},
                "quantity": {"type": "numeric", "nullable": True},
            },
            "primary_key": ["billing_number", "item_number"],
            "foreign_keys": [
                {"column": "billing_number", "references": "vbrk.billing_number"},
                {"column": "material_id", "references": "mara.material_id"},
            ],
        },
        "bkpf": {
            "columns": {
                "document_number": {"type": "character varying(10)", "nullable": False},
                "company_code": {"type": "character varying(4)", "nullable": True},
                "fiscal_year": {"type": "integer", "nullable": True},
                "document_type": {"type": "character varying(2)", "nullable": True},
                "document_date": {"type": "date", "nullable": True},
                "posting_date": {"type": "date", "nullable": True},
                "currency": {"type": "character varying(3)", "nullable": True},
                "reference": {"type": "text", "nullable": True},
            },
            "primary_key": ["document_number"],
        },
        "bseg": {
            "columns": {
                "document_number": {"type": "character varying(10)", "nullable": False},
                "item_number": {"type": "integer", "nullable": False},
                "posting_key": {"type": "character varying(2)", "nullable": True},
                "account_type": {"type": "character varying(1)", "nullable": True},
                "account_number": {"type": "character varying(10)", "nullable": True},
                "amount": {"type": "numeric", "nullable": True},
                "tax_code": {"type": "character varying(2)", "nullable": True},
                "cost_center": {"type": "character varying(10)", "nullable": True},
                "profit_center": {"type": "character varying(10)", "nullable": True},
                "text": {"type": "text", "nullable": True},
            },
            "primary_key": ["document_number", "item_number"],
            "foreign_keys": [{"column": "document_number", "references": "bkpf.document_number"}],
        },
        "vbak_region": {
            "columns": {
                "sales_document": {"type": "character varying(10)", "nullable": False},
                "customer_id": {"type": "character varying(10)", "nullable": True},
                "region_code": {"type": "character varying(6)", "nullable": True},
                "order_date": {"type": "date", "nullable": True},
                "material_id": {"type": "character varying(18)", "nullable": False},
                "order_qty": {"type": "numeric", "nullable": True},
                "order_value": {"type": "numeric", "nullable": True},
            },
            "primary_key": ["sales_document", "material_id"],
            "foreign_keys": [
                {"column": "sales_document", "references": "vbak.sales_document"},
                {"column": "customer_id", "references": "kna1.customer_id"},
                {"column": "material_id", "references": "mara.material_id"},
            ],
        },
        "marc": {
            "columns": {
                "material_id": {"type": "character varying(18)", "nullable": False},
                "plant": {"type": "character varying(4)", "nullable": False},
                "mrp_type": {"type": "character varying(2)", "nullable": True},
                "reorder_point": {"type": "numeric", "nullable": True},
                "safety_stock": {"type": "numeric", "nullable": True},
                "procurement_type": {"type": "character varying(1)", "nullable": True},
            },
            "primary_key": ["material_id", "plant"],
            "foreign_keys": [
                {"column": "material_id", "references": "mara.material_id"},
                {"column": "plant", "references": "t001w.plant"},
            ],
        },
        "mbew": {
            "columns": {
                "material_id": {"type": "character varying(18)", "nullable": False},
                "valuation_area": {"type": "character varying(4)", "nullable": False},
                "price_control": {"type": "character varying(1)", "nullable": True},
                "standard_price": {"type": "numeric", "nullable": True},
                "moving_avg_price": {"type": "numeric", "nullable": True},
                "price_unit": {"type": "integer", "nullable": True},
                "currency": {"type": "character varying(3)", "nullable": True},
                "last_updated": {"type": "date", "nullable": True},
            },
            "primary_key": ["material_id", "valuation_area"],
            "foreign_keys": [
                {"column": "material_id", "references": "mara.material_id"},
                {"column": "valuation_area", "references": "t001w.plant"},
            ],
        },
        "ekko": {
            "columns": {
                "purchasing_document": {"type": "character varying(10)", "nullable": False},
                "vendor_id": {"type": "character varying(10)", "nullable": True},
                "plant": {"type": "character varying(4)", "nullable": True},
                "document_date": {"type": "date", "nullable": True},
                "currency": {"type": "character varying(3)", "nullable": True},
            },
            "primary_key": ["purchasing_document"],
            "foreign_keys": [
                {"column": "vendor_id", "references": "lfa1.vendor_id"},
                {"column": "plant", "references": "t001w.plant"},
            ],
        },
        "ekpo": {
            "columns": {
                "purchasing_document": {"type": "character varying(10)", "nullable": False},
                "item_number": {"type": "integer", "nullable": False},
                "material_id": {"type": "character varying(18)", "nullable": True},
                "order_qty": {"type": "numeric", "nullable": True},
                "net_price": {"type": "numeric", "nullable": True},
                "net_value": {"type": "numeric", "nullable": True},
            },
            "primary_key": ["purchasing_document", "item_number"],
            "foreign_keys": [
                {"column": "purchasing_document", "references": "ekko.purchasing_document"},
                {"column": "material_id", "references": "mara.material_id"},
            ],
        },
        "mseg": {
            "columns": {
                "material_document": {"type": "character varying(10)", "nullable": False},
                "item_number": {"type": "integer", "nullable": False},
                "material_id": {"type": "character varying(18)", "nullable": True},
                "plant": {"type": "character varying(4)", "nullable": True},
                "movement_type": {"type": "character varying(3)", "nullable": True},
                "quantity": {"type": "numeric", "nullable": True},
                "posting_date": {"type": "date", "nullable": True},
                "purchasing_document": {"type": "character varying(10)", "nullable": True},
            },
            "primary_key": ["material_document", "item_number"],
            "foreign_keys": [
                {"column": "material_id", "references": "mara.material_id"},
                {"column": "plant", "references": "t001w.plant"},
            ],
        },
    }
}

TABLE_ORDER = list(schema["tables"].keys())


# ---------------------------------------------------------------------
# Create tables (generic - unchanged in spirit from the original db.py)
# ---------------------------------------------------------------------
def create_tables(cursor):
    for table_name in TABLE_ORDER:
        table_data = schema["tables"][table_name]
        cols = []
        for name, col in table_data["columns"].items():
            null_str = "NOT NULL" if not col["nullable"] else ""
            cols.append(f'"{name}" {col["type"]} {null_str}')
        cols_sql = ",\n    ".join(cols)

        pk_sql = ""
        if "primary_key" in table_data:
            pk = ", ".join(f'"{c}"' for c in table_data["primary_key"])
            pk_sql = f",\n    PRIMARY KEY ({pk})"

        fk_sql = ""
        if "foreign_keys" in table_data:
            fks = [
                f'FOREIGN KEY ("{fk["column"]}") REFERENCES "{fk["references"].split(".")[0]}"("{fk["references"].split(".")[1]}")'
                for fk in table_data["foreign_keys"]
            ]
            if fks:
                fk_sql = ",\n    " + ",\n    ".join(fks)

        create_sql = f"""
        CREATE TABLE IF NOT EXISTS "{table_name}" (
            {cols_sql}
            {pk_sql}
            {fk_sql}
        );
        """
        cursor.execute(create_sql)
        print(f"✅ Created table: {table_name}")


# ---------------------------------------------------------------------
# Reset - drops every table this script owns, CASCADE so FK-dependent
# objects go with them. Gated behind RESET_DB=yes or --reset so a bare
# `python db_setup.py` never touches an existing demo by accident.
# ---------------------------------------------------------------------
def reset_database(cursor):
    print("🗑️  Resetting: dropping all tables this script owns...")
    for table_name in reversed(TABLE_ORDER):
        cursor.execute(f'DROP TABLE IF EXISTS "{table_name}" CASCADE;')
    print(f"✅ Dropped {len(TABLE_ORDER)} tables.")
    # For a true "wipe everything in this DB" reset - including any stray
    # objects this script doesn't know about - you could instead run:
    #   DROP SCHEMA public CASCADE; CREATE SCHEMA public;
    # Not used by default: on managed Postgres (RDS etc.) that also drops
    # schema-level grants a normal app user often can't recreate. The
    # table-by-table CASCADE drop above is safer for a shared demo DB.


# ---------------------------------------------------------------------
# Guarantee a minimum on-disk database size, deterministically.
#
# Hand-tuning business-table row counts to land on an exact byte target
# doesn't hold up across environments - actual bytes-per-row shifts with
# Postgres version, TOAST/compression behavior, and whether checksums
# are on. Instead: load the real business data at a sane, fast-to-generate
# size, then measure actual size and top up with a dedicated, clearly-
# labeled padding table until it clears the target.
# ---------------------------------------------------------------------
def _get_db_size_bytes(cursor):
    cursor.execute("SELECT pg_database_size(current_database());")
    return cursor.fetchone()[0]


def pad_database_to_target_size(cursor, target_bytes=TARGET_DB_SIZE_BYTES):
    """
    Tops the database up to at least `target_bytes` using `_db_size_padding`.
    Safe to leave in place - it's inert, has no foreign keys pointing at
    or from it, and none of the demo's real business queries will touch
    it. Drop it with `DROP TABLE "_db_size_padding";` if you'd rather not
    keep it (the DB will shrink back below the target, obviously).
    """
    cursor.execute(f'CREATE TABLE IF NOT EXISTS "{PAD_TABLE_NAME}" (pad_id serial PRIMARY KEY, filler text);')
    # EXTERNAL storage skips TOAST compression, so batch size on disk is
    # predictable instead of shrinking because the filler text happens
    # to compress well.
    cursor.execute(f'ALTER TABLE "{PAD_TABLE_NAME}" ALTER COLUMN filler SET STORAGE EXTERNAL;')

    current_size = _get_db_size_bytes(cursor)
    if current_size >= target_bytes:
        print(f"✅ Database already at {current_size / 1e9:.2f} GB - no padding needed.")
        return

    print(f"📏 Current DB size: {current_size / 1e6:.1f} MB. Padding up to >= {target_bytes / 1e9:.2f} GB...")
    while current_size < target_bytes:
        # os.urandom + base64 is far faster than building each string
        # character-by-character, and base64 output is high-entropy so
        # it won't collapse under TOAST compression even without the
        # EXTERNAL storage setting above.
        batch = [
            (base64.b64encode(os.urandom(PAD_ROW_RANDOM_BYTES)).decode(),)
            for _ in range(PAD_BATCH_SIZE)
        ]
        execute_values(cursor, f'INSERT INTO "{PAD_TABLE_NAME}" (filler) VALUES %s', batch, page_size=1000)
        current_size = _get_db_size_bytes(cursor)
        print(f"   ...{current_size / 1e6:.1f} MB so far")

    print(f"✅ Final database size: {current_size / 1e9:.2f} GB")


# ---------------------------------------------------------------------
# Insert synthetic data
# ---------------------------------------------------------------------
def insert_data():
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM kna1;")
    if cursor.fetchone()[0] > 0:
        print("⏭️  Demo data already present in this database - skipping seed (tables are non-empty). Use --reset to rebuild.")
        pad_database_to_target_size(cursor)
        cursor.close()
        conn.close()
        return

    print("🔗 Connected. Generating synthetic data...")

    # --- Master data ---------------------------------------------------
    customers, customer_regions = [], {}
    for i in range(1, TOTAL_CUSTOMERS + 1):
        cid = f"C{i:05d}"
        country, region = random.choice(REGION_COUNTRIES)
        customers.append((cid, fake.company(), country, fake.city(), fake.postcode()))
        customer_regions[cid] = region

    vendors = [
        (f"V{i:05d}", fake.company(), random.choice(REGION_COUNTRIES)[0], fake.city(), fake.postcode())
        for i in range(1, TOTAL_VENDORS + 1)
    ]

    materials = [(mid, name, unit, group) for mid, name, group, unit in CURATED_MATERIALS]
    for i in range(len(CURATED_MATERIALS) + 1, TOTAL_MATERIALS + 1):
        mid = f"MAT-{i:05d}"
        group = random.choice(RANDOM_MATERIAL_GROUPS)
        unit = random.choice(RANDOM_MATERIAL_UNITS)
        name = f"{fake.word().capitalize()} {random.choice(['Component', 'Part', 'Assembly', 'Fitting', 'Module'])}"
        materials.append((mid, name, unit, group))
    material_ids = [m[0] for m in materials]

    gl_accounts = [(f"{i:010}", fake.bs().title(), random.choice(["A1", "B2", "C3"])) for i in range(100000, 100000 + TOTAL_GL_ACCOUNTS)]
    skb1 = [(gl, random.choice(["1000", "2000", "3000", "4000"]), random.choice(["USD", "EUR", "GBP"])) for gl, _, _ in gl_accounts]

    t001w = [
        ("PL01", "Noida Manufacturing Plant", "Noida", "IND"),
        ("PL02", "Delhi Assembly Plant", "Delhi", "IND"),
        ("PL03", "Pune Fabrication Plant", "Pune", "IND"),
    ]

    print("📦 Inserting master data...")
    execute_values(cursor, 'INSERT INTO kna1 VALUES %s', customers, page_size=1000)
    execute_values(cursor, 'INSERT INTO lfa1 VALUES %s', vendors, page_size=1000)
    execute_values(cursor, 'INSERT INTO mara VALUES %s', materials, page_size=1000)
    execute_values(cursor, 'INSERT INTO ska1 VALUES %s', gl_accounts, page_size=1000)
    execute_values(cursor, 'INSERT INTO skb1 VALUES %s', skb1, page_size=1000)
    execute_values(cursor, 'INSERT INTO t001w VALUES %s', t001w, page_size=1000)

    # --- Core transactional data (sales/delivery/billing/accounting) ---
    vbak, vbap, likp, lips, vbrk, vbrp, bkpf, bseg = [], [], [], [], [], [], [], []
    fiscal_year = 2024
    total_sales_docs = TOTAL_SALES_DOCS
    total_bkpf_docs = TOTAL_BKPF_DOCS

    print(f"🧾 Generating core transactional data ({total_sales_docs:,} sales docs, {total_bkpf_docs:,} accounting docs)...")
    for i in range(1, total_sales_docs + 1):
        sales_doc = f"SD{i:06d}"
        cust = random.choice(customers)[0]
        doc_date = fake.date_between(start_date="-2y", end_date="today")
        total_amt = round(random.uniform(1000, 50000), 2)
        vbak.append((sales_doc, cust, doc_date, total_amt))

        num_items = random.randint(1, 5)
        for item_no in range(1, num_items + 1):
            mat = random.choice(material_ids)
            qty = round(random.uniform(1, 100), 2)
            vbap.append((sales_doc, item_no, mat, qty))

        delivery_no = f"DL{i:06d}"
        delivery_date = doc_date + timedelta(days=random.randint(1, 10))
        likp.append((delivery_no, sales_doc, delivery_date))
        for item_no in range(1, num_items + 1):
            mat = random.choice(material_ids)
            qty = round(random.uniform(1, 100), 2)
            lips.append((delivery_no, item_no, mat, qty))

        billing_no = f"BL{i:06d}"
        billing_date = delivery_date + timedelta(days=random.randint(1, 15))
        vbrk.append((billing_no, sales_doc, billing_date, total_amt))
        for item_no in range(1, num_items + 1):
            mat = random.choice(material_ids)
            qty = round(random.uniform(1, 100), 2)
            vbrp.append((billing_no, item_no, mat, qty))

    for i in range(1, total_bkpf_docs + 1):
        doc_no = f"D{i:07d}"
        company_code = random.choice(["1000", "2000", "3000", "4000"])
        doc_type = random.choice(["SA", "KR", "DR"])
        doc_date = fake.date_between(start_date="-1y", end_date="today")
        posting_date = doc_date + timedelta(days=random.randint(0, 5))
        currency = random.choice(["USD", "EUR", "GBP"])
        ref = fake.uuid4()[:8]
        bkpf.append((doc_no, company_code, fiscal_year, doc_type, doc_date, posting_date, currency, ref))

        num_items = random.randint(2, 5)
        for item_no in range(1, num_items + 1):
            posting_key = random.choice(["01", "50", "40", "31"])
            acct_type = random.choice(["S", "C", "D"])
            if acct_type == "S":
                acct_no = random.choice(gl_accounts)[0]
            elif acct_type == "C":
                acct_no = random.choice(customers)[0]
            else:
                acct_no = random.choice(vendors)[0]
            amount = round(random.uniform(100, 10000), 2)
            tax_code = random.choice(["A1", "B2", "C3"])
            cost_center = f"CC{random.randint(100, 999)}"
            profit_center = f"PC{random.randint(100, 999)}"
            text = fake.sentence(nb_words=6)
            bseg.append((doc_no, item_no, posting_key, acct_type, acct_no, amount, tax_code, cost_center, profit_center, text))

    print("💾 Inserting core transactional records...")
    execute_values(cursor, 'INSERT INTO vbak VALUES %s', vbak, page_size=1000)
    execute_values(cursor, 'INSERT INTO vbap VALUES %s', vbap, page_size=1000)
    execute_values(cursor, 'INSERT INTO likp VALUES %s', likp, page_size=1000)
    execute_values(cursor, 'INSERT INTO lips VALUES %s', lips, page_size=1000)
    execute_values(cursor, 'INSERT INTO vbrk VALUES %s', vbrk, page_size=1000)
    execute_values(cursor, 'INSERT INTO vbrp VALUES %s', vbrp, page_size=1000)
    execute_values(cursor, 'INSERT INTO bkpf VALUES %s', bkpf, page_size=1000)
    execute_values(cursor, 'INSERT INTO bseg VALUES %s', bseg, page_size=1000)

    # --- vbak_region: region-wise order breakdown by material -----------
    # order_value is computed here (qty x a synthetic unit price) since
    # vbap has no net_value column to pull from. Duplicate (sales_doc,
    # material_id) lines within one order are aggregated to satisfy the
    # table's composite primary key.
    print("🌍 Building region-wise order breakdown (vbak_region)...")
    vbak_meta = {sd: (cust, doc_date) for sd, cust, doc_date, _ in vbak}
    agg = {}
    for sales_doc, item_no, mat_id, qty in vbap:
        cust, doc_date = vbak_meta[sales_doc]
        region = customer_regions.get(cust, "APAC")
        unit_price = round(random.uniform(10, 500), 2)
        value = round(qty * unit_price, 2)
        key = (sales_doc, mat_id)
        if key in agg:
            prev_qty, prev_val, _, _, _ = agg[key]
            agg[key] = (prev_qty + qty, prev_val + value, cust, region, doc_date)
        else:
            agg[key] = (qty, value, cust, region, doc_date)

    vbak_region_rows = [
        (sd, cust, region, doc_date, mat, round(qty, 2), round(val, 2))
        for (sd, mat), (qty, val, cust, region, doc_date) in agg.items()
    ]
    execute_values(cursor, 'INSERT INTO vbak_region VALUES %s', vbak_region_rows, page_size=1000)

    # --- Plant/valuation/purchasing/movement extension tables -----------
    print("🏭 Generating plant, valuation, purchasing and movement data...")
    marc_rows = []
    for mid in material_ids:
        for plant in PLANTS:
            if random.random() < 0.6:
                marc_rows.append((
                    mid, plant, random.choice(["PD", "VB", "V1"]),
                    round(random.uniform(100, 500)), round(random.uniform(50, 200)),
                    random.choice(["E", "F"]),
                ))

    mbew_rows = []
    for mid in material_ids:
        for plant in PLANTS:
            if random.random() < 0.6:
                mbew_rows.append((
                    mid, plant, random.choice(["S", "V"]),
                    round(random.uniform(10, 460), 2), round(random.uniform(10, 460), 2),
                    1, "USD", fake.date_between(start_date="-60d", end_date="today"),
                ))

    vendor_ids = [v[0] for v in vendors]
    ekko_rows = []
    for i in range(1, TOTAL_EKKO + 1):
        ekko_rows.append((
            f"PO{i:08d}", random.choice(vendor_ids), random.choice(PLANTS),
            fake.date_between(start_date="-180d", end_date="today"),
            random.choice(["USD", "EUR", "GBP"]),
        ))
    po_numbers = [r[0] for r in ekko_rows]

    ekpo_rows = []
    for po in po_numbers:
        for item_num in (1, 2):
            mid = random.choice(material_ids)
            qty = round(random.uniform(50, 950))
            price = round(random.uniform(10, 410), 2)
            ekpo_rows.append((po, item_num, mid, qty, price, round(qty * price, 2)))

    marc_pairs = [(r[0], r[1]) for r in marc_rows]
    mseg_rows = []
    for i in range(1, TOTAL_MSEG + 1):
        mid, plant = random.choice(marc_pairs)
        mtype = random.choice(["101", "261", "601"])
        po = random.choice(po_numbers) if mtype == "101" else None
        mseg_rows.append((
            f"MD{i:08d}", 1, mid, plant, mtype,
            round(random.uniform(10, 510)),
            fake.date_between(start_date="-120d", end_date="today"),
            po,
        ))

    print("💾 Inserting extension tables...")
    execute_values(cursor, 'INSERT INTO marc VALUES %s', marc_rows, page_size=1000)
    execute_values(cursor, 'INSERT INTO mbew VALUES %s', mbew_rows, page_size=1000)
    execute_values(cursor, 'INSERT INTO ekko VALUES %s', ekko_rows, page_size=1000)
    execute_values(cursor, 'INSERT INTO ekpo VALUES %s', ekpo_rows, page_size=1000)
    execute_values(cursor, 'INSERT INTO mseg VALUES %s', mseg_rows, page_size=1000)

    print("🎉 Synthetic SAP data (20 tables) inserted successfully!")

    pad_database_to_target_size(cursor)

    cursor.close()
    conn.close()


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------
if __name__ == "__main__":
    reset_requested = os.getenv("RESET_DB", "").strip().lower() in ("1", "true", "yes") or "--reset" in sys.argv

    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True
    cur = conn.cursor()

    if reset_requested:
        reset_database(cur)

    create_tables(cur)
    cur.close()
    conn.close()
    insert_data()
