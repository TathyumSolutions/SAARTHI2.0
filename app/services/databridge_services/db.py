"""
Seeds a standalone SAP-style demo dataset into an EXTERNAL Postgres
database - one that lives outside this app's own Docker footprint,
exactly like a real customer's SAP system would. This script never
touches the app's own databases and has no fallback to any of them: it
only ever connects to whatever DATABRIDGE_TARGET_* env vars point at,
same as app/routes/database_routes.py's run_agentic_process() sets when
it invokes this as a subprocess using a registered Database Connection's
credentials. Run standalone (e.g. `python db.py`), those env vars must be
set explicitly first - there is no default host to fall back to.
"""
import sys
import psycopg2
import os
import random
from faker import Faker
from datetime import timedelta
from dotenv import load_dotenv

# Load environment variables
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
# UPDATED SCHEMA with proper composite primary keys (SAP-style)
# ---------------------------------------------------------------------
schema = {
    "tables": {
        "bkpf": {
            "columns": {
                "document_number": {"type": "character varying(10)", "nullable": False},
                "company_code": {"type": "character varying(4)", "nullable": True},
                "fiscal_year": {"type": "integer", "nullable": True},
                "document_type": {"type": "character varying(2)", "nullable": True},
                "document_date": {"type": "date", "nullable": True},
                "posting_date": {"type": "date", "nullable": True},
                "currency": {"type": "character varying(3)", "nullable": True},
                "reference": {"type": "text", "nullable": True}
            },
            "primary_key": ["document_number"]
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
                "text": {"type": "text", "nullable": True}
            },
            "primary_key": ["document_number", "item_number"],
            "foreign_keys": [{"column": "document_number", "references": "bkpf.document_number"}]
        },
        "kna1": {
            "columns": {
                "customer_id": {"type": "character varying(10)", "nullable": False},
                "name": {"type": "character varying(100)", "nullable": True},
                "country": {"type": "character varying(3)", "nullable": True},
                "city": {"type": "character varying(50)", "nullable": True},
                "postal_code": {"type": "character varying(10)", "nullable": True}
            },
            "primary_key": ["customer_id"]
        },
        "lfa1": {
            "columns": {
                "vendor_id": {"type": "character varying(10)", "nullable": False},
                "name": {"type": "character varying(100)", "nullable": True},
                "country": {"type": "character varying(3)", "nullable": True},
                "city": {"type": "character varying(50)", "nullable": True},
                "postal_code": {"type": "character varying(10)", "nullable": True}
            },
            "primary_key": ["vendor_id"]
        },
        "mara": {
            "columns": {
                "material_id": {"type": "character varying(18)", "nullable": False},
                "description": {"type": "character varying(100)", "nullable": True},
                "base_unit": {"type": "character varying(3)", "nullable": True},
                "material_group": {"type": "character varying(4)", "nullable": True}
            },
            "primary_key": ["material_id"]
        },
        "ekko": {
            "columns": {
                "purchase_document": {"type": "character varying(10)", "nullable": False},
                "vendor_id": {"type": "character varying(10)", "nullable": True},
                "company_code": {"type": "character varying(4)", "nullable": True},
                "document_date": {"type": "date", "nullable": True},
                "currency": {"type": "character varying(3)", "nullable": True}
            },
            "primary_key": ["purchase_document"],
            "foreign_keys": [{"column": "vendor_id", "references": "lfa1.vendor_id"}]
        },
        "ekpo": {
            "columns": {
                "purchase_document": {"type": "character varying(10)", "nullable": False},
                "item_number": {"type": "integer", "nullable": False},
                "material_id": {"type": "character varying(18)", "nullable": True},
                "plant": {"type": "character varying(4)", "nullable": True},
                "quantity": {"type": "numeric", "nullable": True},
                "net_price": {"type": "numeric", "nullable": True},
                "net_value": {"type": "numeric", "nullable": True}
            },
            "primary_key": ["purchase_document", "item_number"],
            "foreign_keys": [
                {"column": "purchase_document", "references": "ekko.purchase_document"},
                {"column": "material_id", "references": "mara.material_id"}
            ]
        },
        "vbak": {
            "columns": {
                "sales_document": {"type": "character varying(10)", "nullable": False},
                "customer_id": {"type": "character varying(10)", "nullable": True},
                "document_date": {"type": "date", "nullable": True},
                "total_amount": {"type": "numeric", "nullable": True}
            },
            "primary_key": ["sales_document"],
            "foreign_keys": [{"column": "customer_id", "references": "kna1.customer_id"}]
        },
        "vbap": {
            "columns": {
                "sales_document": {"type": "character varying(10)", "nullable": False},
                "item_number": {"type": "integer", "nullable": False},
                "material_id": {"type": "character varying(18)", "nullable": True},
                "quantity": {"type": "numeric", "nullable": True}
            },
            "primary_key": ["sales_document", "item_number"],
            "foreign_keys": [
                {"column": "sales_document", "references": "vbak.sales_document"},
                {"column": "material_id", "references": "mara.material_id"}
            ]
        },
        "likp": {
            "columns": {
                "delivery_number": {"type": "character varying(10)", "nullable": False},
                "sales_document": {"type": "character varying(10)", "nullable": True},
                "delivery_date": {"type": "date", "nullable": True}
            },
            "primary_key": ["delivery_number"],
            "foreign_keys": [{"column": "sales_document", "references": "vbak.sales_document"}]
        },
        "lips": {
            "columns": {
                "delivery_number": {"type": "character varying(10)", "nullable": False},
                "item_number": {"type": "integer", "nullable": False},
                "material_id": {"type": "character varying(18)", "nullable": True},
                "quantity": {"type": "numeric", "nullable": True}
            },
            "primary_key": ["delivery_number", "item_number"],
            "foreign_keys": [
                {"column": "delivery_number", "references": "likp.delivery_number"},
                {"column": "material_id", "references": "mara.material_id"}
            ]
        },
        "vbrk": {
            "columns": {
                "billing_number": {"type": "character varying(10)", "nullable": False},
                "sales_document": {"type": "character varying(10)", "nullable": True},
                "billing_date": {"type": "date", "nullable": True},
                "total_amount": {"type": "numeric", "nullable": True}
            },
            "primary_key": ["billing_number"],
            "foreign_keys": [{"column": "sales_document", "references": "vbak.sales_document"}]
        },
        "vbrp": {
            "columns": {
                "billing_number": {"type": "character varying(10)", "nullable": False},
                "item_number": {"type": "integer", "nullable": False},
                "material_id": {"type": "character varying(18)", "nullable": True},
                "quantity": {"type": "numeric", "nullable": True}
            },
            "primary_key": ["billing_number", "item_number"],
            "foreign_keys": [
                {"column": "billing_number", "references": "vbrk.billing_number"},
                {"column": "material_id", "references": "mara.material_id"}
            ]
        },
        "ska1": {
            "columns": {
                "gl_account": {"type": "character varying(10)", "nullable": False},
                "account_name": {"type": "character varying(100)", "nullable": True},
                "account_group": {"type": "character varying(4)", "nullable": True}
            },
            "primary_key": ["gl_account"]
        },
        "skb1": {
            "columns": {
                "gl_account": {"type": "character varying(10)", "nullable": False},
                "company_code": {"type": "character varying(4)", "nullable": False},
                "currency": {"type": "character varying(3)", "nullable": True}
            },
            "primary_key": ["gl_account", "company_code"],
            "foreign_keys": [{"column": "gl_account", "references": "ska1.gl_account"}]
        }
    }
}

