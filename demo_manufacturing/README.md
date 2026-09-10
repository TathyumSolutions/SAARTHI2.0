# Manufacturing Demo Data Set (Engineering / Auto-Components Style)

A self-contained, synthetic manufacturing-company demo data set for exercising
Saarthi end-to-end across all of its connector types: a Postgres database,
Excel reference tables, unstructured policy documents, and a validation API.
Everything here is synthetic - company names, GSTIN/PAN-shaped identifiers,
phone numbers, and financial figures are randomly generated in the right
*format* and are not real companies or real regulatory text.

```
demo_manufacturing/
├── db_manufacturing.py           # schema + Faker-based data generator -> Postgres
├── generate_excel_reference.py   # 4 "external" Excel reference workbooks
├── generate_guideline_docs.py    # 5 factory policy documents (.docx)
├── validation_api.py             # stub GSTIN/PAN + machine health + quality API
└── output/
    ├── excel/                    # generated workbooks
    └── guidelines/                # generated policy documents
```

## 1. The database (`db_manufacturing.py`)

Provisions its own Postgres database, `manufacturing_demo_db`, independent of
Saarthi's own `saarthi_core_db` / `saarthi_resources_db` / `saarthi_workspace_db`
(see `config/config.py`) and independent of the `lending_demo_db` used by
`demo_lending/` - point Saarthi's UI at it afterwards as one more "Database
Connection" data source.

### Schema

| Table                        | What it holds                                                                 |
|-------------------------------|--------------------------------------------------------------------------------|
| `plants`                      | Plant network (city/state/region/plant type: Machining, Foundry, Assembly, ...) |
| `employees`                   | Plant staff (Plant Manager, Production Supervisor, Quality Inspector, ...)     |
| `suppliers`                    | Empanelled raw-material vendors and their quality rating                       |
| `machines`                     | Shop-floor equipment master (CNC, presses, molding machines, ...) and status  |
| `products`                     | Finished-goods catalogue with standard cost/price/cycle time                   |
| `raw_materials`                | Raw material master (steel, aluminium, resins, fasteners, components, ...)     |
| `bill_of_materials`            | Product -> raw material composition (quantity per unit)                        |
| `customers`                    | Buyers: OEM/Tier-1/Distributor/Export, credit limit, payment terms             |
| `purchase_orders`              | Raw-material procurement orders to suppliers -> receipt                        |
| `production_orders`            | Customer order -> shop-floor work order, planned vs. actual, delay/at-risk     |
| `production_log`               | Per-day production tracking per order (the largest table)                     |
| `shipments`                    | Dispatch of finished goods against production orders                          |
| `payables`                     | Supplier payments, utility bills, contractor/lease payables                    |
| `machine_downtime`             | Breakdown/maintenance events, criticality and cost                            |
| `quality_inspection_records`   | Incoming/in-process/final inspection results per production order             |
| `transactions_ledger`          | Sales invoice, payment received, and raw-material purchase ledger entries     |

### Data generation approach

- Indian company/contact names via Faker's `en_IN` locale; GSTIN/PAN/mobile
  numbers are generated in valid *format* only (`gen_gstin`, `gen_pan`,
  `gen_mobile` in `db_manufacturing.py`).
- Product/raw-material catalogues and BOM are modeled on a typical Indian
  engineering/auto-components manufacturer (`PRODUCTS`, `RAW_MATERIALS`).
- Shop-floor behaviour is a 2-state Markov chain per production order
  ("on track" <-> "disrupted") rather than independent per-day coin flips
  (`RELIABILITY_PARAMS`) - this makes disruption *sticky*, matching real
  production lines, and is what drives realistic sustained delays instead of
  noise that mostly self-corrects. A production order's current delay is the
  length of its *unbroken trailing* streak of Delayed/Stopped days, not its
  worst historical moment - i.e. a line that caught back up is "on track"
  again, matching how a real shop-floor delay/at-risk flag works.
- Bulk loading uses Postgres `COPY` via a small buffered `CopyWriter` (not
  row-by-row `INSERT`), batching ~50k rows per flush - this is what makes
  generating millions of rows tractable in minutes rather than hours.
  Writers with a foreign-key dependency on another table being written in
  the same pass (`production_log` -> `production_orders`) declare it via
  `depends_on=[...]` so the referenced writer is always flushed first.

### Usage

