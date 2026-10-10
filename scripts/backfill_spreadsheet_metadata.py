"""
One-time repair of existing database_connections rows and spreadsheet
tables, so connections uploaded before the column-metadata fixes get the
same treatment new uploads do:

  Excel connections
    1. A connection whose uploaded file/manifest entry is gone is marked
       status='error' ("re-upload needed") instead of sitting there with an
       empty description/summary looking fine.
    2. Notes/footer lines that were loaded as data rows at the bottom of a
       table (one filled cell, e.g. "Notes", "- Commission is paid on ...")
       are moved out of the data and kept as the table's notes.
    3. Numbers stored as text ("0.64%", "1,200") become real numbers, with
       the unit recorded per column; each column gets a role.
    4. Unless --no-llm: the table description and every column's meaning
       are regenerated from the title, notes, headers and sample rows (the
       same step Process now runs).
    5. schema_metadata is filled in from the result.

  PostgreSQL connections (only with --db-columns)
    Column meanings are inferred from sample values (the same step Process
    now runs). Needs schema_metadata from an earlier introspection.

  All connections
    Runs of whitespace in name/description are collapsed
    ("Lending    Database." -> "Lending Database.").

Not recoverable here: the original column headers of an old upload (e.g.
"Slab: < Rs 10L/qtr" was stored as slab_rs_10l_qtr, losing the "<"). For a
table like that, delete the connection and re-upload the file - the new
upload keeps the headers and names the column slab_lt_rs_10l_qtr.

Safe to re-run. Use --dry-run to see what would change without saving.

Usage:
    python scripts/backfill_spreadsheet_metadata.py [--dry-run] [--no-llm] [--db-columns]
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models.database_connection import DatabaseConnection

MISSING_MESSAGE = "The uploaded file for this connection is missing. Please delete this connection and re-upload the file."


def split_trailing_note_rows(df):
    """Rows at the bottom of an already-stored table that hold at most one
    cell in a 3+ column table - note lines, not data. Returns (df, notes)."""
    if len(df.columns) < 3:
        return df, ""
    filled = df.notna().sum(axis=1).tolist()
    cut = len(filled)
    while cut > 0 and filled[cut - 1] <= 1:
        cut -= 1
    if cut == len(filled) or cut == 0:
        return df, ""
    lines = [str(v).strip() for _, row in df.iloc[cut:].iterrows() for v in row.tolist()
             if v is not None and str(v).strip() and str(v) != "nan"]
    return df.iloc[:cut].reset_index(drop=True), "\n".join(lines)


def repair_excel_connection(connection, args, log):
    from app.services import spreadsheet_service
    from app.routes.database_routes import _summarize_spreadsheet_table_for_metamind

    tables = spreadsheet_service.get_tables_for_connection(connection.id)
    if not tables:
        log("  no data on disk -> marked as error (re-upload needed)")
        connection.status = "error"
        connection.error_message = MISSING_MESSAGE
        connection.metamind_summary = "No data available - the uploaded file is missing and needs to be re-uploaded."
        return

    for record in tables:
        name = record["table"]
        try:
            df = spreadsheet_service.get_table_df(name)
        except Exception as e:
            log(f"  {name}: could not read its data file ({e}) -> marked as error")
            connection.status = "error"
            connection.error_message = MISSING_MESSAGE
            return
        before = len(df)
        df, notes = split_trailing_note_rows(df)
        if notes:
            log(f"  {name}: moved {before - len(df)} note row(s) out of the data")
        labels = {c["name"]: c["label"] for c in record.get("columns", []) if c.get("label")}
        if args.dry_run:
            continue
        spreadsheet_service.save_table(
            connection.id, name, record.get("sheet"), df, labels=labels,
            title=record.get("title") or connection.description or "",
            notes="\n".join(x for x in (record.get("notes"), notes) if x),
        )
        if not args.no_llm:
            description = _summarize_spreadsheet_table_for_metamind(name, connection.description)
            log(f"  {name}: {description}")

    if not args.dry_run:
        connection.schema_metadata = spreadsheet_service.schema_metadata_for(
            spreadsheet_service.get_tables_for_connection(connection.id)
        )
        if connection.error_message == MISSING_MESSAGE:
            connection.status, connection.error_message = "connected", None
        log(f"  schema_metadata filled for {len(connection.schema_metadata)} table(s)")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="report only, save nothing")
    parser.add_argument("--no-llm", action="store_true", help="skip regenerating descriptions/column meanings")
    parser.add_argument("--db-columns", action="store_true", help="also infer column meanings for PostgreSQL connections")
    args = parser.parse_args()

    from app.routes.database_routes import _clean_text
    from app.services.automated_metamind import enrich_db_column_semantics

    app = create_app()
    with app.app_context():
        for connection in DatabaseConnection.query.order_by(DatabaseConnection.id).all():
            print(f"[{connection.id}] {connection.name} ({connection.type})")
            log = print
            clean_name, clean_desc = _clean_text(connection.name) or connection.name, _clean_text(connection.description)
            if (clean_name, clean_desc) != (connection.name, connection.description):
                log("  tidied name/description whitespace")
                connection.name, connection.description = clean_name, clean_desc

            try:
                if (connection.type or "").lower() == "excel":
                    repair_excel_connection(connection, args, log)
                elif (connection.type or "").lower() == "postgresql" and args.db_columns and not args.dry_run:
                    if not connection.schema_metadata:
                        log("  no schema_metadata yet - click Process on this connection first")
                    else:
                        log(f"  column meanings added for {enrich_db_column_semantics(connection)} table(s)")
            except Exception as e:
                db.session.rollback()
                log(f"  FAILED: {e}")
                continue

            if args.dry_run:
                db.session.rollback()
            else:
                db.session.commit()
    print("Done." + (" (dry run - nothing saved)" if args.dry_run else ""))


if __name__ == "__main__":
    main()
