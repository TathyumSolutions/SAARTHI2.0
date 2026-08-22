# Lending Demo Data Set (NBFC-style)

A self-contained, synthetic NBFC/lending-company demo data set for exercising
Saarthi end-to-end across all of its connector types: a Postgres database,
Excel reference tables, unstructured policy documents, and a validation API.
Everything here is synthetic - names, PAN/Aadhaar-shaped identifiers, phone
numbers, and financial figures are randomly generated in the right *format*
and are not real people or real regulatory text.

```
demo_lending/
├── db_lending.py                 # schema + Faker-based data generator -> Postgres
├── generate_excel_reference.py   # 4 "external" Excel reference workbooks
├── generate_guideline_docs.py    # 5 NBFC policy documents (.docx)
├── validation_api.py             # stub PAN/GSTIN/Aadhaar + credit bureau API
└── output/
    ├── excel/                    # generated workbooks
    └── guidelines/                # generated policy documents
```

## 1. The database (`db_lending.py`)

Provisions its own Postgres database, `lending_demo_db`, independent of
Saarthi's own `saarthi_core_db` / `saarthi_resources_db` / `saarthi_workspace_db`
(see `config/config.py`) - point Saarthi's UI at it afterwards as one more
"Database Connection" data source.

### Schema

| Table                    | What it holds                                                              |
|---------------------------|-----------------------------------------------------------------------------|
| `branches`                | Branch network (city/state/region)                                        |
| `employees`               | Branch staff (Branch Manager, Credit Analyst, Relationship Manager, ...)   |
| `agents`                  | Empanelled DSAs/agents and their commission rate                          |
| `loan_products`           | Product catalogue (Personal, Gold, Vehicle, MSME, LAP, Home, ...) with rate/tenure bands |
| `customers`               | Borrower KYC: name, PAN, masked Aadhaar, income, CIBIL score, address       |
| `loan_applications`       | Application -> underwriting decision                                       |
| `loans`                   | Sanctioned/disbursed loan accounts, EMI, status, current DPD, NPA flag      |
| `repayment_schedule`      | Per-installment amortization schedule (the largest table)                  |
| `collections`             | Actual receipts against the schedule (principal/interest/penalty split)    |
| `payables`                | Agent commission, insurance premium, vendor/branch payables                |
| `npa_classification`      | DPD-bucket / asset-classification / provisioning snapshot                  |
| `credit_bureau_records`   | Per-customer bureau score records (CIBIL, Experian, Equifax, CRIF)          |
| `transactions_ledger`     | Disbursement and processing-fee ledger entries                            |

### Data generation approach

- Indian names/addresses via Faker's `en_IN` locale; PAN/Aadhaar/mobile
  numbers are generated in valid *format* only (`gen_pan`, `gen_aadhaar_masked`,
  `gen_mobile` in `db_lending.py`).
- Loan pricing, tenure bands and processing fees per product are modelled on
  a typical Indian NBFC catalogue (`LOAN_PRODUCTS`).
- Repayment behaviour is a 2-state Markov chain per loan ("current" <->
  "delinquent") rather than independent per-month coin flips
  (`DELINQUENCY_PARAMS`) - this is what makes delinquency *sticky*, matching
  real portfolios, and is what drives realistic 90+ DPD NPA formation
  instead of noise that mostly self-cures. A loan's current DPD is the
  length of its *unbroken trailing* streak of unresolved installments, not
  its worst historical moment - i.e. a borrower who caught up is "current"
  again, matching how real NPA/DPD fields work.
- Bulk loading uses Postgres `COPY` via a small buffered `CopyWriter` (not
  row-by-row `INSERT`), batching ~50k rows per flush - this is what makes
  generating millions of rows tractable in minutes rather than hours.
  Writers with a foreign-key dependency on another table being written in
  the same pass (`loans` -> `loan_applications`, `collections` ->
  `repayment_schedule`) declare it via `depends_on=[...]` so the referenced
  writer is always flushed first.

### Usage

```bash
cd demo_lending
pip install -r ../requirements.txt   # Faker, psycopg2-binary, pandas, openpyxl, python-docx already listed there

# against a local/dev Postgres server (only server+creds matter; the
# lending_demo_db database name itself is fixed and created if missing)
python db_lending.py --scale small                      # ~150 MB, seconds - quick smoke test
python db_lending.py --scale full                        # ~1.5-1.8 GB, ~4 min - the default
python db_lending.py --scale full --db-url postgresql://user:pass@host:5432/postgres
```