# ---------------------------------------------------------------------
# Function to create tables
# ---------------------------------------------------------------------
def create_tables(cursor):
    for table_name, table_data in schema["tables"].items():
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
# Purchase order (ekko/ekpo) data - procurement side of the demo dataset,
# mirroring the sales-side vbak/vbap generation below. Split into its own
# function so it can be called both on a fresh seed and, independently,
# against a database that already has master/transactional data but
# predates ekko/ekpo (see the master_data_present branch in insert_data).
# ---------------------------------------------------------------------
def _seed_purchase_orders(cursor, vendor_ids, material_ids, total_purchase_docs=3000):
    cursor.execute("SELECT COUNT(*) FROM ekko;")
    if cursor.fetchone()[0] > 0:
        print("⏭️  Purchase order demo data already present - skipping.")
        return
    if not vendor_ids or not material_ids:
        print("⚠️  No vendors/materials available - skipping purchase order seed.")
        return

    print("🧾 Generating purchase order data...")
    ekko, ekpo = [], []
    for i in range(1, total_purchase_docs + 1):
        purchase_doc = f"PO{str(i).zfill(6)}"
        vendor = random.choice(vendor_ids)
        company_code = random.choice(['1000', '2000', '3000', '4000'])
        doc_date = fake.date_between(start_date="-2y", end_date="today")
        currency = random.choice(['USD', 'EUR', 'GBP'])
        ekko.append((purchase_doc, vendor, company_code, doc_date, currency))

        num_items = random.randint(1, 5)
        for item_no in range(1, num_items + 1):
            material = random.choice(material_ids)
            plant = random.choice(['1000', '2000', '3000'])
            quantity = round(random.uniform(1, 500), 2)
            net_price = round(random.uniform(10, 5000), 2)
            net_value = round(quantity * net_price, 2)
            ekpo.append((purchase_doc, item_no, material, plant, quantity, net_price, net_value))

    print("💾 Inserting purchase order records...")
    cursor.executemany('INSERT INTO ekko VALUES (%s,%s,%s,%s,%s);', ekko)
    cursor.executemany('INSERT INTO ekpo VALUES (%s,%s,%s,%s,%s,%s,%s);', ekpo)
    print(f"🎉 Inserted {len(ekko)} purchase orders / {len(ekpo)} purchase order items!")


