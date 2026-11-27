# Question-bank regression framework

Runs every question in the Lending and Manufacturing question banks
against the demo databases, grades the answers against hand-written
reference SQL, and reports what failed and why.

| Question source | Ids | Bank file |
|---|---|---|
| `docs/LoanQestions.txt` | `TXT-S1`..`TXT-C5` | `question_bank/lending.yaml` |
| `docs/NBFC Lending Question Bank.docx` | `S1`..`A3`, `F1`..`F3` | `question_bank/lending.yaml` |
| `docs/Manufacturing Question Bank (2).docx` | `S1`..`A3`, `F1`..`F3` | `question_bank/manufacturing.yaml` |

Each question records its resolved wording, the logic a correct answer
needs (from the docx), a reference SQL query, and how to compare. `:as_of`
is the data generator's own "today" (lending 2026-08-22, manufacturing
2026-08-25), so relative periods ("last quarter", "12 months to :as_of")
stay fixed. Entity placeholders (`:loan_account_number`, `:supplier_code`,
...) are real values from the `--scale small` data set.

## Layout

```
regression/
  question_bank/*.yaml   questions, reference SQL, compare rules
  expected/<domain>/     reference results saved by --snapshot
  bank.py                loads a bank, fills {{placeholders}}
  reference.py           runs reference SQL; saves/loads snapshots
  pipeline_runner.py     asks the real DataBridge (LangGraph) pipeline
  evaluator.py           value-based grading of a pipeline answer
  stage_checks.py        checks of pipeline stages that need no LLM
  report.py              Markdown + JSON report in reports/
  run_regression.py      command line
  tests/                 tests of the framework and the banks
```

## Setup

1. Load the demo data (PostgreSQL; the snapshots were taken at `--scale small`):

   ```bash
   python demo_lending/db_lending.py --scale small --db-url postgresql://saarthi:password@localhost:5432/postgres
   ```

   ```bash
   python demo_manufacturing/db_manufacturing.py --scale small --db-url postgresql://saarthi:password@localhost:5432/postgres
   ```

2. Point the framework at that server and choose a model. In PowerShell:

   ```powershell
   $env:REGRESSION_DB_URL = "postgresql://saarthi:password@localhost:5432/postgres"
   $env:REGRESSION_MODEL  = "api://claude-sonnet-4-5"   # or "api://gpt-4o", or "ollama://llama3"
   $env:REGRESSION_API_KEY = "<key for an api:// model>"
   $env:REGRESSION_OLLAMA_URL = "http://localhost:11434"  # for ollama:// models
   ```

   In bash, use `export NAME=value` instead.

## Running

Run from the repository root.

```bash
python -m regression.run_regression --check-params --stages
```

```bash
python -m regression.run_regression --pipeline
```

```bash
python -m regression.run_regression --pipeline --domain lending --ids S1,M2,TXT-M4
```

```bash
python -m pytest regression/tests
```

- `--check-params`: every entity placeholder exists in the loaded data.
- `--snapshot`: run the reference SQL and save the results to `expected/`.
  Re-run after regenerating the data at another scale.
- `--stages`: no LLM needed. Reference SQL still matches its snapshot;
  inferred join relations are sane; the tables a local model is shown
  include every table the answer needs; required join paths exist.
- `--pipeline`: each question goes through `run_data_bridge_agent`, the
  same LangGraph pipeline the chat uses (simplifier, QuerySense,
  validator, SQL generator, formatter, ...). The harness only supplies
  what the web app looks up per user: the schema (introspected from the
  demo DB by the app's own functions), the connection to run SQL on, and
  a throwaway SQLite app database. `--db-only` limits it to DB-only questions.

Reports go to `regression/reports/` (ignored by git). The exit code is
non-zero when anything fails, so the run can gate CI.

## Grading

The pipeline names its own columns, so grading is by value. Each column
listed in `compare.match_columns` must have a pipeline column with the
same values (as a multiset, or in order for `mode: ordered`). Whole
numbers must match exactly. Fractions may differ by rounding (0.011
absolute, 0.05 % relative). A percentage may come back as a fraction.

| Status | Meaning |
|---|---|
| PASS | right row count and the required columns match |
| PARTIAL | some columns match, or the count is right but values differ |
| FAIL | nothing matches, or rows were returned where none exist |
| ERROR | the pipeline raised or returned an error |
| SKIP | nothing to grade |

Questions that rely on the policy document, the Excel card or an external
API (`T3`, `F1`, `F2`, and the DOC/XLSX parts of `T*`/`A*`) are graded on
`expected_facts` phrases in the answer text. Those parts need the full
router with documents and spreadsheets loaded. The DB part of every
mixed question has its own reference SQL.

## Data facts the reference SQL relies on

- `loans` has no `agent_id`; agent-sourced loans go through `loan_applications`.
- `loan_products.processing_fee_pct` is a percentage (2.00 = 2 %);
  `npa_classification.provisioning_pct` is a fraction (0.15 = 15 %).
- `collections.total_amount` = principal + interest; the penalty is
  posted separately.
- The lending data holds one NPA snapshot (2026-08-01), for active loans only.
- Agent Commission payables carry a random `agent_id`, not the sourcing
  agent's (`db_lending.py`, `random.choice(agent_pool)`).
- Manufacturing Sales Invoice = quantity ordered x unit price; shipment
  invoices include freight. Shipped value is compared without freight.
- TXT-C5 (ledger vs loan) and manufacturing T2 (missing reject reasons)
  have no rows in this data. The correct answer is "none".
