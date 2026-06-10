# # import re
# # from pathlib import Path

# # # Try latin-1 (safe for SQL dumps)
# # sql_file = Path("/home/itdelivery/dump-sap_database-202509161809.sql").read_text(encoding="latin-1")

# # # Extract CREATE TABLE blocks
# # tables = re.findall(r"CREATE TABLE.*?\);", sql_file, re.S)

# # # Clean + save chunks
# # schema_chunks = []
# # for t in tables:
# #     lines = [line.strip() for line in t.splitlines() if line.strip()]
# #     schema_chunks.append("\n".join(lines))

# # print(f"Extracted {len(schema_chunks)} tables")
# # print(schema_chunks[0])  # preview




# import psycopg2
# import json
# from collections import defaultdict

# def get_db_schema(host, port, dbname, user, password, schema="public"):
#     conn = psycopg2.connect(
#         host=host,
#         port=port,
#         dbname=dbname,
#         user=user,
#         password=password
#     )
#     cur = conn.cursor()

#     # Fetch tables
#     cur.execute("""
#         SELECT table_name
#         FROM information_schema.tables
#         WHERE table_schema = %s
#         ORDER BY table_name;
#     """, (schema,))
#     tables = [t[0] for t in cur.fetchall()]

#     db_schema = {"tables": {}}

#     for table in tables:
#         # Fetch columns
#         cur.execute("""
#             SELECT column_name, data_type, is_nullable, character_maximum_length
#             FROM information_schema.columns
#             WHERE table_schema = %s AND table_name = %s
#             ORDER BY ordinal_position;
#         """, (schema, table))

#         columns = {}
#         for col_name, data_type, is_nullable, char_len in cur.fetchall():
#             col_type = data_type
#             if char_len:
#                 col_type += f"({char_len})"
#             columns[col_name] = {
#                 "type": col_type,
#                 "nullable": (is_nullable == "YES")
#             }

#         # Fetch primary keys
#         cur.execute("""
#             SELECT kcu.column_name
#             FROM information_schema.table_constraints tc
#             JOIN information_schema.key_column_usage kcu
#               ON tc.constraint_name = kcu.constraint_name
#              AND tc.table_schema = kcu.table_schema
#             WHERE tc.constraint_type = 'PRIMARY KEY'
#               AND tc.table_schema = %s
#               AND tc.table_name = %s;
#         """, (schema, table))
#         pk = [r[0] for r in cur.fetchall()]

#         # Fetch foreign keys
#         cur.execute("""
#             SELECT
#                 kcu.column_name,
#                 ccu.table_name AS foreign_table,
#                 ccu.column_name AS foreign_column
#             FROM information_schema.table_constraints tc
#             JOIN information_schema.key_column_usage kcu
#               ON tc.constraint_name = kcu.constraint_name
#              AND tc.table_schema = kcu.table_schema
#             JOIN information_schema.constraint_column_usage ccu
#               ON ccu.constraint_name = tc.constraint_name
#              AND ccu.table_schema = tc.table_schema
#             WHERE tc.constraint_type = 'FOREIGN KEY'
#               AND tc.table_schema = %s
#               AND tc.table_name = %s;
#         """, (schema, table))

#         fks = [
#             {"column": r[0], "references": f"{r[1]}.{r[2]}"}
#             for r in cur.fetchall()
#         ]

#         # Add to schema
#         db_schema["tables"][table] = {
#             "columns": columns,
#             "primary_key": pk,
#             "foreign_keys": fks
#         }

#     cur.close()
#     conn.close()
#     return db_schema


# if __name__ == "__main__":
#     schema = get_db_schema(
#         host="localhost",   # change if remote
#         port=5432,
#         dbname="data-bridge2",
#         user="postgres",
#         password="postgres"
#     )

#     # Save schema to JSON file
#     with open("sap_schema.json", "w") as f:
#         json.dump(schema, f, indent=2)

#     print("✅ Schema extracted to sap_schema.json")
 


#  dec10code
import psycopg2
import json
#from ollama import Ollama
import ollama
from ollama import Client

