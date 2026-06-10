# import psycopg2
# import os
# import json
# from dotenv import load_dotenv

# # Load environment variables
# load_dotenv()

# DB_CONFIG = {
#     "host": os.getenv("PGHOST"),
#     "port": os.getenv("PGPORT"),
#     "dbname": os.getenv("PGDATABASE"),
#     "user": os.getenv("PGUSER"),
#     "password": os.getenv("PGPASSWORD")
# }

# # === Full SAP-style schema ===
# schema = {
#     "tables": {
#         "bkpf": {
#             "comment": "Accounting document header table (contains general information for each financial document).",
#             "columns": {
#                 "document_number": {"type": "character varying(10)", "nullable": False, "comment": "Unique accounting document number (header identifier)."},
#                 "company_code": {"type": "character varying(4)", "nullable": True, "comment": "Company code to which the document belongs."},
#                 "fiscal_year": {"type": "integer", "nullable": True, "comment": "Fiscal year in which the document is posted."},
#                 "document_type": {"type": "character varying(2)", "nullable": True, "comment": "SAP document type (e.g., SA, KR, DR)."},
#                 "document_date": {"type": "date", "nullable": True, "comment": "Date on which the document was created."},
#                 "posting_date": {"type": "date", "nullable": True, "comment": "Date the document was posted to accounting."},
#                 "currency": {"type": "character varying(3)", "nullable": True, "comment": "Currency used in the document."},
#                 "reference": {"type": "text", "nullable": True, "comment": "Reference text or external document number."}
#             },
#             "primary_key": ["document_number"],
#             "foreign_keys": []
#         },
#         "bseg": {
#             "comment": "Accounting document line items table (contains detailed posting information per document).",
#             "columns": {
#                 "item_id": {"type": "integer", "nullable": False, "comment": "Unique line item identifier within an accounting document."},
#                 "document_number": {"type": "character varying(10)", "nullable": True, "comment": "Reference to accounting document header (BKPF)."},
#                 "posting_key": {"type": "character varying(2)", "nullable": True, "comment": "Posting key defining debit/credit and account type."},
#                 "account_type": {"type": "character varying(1)", "nullable": True, "comment": "Account type (C=Customer, D=Vendor, S=GL)."},
#                 "account_number": {"type": "character varying(10)", "nullable": True, "comment": "Account number (customer/vendor/GL)."},
#                 "amount": {"type": "numeric", "nullable": True, "comment": "Transaction amount for this line item."},
#                 "tax_code": {"type": "character varying(2)", "nullable": True, "comment": "Tax code applied to this posting."},
#                 "cost_center": {"type": "character varying(10)", "nullable": True, "comment": "Cost center associated with the posting."},
#                 "profit_center": {"type": "character varying(10)", "nullable": True, "comment": "Profit center associated with the posting."},
#                 "text": {"type": "text", "nullable": True, "comment": "Line item text or description."}
#             },
#             "primary_key": ["item_id"],
#             "foreign_keys": [{"column": "document_number", "references": "bkpf.document_number"}]
#         },
#         "kna1": {
#             "comment": "Customer master (general data).",
#             "columns": {
#                 "customer_id": {"type": "character varying(10)", "nullable": False, "comment": "Unique customer identifier."},
#                 "name": {"type": "character varying(100)", "nullable": True, "comment": "Customer full name."},
#                 "country": {"type": "character varying(3)", "nullable": True, "comment": "Country code of the customer."},
#                 "city": {"type": "character varying(50)", "nullable": True, "comment": "City of the customer."},
#                 "postal_code": {"type": "character varying(10)", "nullable": True, "comment": "Postal code of the customer."}
#             },
#             "primary_key": ["customer_id"],
#             "foreign_keys": []
#         },
#         "lfa1": {
#             "comment": "Vendor master (general data).",
#             "columns": {
#                 "vendor_id": {"type": "character varying(10)", "nullable": False, "comment": "Unique vendor identifier."},
#                 "name": {"type": "character varying(100)", "nullable": True, "comment": "Vendor name."},
#                 "country": {"type": "character varying(3)", "nullable": True, "comment": "Country code of the vendor."},
#                 "city": {"type": "character varying(50)", "nullable": True, "comment": "City of the vendor."},
#                 "postal_code": {"type": "character varying(10)", "nullable": True, "comment": "Postal code of the vendor."}
#             },
#             "primary_key": ["vendor_id"],
#             "foreign_keys": []
#         },
#         "mara": {
#             "comment": "Material master (general data).",
#             "columns": {
#                 "material_id": {"type": "character varying(18)", "nullable": False, "comment": "Unique material identifier."},
#                 "description": {"type": "character varying(100)", "nullable": True, "comment": "Material description."},
#                 "base_unit": {"type": "character varying(3)", "nullable": True, "comment": "Base unit of measure for the material."},
#                 "material_group": {"type": "character varying(4)", "nullable": True, "comment": "Material group classification."}
#             },
#             "primary_key": ["material_id"],
#             "foreign_keys": []
#         },
#         "vbak": {
#             "comment": "Sales document header data.",
#             "columns": {
#                 "sales_document": {"type": "character varying(10)", "nullable": False, "comment": "Unique sales document number."},
#                 "customer_id": {"type": "character varying(10)", "nullable": True, "comment": "Customer placing the order."},
#                 "document_date": {"type": "date", "nullable": True, "comment": "Sales document creation date."},
#                 "total_amount": {"type": "numeric", "nullable": True, "comment": "Total sales document amount."}
#             },
#             "primary_key": ["sales_document"],
#             "foreign_keys": [{"column": "customer_id", "references": "kna1.customer_id"}]
#         },
#         "vbap": {
#             "comment": "Sales document item data.",
#             "columns": {
#                 "item_number": {"type": "integer", "nullable": False, "comment": "Item number within the sales document."},
#                 "sales_document": {"type": "character varying(10)", "nullable": True, "comment": "Reference to sales document (VBAK)."},
#                 "material_id": {"type": "character varying(18)", "nullable": True, "comment": "Material number."},
#                 "quantity": {"type": "numeric", "nullable": True, "comment": "Quantity ordered."}
#             },
#             "primary_key": ["item_number"],
#             "foreign_keys": [
#                 {"column": "sales_document", "references": "vbak.sales_document"},
#                 {"column": "material_id", "references": "mara.material_id"}
#             ]
#         },
#         "likp": {
#             "comment": "Delivery document header data.",
#             "columns": {
#                 "delivery_number": {"type": "character varying(10)", "nullable": False, "comment": "Unique delivery document number."},
#                 "sales_document": {"type": "character varying(10)", "nullable": True, "comment": "Linked sales document (VBAK)."},
#                 "delivery_date": {"type": "date", "nullable": True, "comment": "Date of delivery."}
#             },
#             "primary_key": ["delivery_number"],
#             "foreign_keys": [{"column": "sales_document", "references": "vbak.sales_document"}]
#         },
#         "lips": {
#             "comment": "Delivery document item data.",
#             "columns": {
#                 "item_number": {"type": "integer", "nullable": False, "comment": "Item number in delivery document."},
#                 "delivery_number": {"type": "character varying(10)", "nullable": True, "comment": "Reference to delivery document (LIKP)."},
#                 "material_id": {"type": "character varying(18)", "nullable": True, "comment": "Material being delivered."},
#                 "quantity": {"type": "numeric", "nullable": True, "comment": "Delivered quantity."}
#             },
#             "primary_key": ["item_number"],
#             "foreign_keys": [
#                 {"column": "delivery_number", "references": "likp.delivery_number"},
#                 {"column": "material_id", "references": "mara.material_id"}
#             ]
#         },
#         "vbrk": {
#             "comment": "Billing document header data.",
#             "columns": {
#                 "billing_number": {"type": "character varying(10)", "nullable": False, "comment": "Unique billing document number."},
#                 "sales_document": {"type": "character varying(10)", "nullable": True, "comment": "Linked sales document (VBAK)."},
#                 "billing_date": {"type": "date", "nullable": True, "comment": "Date of billing."},
#                 "total_amount": {"type": "numeric", "nullable": True, "comment": "Total billing amount."}
#             },
#             "primary_key": ["billing_number"],
#             "foreign_keys": [{"column": "sales_document", "references": "vbak.sales_document"}]
#         },
#         "vbrp": {
#             "comment": "Billing document item data.",
#             "columns": {
#                 "item_number": {"type": "integer", "nullable": False, "comment": "Item number in billing document."},
#                 "billing_number": {"type": "character varying(10)", "nullable": True, "comment": "Reference to billing document (VBRK)."},
#                 "material_id": {"type": "character varying(18)", "nullable": True, "comment": "Material being billed."},
#                 "quantity": {"type": "numeric", "nullable": True, "comment": "Billed quantity."}
#             },
#             "primary_key": ["item_number"],
#             "foreign_keys": [
#                 {"column": "billing_number", "references": "vbrk.billing_number"},
#                 {"column": "material_id", "references": "mara.material_id"}
#             ]
#         },
#         "ska1": {
#             "comment": "G/L account master (chart of accounts).",
#             "columns": {
#                 "gl_account": {"type": "character varying(10)", "nullable": False, "comment": "General ledger account number."},
#                 "account_name": {"type": "character varying(100)", "nullable": True, "comment": "Account description."},
#                 "account_group": {"type": "character varying(4)", "nullable": True, "comment": "G/L account group."}
#             },
#             "primary_key": ["gl_account"],
#             "foreign_keys": []
#         },
#         "skb1": {
#             "comment": "G/L account master (company code-specific data).",
#             "columns": {
#                 "gl_account": {"type": "character varying(10)", "nullable": False, "comment": "General ledger account number."},
#                 "company_code": {"type": "character varying(4)", "nullable": False, "comment": "Company code to which the G/L account belongs."},
#                 "currency": {"type": "character varying(3)", "nullable": True, "comment": "Account currency."}
#             },
#             "primary_key": ["gl_account", "company_code"],
#             "foreign_keys": [{"column": "gl_account", "references": "ska1.gl_account"}]
#         }
#     }
# }


