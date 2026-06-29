import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from urllib.parse import urlparse

def initialize_chats_database(base_database_url):
    """
    Standalone initializer that automatically creates a dedicated database 
    and table for the Chat Audit Trail/History on application startup.
    """
    chats_db_name = "saarthi_chats_db"
    
    try:
        # 1. Parse the connection string to extract host, credentials, and port
        result = urlparse(base_database_url)
        username = result.username
        password = result.password
        host = result.hostname
        port = result.port or 5432
        
        # Connect to the base cluster database to check/create our chat database
        base_dsn = f"postgresql://{username}:{password}@{host}:{port}/saarthi_db"
        conn = psycopg2.connect(base_dsn)
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cursor = conn.cursor()
        
        # Check if saarthi_chats_db already exists
        cursor.execute(f"SELECT 1 FROM pg_database WHERE datname='{chats_db_name}'")
        exists = cursor.fetchone()
        
        if not exists:
            print(f"[Chats DB Setup] Database '{chats_db_name}' not found. Creating it now...")
            cursor.execute(f"CREATE DATABASE {chats_db_name}")
            print(f"[Chats DB Setup] Database '{chats_db_name}' created successfully!")
        else:
            print(f"[Chats DB Setup] Database '{chats_db_name}' already exists.")
            
        cursor.close()
        conn.close()
        
        # 2. Connect directly to the brand new chats database to build the sessions table
        chats_db_dsn = f"postgresql://{username}:{password}@{host}:{port}/{chats_db_name}"
        conn = psycopg2.connect(chats_db_dsn)
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cursor = conn.cursor()
        
        # Create our clean chat tracking schema
        create_table_query = """
        CREATE TABLE IF NOT EXISTS chat_sessions (
            id SERIAL PRIMARY KEY,
            session_id VARCHAR(255) UNIQUE NOT NULL,
            title VARCHAR(255) NOT NULL,
            chat_history TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        cursor.execute(create_table_query)
        print("[Chats DB Setup] Table 'chat_sessions' is verified and ready for audit trails.")
        
        cursor.close()
        conn.close()

    except Exception as e:
        print(f"[Chats DB Setup] Error during isolated chat database initialization: {e}")