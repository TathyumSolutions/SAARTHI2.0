import psycopg2

#DB_CONFIG = {
#    'host': 'localhost',
#    'database': 'myflaskdb',
#    'user': 'myflaskuser',
#    'password': 'mypassword123',
#    'port': '5432'
#}
DB_CONFIG = {
    'host': 'db',            # Service name from docker-compose
    'database': 'saarthi_db', # Or whatever you named it in .env
    'user': 'saarthi', 
    'password': 'password', 
    'port': '5432'
}

try:
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute('SELECT version();')
    version = cur.fetchone()
    print("✓ PostgreSQL connection successful!")
    print(f"Database version: {version[0]}")
    cur.close()
    conn.close()
except Exception as e:
    print(f"✗ Connection failed: {str(e)}")