def get_sap_schema_with_comments(host, port, dbname, user, password, schema="public"):
    """
    Extracts SAP database schema and generates detailed comments using Llama3.
    Uses SAP knowledge for table/column descriptions and includes example values.
    """
    conn = psycopg2.connect(
        host=host,
        port=port,
        dbname=dbname,
        user=user,
        password=password
    )
    cur = conn.cursor()

    # Fetch tables
    cur.execute("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = %s
        ORDER BY table_name;
    """, (schema,))
    tables = [t[0] for t in cur.fetchall()]

    db_schema = {"tables": {}, "database_comment": ""}

    # Initialize Ollama client
    #client = Ollama(model="llama3:latest")
    #client = Client(host='http://localhost:11434')
    #client = Client(host='http://host.docker.internal:11434')
    client = Client(host='http://ollama:11434')

    # Database-level comment using SAP context
    db_prompt = (
        "You are an expert in SAP ERP systems. "
        "Given the following SAP table names, generate a detailed comment about the database, "
        "including its purpose, main business processes it represents, and relationships between tables. "
        "Include examples of data typical for SAP ERP.\n\n"
        f"Tables: {tables}\n\n"
        "Output should be clear and descriptive for an AI agent."
    )
    #db_schema["database_comment"] = client.generate(db_prompt).text
    db_schema["database_comment"] = client.generate(model='llama3:latest', prompt=db_prompt)['response']

    for table in tables:
        # Fetch columns
        cur.execute("""
            SELECT column_name, data_type, is_nullable, character_maximum_length
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position;
        """, (schema, table))

        columns = {}
        for col_name, data_type, is_nullable, char_len in cur.fetchall():
            col_type = data_type
            if char_len:
                col_type += f"({char_len})"
            columns[col_name] = {
                "type": col_type,
                "nullable": (is_nullable == "YES"),
                "example_values": []
            }

        # Primary keys
        cur.execute("""
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            WHERE tc.constraint_type = 'PRIMARY KEY'
              AND tc.table_schema = %s
              AND tc.table_name = %s;
        """, (schema, table))
        pk = [r[0] for r in cur.fetchall()]

        # Foreign keys
        cur.execute("""
            SELECT
                kcu.column_name,
                ccu.table_name AS foreign_table,
                ccu.column_name AS foreign_column
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage ccu
              ON ccu.constraint_name = tc.constraint_name
             AND ccu.table_schema = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_schema = %s
              AND tc.table_name = %s;
        """, (schema, table))
        fks = [{"column": r[0], "references": f"{r[1]}.{r[2]}"} for r in cur.fetchall()]

        # Sample data
        for col in columns:
            cur.execute(f"SELECT {col} FROM {schema}.{table} WHERE {col} IS NOT NULL LIMIT 5;")
            examples = [str(r[0]) for r in cur.fetchall()]
            columns[col]["example_values"] = examples

        # Table-level comment using SAP context
        table_prompt = (
            f"You are an SAP ERP data expert. Describe the purpose of the table '{table}', "
            "its role in SAP processes, and the meaning of each column. "
            "Include example values where applicable. Use your SAP domain knowledge "
            "for standard tables like MARA, VBAP, VBAK, etc.\n\n"
            f"Columns with example data: {json.dumps(columns, indent=2)}"
        )
        #table_comment = client.generate(table_prompt).text
        table_comment = client.generate(model='llama3:latest', prompt=table_prompt)['response']

        db_schema["tables"][table] = {
            "columns": columns,
            "primary_key": pk,
            "foreign_keys": fks,
            "comment": table_comment
        }

    cur.close()
    conn.close()
    return db_schema


#if __name__ == "__main__":
#    schema = get_sap_schema_with_comments(
#        host="localhost",
#        port=5432,
#        dbname="data-bridge2",
#        user="postgres",
#        password="postgres"
#    )

if __name__ == "__main__":
    # Point directly to your local Ollama from inside Docker
    #client = Client(host='http://host.docker.internal:11434')
    client = Client(host='http://ollama:11434')

    schema = get_sap_schema_with_comments(
        host="db",           
        port=5432,
        dbname="databrige_db", # Hardcoded target
        user="saarthi",      
        password="password"
    )
    import os
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    save_path = os.path.join(BASE_DIR, "sap_schema_with_sap_comments.json")

    # Save schema
    with open(save_path, "w") as f:
        json.dump(schema, f, indent=2)

    print("✅ Success! JSON created in databrige_db.")

    # Save schema with SAP-aware comments
    #with open("sap_schema_with_sap_comments.json", "w") as f:
    #    json.dump(schema, f, indent=2)

    #print("✅ SAP schema with domain-specific comments saved to sap_schema_with_sap_comments.json")
