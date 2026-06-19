import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from urllib.parse import urlparse

def initialize_api_database(base_database_url):
    """
    Automatically creates the separate database and its tables on startup
    by parsing the application's existing live database URL connection string.
    """
    new_db_name = "saarthi_api_db"
    
    try:
        # 1. Parse the existing connection string to find the host, user, password, and port
        result = urlparse(base_database_url)
        username = result.username
        password = result.password
        host = result.hostname
        port = result.port or 5432
        
        # Reconstruct the connection back to the core database to run our setup check
        dsn = f"postgresql://{username}:{password}@{host}:{port}/saarthi_db"
        
        # Connect to default database to check/create the new database
        conn = psycopg2.connect(dsn)
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cursor = conn.cursor()
        
        # Check if saarthi_api_db already exists
        cursor.execute(f"SELECT 1 FROM pg_database WHERE datname='{new_db_name}'")
        exists = cursor.fetchone()
        
        if not exists:
            print(f"[DB Setup] Database '{new_db_name}' not found. Creating it now...")
            cursor.execute(f"CREATE DATABASE {new_db_name}")
            print(f"[DB Setup] Database '{new_db_name}' created successfully!")
        else:
            print(f"[DB Setup] Database '{new_db_name}' already exists.")
            
        cursor.close()
        conn.close()
        
        # 2. Connect directly to the new database to build the tables
        api_db_dsn = f"postgresql://{username}:{password}@{host}:{port}/{new_db_name}"
        conn = psycopg2.connect(api_db_dsn)
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cursor = conn.cursor()
        
        # Create our table if it doesn't exist
        create_table_query = """
        CREATE TABLE IF NOT EXISTS registered_tools (
            id SERIAL PRIMARY KEY,
            integration_name VARCHAR(100) UNIQUE NOT NULL,
            base_url TEXT NOT NULL,
            endpoint TEXT NOT NULL,
            method VARCHAR(10) NOT NULL DEFAULT 'GET',
            auth_type VARCHAR(50) NOT NULL DEFAULT 'No Auth',
            api_token TEXT,
            api_description TEXT NOT NULL,
            status VARCHAR(20) DEFAULT 'Active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        cursor.execute(create_table_query)
        print("[DB Setup] Table 'registered_tools' is verified and ready.")
        
        cursor.close()
        conn.close()

    except Exception as e:
        print(f"[DB Setup] Error during automated database initialization: {e}")