# def create_tables(schema, cursor):
#     for table_name, table_data in schema["tables"].items():
#         cols = []
#         for name, col in table_data["columns"].items():
#             null_str = "NOT NULL" if not col["nullable"] else ""
#             cols.append(f'"{name}" {col["type"]} {null_str}')
#         cols_sql = ",\n    ".join(cols)

#         pk_sql = ""
#         if "primary_key" in table_data:
#             pk = ", ".join(f'"{c}"' for c in table_data["primary_key"])
#             pk_sql = f",\n    PRIMARY KEY ({pk})"

#         fk_sql = ""
#         if "foreign_keys" in table_data:
#             fks = [
#                 f'FOREIGN KEY ("{fk["column"]}") REFERENCES "{fk["references"].split(".")[0]}"("{fk["references"].split(".")[1]}")'
#                 for fk in table_data["foreign_keys"]
#             ]
#             if fks:
#                 fk_sql = ",\n    " + ",\n    ".join(fks)

#         create_sql = f"""
#         CREATE TABLE IF NOT EXISTS "{table_name}" (
#             {cols_sql}
#             {pk_sql}
#             {fk_sql}
#         );
#         """
#         cursor.execute(create_sql)
#         print(f"✅ Created table: {table_name}")

#         if "comment" in table_data:
#             cursor.execute(f'COMMENT ON TABLE "{table_name}" IS %s;', (table_data["comment"],))
#         for col, cdata in table_data["columns"].items():
#             if "comment" in cdata:
#                 cursor.execute(f'COMMENT ON COLUMN "{table_name}"."{col}" IS %s;', (cdata["comment"],))


# def main():
#     try:
#         conn = psycopg2.connect(**DB_CONFIG)
#         conn.autocommit = True
#         cursor = conn.cursor()
#         print(f"🔗 Connected to PostgreSQL database: {DB_CONFIG['dbname']}")
#         create_tables(schema, cursor)
#         cursor.close()
#         conn.close()
#         print("🎉 All tables created successfully!")
#     except Exception as e:
#         print("❌ Error:", e)


# if __name__ == "__main__":
#     main()



import psycopg2
import os
import random
from faker import Faker
from datetime import timedelta
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

#DB_CONFIG = {
#    "host": os.getenv("PGHOST"),
#    "port": os.getenv("PGPORT"),
#    "dbname": os.getenv("PGDATABASE"),
#    "user": os.getenv("PGUSER"),
#    "password": os.getenv("PGPASSWORD")
#}
# Hardcoded connection for databrige_db
DB_CONFIG = {
    "host": "db",             # Connects to the Docker container
    "port": "5432",
    "dbname": "databrige_db", # Your target database
    "user": "saarthi",        # Your user from yml
    "password": "password" 
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
# Insert synthetic data
# ---------------------------------------------------------------------
def insert_data():
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True
    cursor = conn.cursor()
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
