# Findings from the question-bank evaluation

Run on 2026-11-27 against `lending_demo_db` and `manufacturing_demo_db`
(`--scale small`), 45 questions with reference SQL.

## Fixed

### 1. Inferred join relations were almost all wrong
`app/services/automated_metamind.py`, `_infer_db_relations`

On `main` the inference offered QuerySense 39 (lending) and 56
(manufacturing) "relations". Both schemas declare every real foreign
key, so none was needed, and nearly all were harmful:

- Sibling foreign keys: `agents.branch_id ~ loans.branch_id`. Both point
  at `branches`, so this join pairs every agent with every loan of a
  branch. It is the wrong path for the questions that need "loans by
  agent" (TXT-M4, TXT-C4, T1, A1-A3), which goes through
  `loan_applications`. `purchase_orders.plant_id ~ shipments.plant_id`
  likewise invents the supplier-to-shipment link the question bank says
  does not exist.
- Plain attributes that share a name: `order_date`, `unit_price`,
  `category`, `mobile`, `email`, `gstin`, `is_active`, `city`.
- `paid_date` accepted as a key because "pa**id**" contains "id".

Now one side must be a key (PK, UNIQUE, or profiled unique with an
id-like name); sibling FKs are rejected; key names match on whole tokens.
Undeclared FKs to a key, SAP-style names and unannotated schemas still
work (`tests/test_infer_db_relations.py`).
Stage check `relations`: 95 suspect relations -> 0.

### 2. Local models were shown the wrong tables
`app/services/databridge_services/agents/query_sense_agent.py`, `_relevant_tables`

For Ollama models QuerySense sends only 6 tables. On `main`, 8 of 45
questions lost a table the answer needs:

- "rejection rate" never reached `production_log.rejected_qty`, and
  "logged" never reached `production_log` (no stemming).
- "POs" was dropped (words under 3 letters were ignored).
- One point per matching column let tables with many generic hits
  (`status`, `amount`, `branch_id`) push out `branches`, the only table
  with `region`.
- The bridge table (`loans` between `repayment_schedule` and
  `branches`) was only added if slots were left.

Now: a shared stem function, capitalised acronyms, IDF-weighted column
words, FK role words ("requester" -> employees), and bridge tables taken
with the table they connect (`tests/test_query_sense_table_relevance.py`).
Stage check `trim`: 8 failures -> 4. The remaining four need meaning
rather than words ("money" -> `transactions_ledger`, "volume slab" ->
`loans`) or a 7th table where the limit is 6 (`OLLAMA_SCHEMA_MAX_TABLES`).

### 3. A failed LLM call was reported as "LLM returned empty response"
`app/services/databridge_services/agents/sql_generator_agent.py`

A missing API key or a refused call surfaced as an empty response. The
error now carries the exception, e.g. "the LLM call raised
ValidationError: 1 validation error for ChatAnthropic".

## Not run here

The `--pipeline` run (questions answered by the LLM) needs a model. This
environment has no Ollama host and no LLM API key, so no LLM answers
were graded. The pipeline plumbing was verified up to the LLM call.
Run `python -m regression.run_regression --pipeline` with a model
configured (see README) to grade the answers and get the next round of fixes.

## Data notes worth knowing before reading results

See README, "Data facts the reference SQL relies on". In short:
- Commission payables are not tied to the sourcing agent, so per-agent
  commission totals (TXT-C4) reflect the generator, not real attribution.
- `loans.current_dpd` is the trailing unpaid streak; the question bank's
  C3 rule (oldest unpaid installment) therefore flags 1,060 loans by design.