# ---------------------------------------------------------------------
# Insert synthetic data
# ---------------------------------------------------------------------
def insert_data():
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True
    cursor = conn.cursor()

    # Re-running this script against an already-seeded database used to
    # crash partway through with a primary-key UniqueViolation (no
    # ON CONFLICT / truncate guard). Skip cleanly instead - this is a
    # one-time seed, not something meant to accumulate duplicate rows.
    #
    # Checked independently of the master/other-transactional skip below:
    # a database seeded before ekko/ekpo (purchase orders) existed in this
    # schema already has non-empty kna1, which would otherwise skip the
    # whole function and leave ekko/ekpo permanently empty even after
    # re-running this script - exactly the "ekpo join returns 0 rows"
    # symptom this script exists to prevent.
    cursor.execute("SELECT COUNT(*) FROM kna1;")
    master_data_present = cursor.fetchone()[0] > 0

    if master_data_present:
        print("⏭️  Master/transactional demo data already present - skipping that part of the seed.")
        cursor.execute("SELECT vendor_id FROM lfa1;")
        vendor_ids = [row[0] for row in cursor.fetchall()]
        cursor.execute("SELECT material_id FROM mara;")
        material_ids = [row[0] for row in cursor.fetchall()]
        _seed_purchase_orders(cursor, vendor_ids, material_ids)
        cursor.close()
        conn.close()
        return

    print("🔗 Connected. Generating synthetic data...")

    # --- Master data ---
    customers = [(f"C{str(i).zfill(4)}", fake.company(), fake.country_code(), fake.city(), fake.postcode()) for i in range(1, 501)]
    vendors = [(f"V{str(i).zfill(4)}", fake.company(), fake.country_code(), fake.city(), fake.postcode()) for i in range(1, 301)]
    materials = [(f"M{str(i).zfill(5)}", fake.word().capitalize(), random.choice(['PC','KG','EA','L']),
                  random.choice(['1000','2000','3000','4000'])) for i in range(1, 1001)]
    gl_accounts = [(f"{i:010}", fake.bs().title(), random.choice(['1000','2000','3000'])) for i in range(100000, 100500)]
    skb1 = [(gl, random.choice(['1000','2000','3000','4000']), random.choice(['USD','EUR','GBP'])) for gl,_,_ in gl_accounts]

    print("📦 Inserting master data...")
    cursor.executemany('INSERT INTO kna1 VALUES (%s,%s,%s,%s,%s);', customers)
    cursor.executemany('INSERT INTO lfa1 VALUES (%s,%s,%s,%s,%s);', vendors)
    cursor.executemany('INSERT INTO mara VALUES (%s,%s,%s,%s);', materials)
    cursor.executemany('INSERT INTO ska1 VALUES (%s,%s,%s);', gl_accounts)
    cursor.executemany('INSERT INTO skb1 VALUES (%s,%s,%s);', skb1)

    # --- Transactional data ---
    vbak, vbap, likp, lips, vbrk, vbrp, bkpf, bseg = [], [], [], [], [], [], [], []
    fiscal_year = 2024

    total_sales_docs = 5000
    total_bkpf_docs = 2000

    print("🧾 Generating transactional data...")

    for i in range(1, total_sales_docs + 1):
        sales_doc = f"SD{str(i).zfill(6)}"
        cust = random.choice(customers)[0]
        doc_date = fake.date_between(start_date="-2y", end_date="today")
        total_amt = round(random.uniform(1000, 50000), 2)
        vbak.append((sales_doc, cust, doc_date, total_amt))

        num_items = random.randint(1, 5)
        for item_no in range(1, num_items + 1):
            mat = random.choice(materials)[0]
            qty = round(random.uniform(1, 100), 2)
            vbap.append((sales_doc, item_no, mat, qty))

        delivery_no = f"DL{str(i).zfill(6)}"
        delivery_date = doc_date + timedelta(days=random.randint(1, 10))
        likp.append((delivery_no, sales_doc, delivery_date))
        for item_no in range(1, num_items + 1):
            mat = random.choice(materials)[0]
            qty = round(random.uniform(1, 100), 2)
            lips.append((delivery_no, item_no, mat, qty))

        billing_no = f"BL{str(i).zfill(6)}"
        billing_date = delivery_date + timedelta(days=random.randint(1, 15))
        vbrk.append((billing_no, sales_doc, billing_date, total_amt))
        for item_no in range(1, num_items + 1):
            mat = random.choice(materials)[0]
            qty = round(random.uniform(1, 100), 2)
            vbrp.append((billing_no, item_no, mat, qty))

    for i in range(1, total_bkpf_docs + 1):
        doc_no = f"D{str(i).zfill(7)}"
        company_code = random.choice(['1000','2000','3000','4000'])
        doc_type = random.choice(['SA','KR','DR'])
        doc_date = fake.date_between(start_date="-1y", end_date="today")
        posting_date = doc_date + timedelta(days=random.randint(0,5))
        currency = random.choice(['USD','EUR','GBP'])
        ref = fake.uuid4()[:8]
        bkpf.append((doc_no, company_code, fiscal_year, doc_type, doc_date, posting_date, currency, ref))

        num_items = random.randint(2,5)
        for item_no in range(1, num_items + 1):
            posting_key = random.choice(['01','50','40','31'])
            acct_type = random.choice(['S','C','D'])
            if acct_type == 'S':
                acct_no = random.choice(gl_accounts)[0]
            elif acct_type == 'C':
                acct_no = random.choice(customers)[0]
            else:
                acct_no = random.choice(vendors)[0]
            amount = round(random.uniform(100, 10000), 2)
            tax_code = random.choice(['A1','B2','C3'])
            cost_center = f"CC{random.randint(100,999)}"
            profit_center = f"PC{random.randint(100,999)}"
            text = fake.sentence(nb_words=6)
            bseg.append((doc_no, item_no, posting_key, acct_type, acct_no, amount, tax_code, cost_center, profit_center, text))

    print("💾 Inserting transactional records...")

    cursor.executemany('INSERT INTO vbak VALUES (%s,%s,%s,%s);', vbak)
    cursor.executemany('INSERT INTO vbap VALUES (%s,%s,%s,%s);', vbap)
    cursor.executemany('INSERT INTO likp VALUES (%s,%s,%s);', likp)
    cursor.executemany('INSERT INTO lips VALUES (%s,%s,%s,%s);', lips)
    cursor.executemany('INSERT INTO vbrk VALUES (%s,%s,%s,%s);', vbrk)
    cursor.executemany('INSERT INTO vbrp VALUES (%s,%s,%s,%s);', vbrp)
    cursor.executemany('INSERT INTO bkpf VALUES (%s,%s,%s,%s,%s,%s,%s,%s);', bkpf)
    cursor.executemany('INSERT INTO bseg VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s);', bseg)

    print("🎉 Synthetic SAP data inserted successfully!")

    _seed_purchase_orders(cursor, [v[0] for v in vendors], [m[0] for m in materials])

    cursor.close()
    conn.close()

# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------
if __name__ == "__main__":
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True
    cur = conn.cursor()
    create_tables(cur)
    cur.close()
    conn.close()
    insert_data()