`--scale` presets (`tiny` / `small` / `medium` / `full`) control the base
master-data row counts; every other table is *derived* from those (e.g.
`repayment_schedule` = loans x average tenure), so the whole data set scales
together and stays internally consistent. `full` was calibrated on this
machine to **1.73 GB** loaded (6.25M `repayment_schedule` rows, 3.06M
`collections` rows, 108k loans, 95k customers) - re-run with `--scale full`
and check `pg_size_pretty(pg_database_size('lending_demo_db'))` if you need
to retune `SCALE_PRESETS["full"]` for a different target size.

The script is idempotent: it always `DROP`s and recreates the schema, so
re-running with a different `--scale` fully replaces the previous data set
(same fixed random seed, so a given `--scale` always regenerates the exact
same data).

### Registering it in Saarthi

Add it like any other Postgres data source from the Saarthi UI
(`app/templates/connections/configure_new.html` / the Database Connections
page): host/port/credentials of the Postgres server, database name
`lending_demo_db`. Saarthi's Metamind schema discovery will pick up all 13
tables and their columns automatically.

## 2. Excel reference tables (`generate_excel_reference.py`)

Generates the kind of reference data a real NBFC keeps in spreadsheets
*outside* the core loan system - useful for testing Saarthi's spreadsheet
connector (`app/services/spreadsheet_service.py`) and for cross-checking
figures between the DB and an "external" source:

- `01_rbi_benchmark_rates.xlsx` - policy rates + a product-rate-vs-benchmark
  check (two products are deliberately flagged as pricing outside benchmark,
  for exercising anomaly-style NL queries)
- `02_branch_master.xlsx` - branch roster with live employee/agent counts
  pulled from the DB
- `03_agent_commission_slabs.xlsx` - DSA commission slab card by product
- `04_insurance_partner_rates.xlsx` - credit-linked insurance premium rates

Run after `db_lending.py` (it reads branch/product data from the DB to stay
consistent with whatever `--scale` was loaded):

```bash
python generate_excel_reference.py --db-url postgresql://user:pass@host:5432/postgres
```

## 3. NBFC guideline documents (`generate_guideline_docs.py`)

Five `.docx` policy documents for Saarthi's unstructured-document RAG
pipeline (`app/templates/unstructured/documents.html`):

- Fair Practices Code
- KYC / AML Policy
- IRAC / NPA Classification & Provisioning Norms
- Digital Lending Operating Guidelines
- Customer Grievance Redressal Policy

**These are original, practitioner-style summaries written for this demo** -
not a reproduction of any official RBI publication - intended purely to give
the RAG pipeline realistic-looking policy text to answer questions against
(e.g. "what DPD bucket is SMA-2?", "what's the grievance escalation TAT?").
Do not use them as an actual compliance reference.

```bash
python generate_guideline_docs.py
```

## 4. Validation API (`validation_api.py`)

A stub Flask service standing in for the external verification calls a
real NBFC makes during onboarding/underwriting - PAN/GSTIN/Aadhaar *format*
validation (no live government/bureau integration) and a mock credit bureau
score/report lookup keyed off `customer_id` (CIBIL score is read straight
from the seeded `customers` row; other bureaus return a deterministic
simulated variant). Exists so Saarthi's API-connector datasource type has
something real to call.

```bash
python validation_api.py                 # http://localhost:8600
```

| Endpoint                              | Method | Body / Params                       |
|-----------------------------------------|--------|--------------------------------------|
| `/health`                              | GET    | -                                    |
| `/validate/pan`                        | POST   | `{"pan": "ABCDE1234F"}`               |
| `/validate/gstin`                      | POST   | `{"gstin": "27ABCDE1234F1Z5"}`         |
| `/validate/aadhaar`                    | POST   | `{"aadhaar_masked": "XXXX-XXXX-1234"}` |
| `/bureau/score/<customer_id>?bureau=CIBIL` | GET | -                                  |
| `/bureau/report/<customer_id>`         | GET    | -                                    |

Register it in Saarthi as an API connector (`app/templates/api_connectors/rest_apis.html`).

## Regenerating everything from scratch

```bash
cd demo_lending
python db_lending.py --scale full
python generate_excel_reference.py
python generate_guideline_docs.py
python validation_api.py &   # leave running while Saarthi is registered against it
```