```bash
cd demo_manufacturing
pip install -r ../requirements.txt   # Faker, psycopg2-binary, pandas, openpyxl, python-docx already listed there

# against a local/dev Postgres server (only server+creds matter; the
# manufacturing_demo_db database name itself is fixed and created if missing)
python db_manufacturing.py --scale small                      # quick smoke test
python db_manufacturing.py --scale full                        # the default
python db_manufacturing.py --scale full --db-url postgresql://user:pass@host:5432/postgres
```

`--scale` presets (`tiny` / `small` / `medium` / `full`) control the base
master-data row counts (plants, suppliers, machines, customers); every other
table is *derived* from those (e.g. `production_log` = production orders x
average simulated days), so the whole data set scales together and stays
internally consistent.

The script is idempotent: it always `DROP`s and recreates the schema, so
re-running with a different `--scale` fully replaces the previous data set
(same fixed random seed, so a given `--scale` always regenerates the exact
same data).

### Registering it in Saarthi

Add it like any other Postgres data source from the Saarthi UI
(`app/templates/connections/configure_new.html` / the Database Connections
page): host/port/credentials of the Postgres server, database name
`manufacturing_demo_db`. Saarthi's Metamind schema discovery will pick up all
16 tables and their columns automatically.

## 2. Excel reference tables (`generate_excel_reference.py`)

Generates the kind of reference data a real factory keeps in spreadsheets
*outside* the core ERP/MES system - useful for testing Saarthi's spreadsheet
connector (`app/services/spreadsheet_service.py`) and for cross-checking
figures between the DB and an "external" source:

- `01_raw_material_price_benchmarks.xlsx` - commodity index snapshot + a
  material-price-vs-benchmark check (two materials are deliberately flagged
  as priced above the market benchmark, for exercising anomaly-style NL
  queries)
- `02_plant_master.xlsx` - plant roster with live employee/machine counts
  pulled from the DB
- `03_vendor_rating_card.xlsx` - supplier empanelment tiers and scorecard
  weightage
- `04_machine_maintenance_schedule.xlsx` - preventive-maintenance interval
  reference by machine type, with live fleet counts pulled from the DB

Run after `db_manufacturing.py` (it reads plant/material/machine data from
the DB to stay consistent with whatever `--scale` was loaded):

```bash
python generate_excel_reference.py --db-url postgresql://user:pass@host:5432/postgres
```

## 3. Factory policy documents (`generate_guideline_docs.py`)

Five `.docx` policy documents for Saarthi's unstructured-document RAG
pipeline (`app/templates/unstructured/documents.html`):

- Quality Management Policy (ISO 9001-style)
- Environment, Health and Safety (EHS) Policy
- Vendor and Supplier Management Policy
- Equipment Maintenance and Calibration Policy
- Environmental Compliance and Waste Management Policy

**These are original, practitioner-style summaries written for this demo** -
not a reproduction of any official ISO or regulatory publication - intended
purely to give the RAG pipeline realistic-looking policy text to answer
questions against (e.g. "what's the PM frequency for a CNC lathe?", "what
defect rate triggers a Fail result?"). Do not use them as an actual
compliance reference.

```bash
python generate_guideline_docs.py
```

## 4. Validation API (`validation_api.py`)

A stub Flask service standing in for the external/internal-systems calls a
real manufacturer makes during vendor/customer onboarding and shop-floor
operations - GSTIN/PAN *format* validation (no live GSTN integration), a
mock machine health/status lookup, and a quality-inspection summary lookup,
both derived from the seeded database. Exists so Saarthi's API-connector
datasource type has something real to call.

```bash
python validation_api.py                 # http://localhost:8601
```

| Endpoint                                  | Method | Body / Params                       |
|---------------------------------------------|--------|--------------------------------------|
| `/health`                                  | GET    | -                                    |
| `/validate/gstin`                          | POST   | `{"gstin": "27ABCDE1234F1Z5"}`         |
| `/validate/pan`                            | POST   | `{"pan": "ABCDE1234F"}`               |
| `/machine/status/<machine_id>`             | GET    | -                                    |
| `/machine/health/<machine_id>`             | GET    | -                                    |
| `/quality/inspection/<production_order_id>`| GET    | -                                    |

Register it in Saarthi as an API connector (`app/templates/api_connectors/rest_apis.html`).

## Regenerating everything from scratch

```bash
cd demo_manufacturing
python db_manufacturing.py --scale full
python generate_excel_reference.py
python generate_guideline_docs.py
python validation_api.py &   # leave running while Saarthi is registered against it
```
