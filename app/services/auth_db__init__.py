import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from urllib.parse import urlparse

def init_auth_database(base_database_url):
    """
    Standalone initializer that automatically creates a dedicated database 
    and table for the Authentication System on application startup.
    """
    auth_db_name = "saarthi_auth_db"
    
    try:
        # 1. Parse the connection string to extract host, credentials, and port
        result = urlparse(base_database_url)
        username = result.username
        password = result.password
        host = result.hostname
        port = result.port or 5432
        
        # Connect to the base cluster database to check/create our authentication database
        base_dsn = f"postgresql://{username}:{password}@{host}:{port}/saarthi_db"
        conn = psycopg2.connect(base_dsn)
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cursor = conn.cursor()
        
        # Check if saarthi_auth_db already exists
        cursor.execute(f"SELECT 1 FROM pg_database WHERE datname='{auth_db_name}'")
        exists = cursor.fetchone()
        
        if not exists:
            print(f"[Auth DB Setup] Database '{auth_db_name}' not found. Creating it now...")
            cursor.execute(f"CREATE DATABASE {auth_db_name}")
            print(f"[Auth DB Setup] Database '{auth_db_name}' created successfully!")
        else:
            print(f"[Auth DB Setup] Database '{auth_db_name}' already exists.")
            
        cursor.close()
        conn.close()
        
        # 2. Connect directly to the brand new auth database to build the users table
        auth_db_dsn = f"postgresql://{username}:{password}@{host}:{port}/{auth_db_name}"
        conn = psycopg2.connect(auth_db_dsn)
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cursor = conn.cursor()
        
        # Create our clean user tracking schema
        create_table_query = """
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            email VARCHAR(255) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            provider VARCHAR(50) DEFAULT 'local',
            provider_id VARCHAR(255) DEFAULT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        cursor.execute(create_table_query)
        # Add company_code and role if the table already existed from a previous run
        # (ALTER ... ADD COLUMN IF NOT EXISTS is safe to run every time, on fresh or existing tables)
        cursor.execute("""
            ALTER TABLE users ADD COLUMN IF NOT EXISTS company_code VARCHAR(100);
            ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(20) NOT NULL DEFAULT 'user';
        """)
        print("[Auth DB Setup] Columns 'company_code' and 'role' verified on 'users' table.")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_resource_mapping (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                resource_type VARCHAR(20) NOT NULL,
                resource_id VARCHAR(255) NOT NULL,
                resource_name VARCHAR(255),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, resource_type, resource_id)
            );
        """)
        print("[Auth DB Setup] Table 'user_resource_mapping' is verified and ready.")
        print("[Auth DB Setup] Table 'users' is verified and ready for authentication.")
        
        cursor.close()
        conn.close()

    except Exception as e:
        print(f"[Auth DB Setup] Error during isolated authentication database initialization: {e}")