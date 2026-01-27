import time
from typing import Dict, Any, Tuple, Optional

class DatabaseService:
    """Service for testing database connections"""
    
    @staticmethod
    def test_postgresql(config: Dict[str, Any]) -> Tuple[bool, str]:
        """Test PostgreSQL connection"""
        try:
            import psycopg2
            
            conn = psycopg2.connect(
                host=config.get('host'),
                port=config.get('port', 5432),
                database=config.get('database'),
                user=config.get('username'),
                password=config.get('password'),
                connect_timeout=5
            )
            conn.close()
            return True, "Connection successful"
        except ImportError:
            return False, "psycopg2 package not installed. Run: pip install psycopg2-binary"
        except Exception as e:
            return False, str(e)
    
    @staticmethod
    def test_mysql(config: Dict[str, Any]) -> Tuple[bool, str]:
        """Test MySQL connection"""
        try:
            import mysql.connector
            
            conn = mysql.connector.connect(
                host=config.get('host'),
                port=config.get('port', 3306),
                database=config.get('database'),
                user=config.get('username'),
                password=config.get('password'),
                connection_timeout=5
            )
            conn.close()
            return True, "Connection successful"
        except ImportError:
            return False, "mysql-connector-python package not installed. Run: pip install mysql-connector-python"
        except Exception as e:
            return False, str(e)
    
    @staticmethod
    def test_mongodb(config: Dict[str, Any]) -> Tuple[bool, str]:
        """Test MongoDB connection"""
        try:
            import pymongo
            
            # Build connection string
            auth_source = config.get('authSource', 'admin')
            connection_string = f"mongodb://{config.get('username')}:{config.get('password')}@{config.get('host')}:{config.get('port', 27017)}/{config.get('database')}?authSource={auth_source}"
            
            client = pymongo.MongoClient(
                connection_string,
                serverSelectionTimeoutMS=5000
            )
            # Force connection
            client.server_info()
            client.close()
            return True, "Connection successful"
        except ImportError:
            return False, "pymongo package not installed. Run: pip install pymongo"
        except Exception as e:
            return False, str(e)
    
    @staticmethod
    def test_sqlserver(config: Dict[str, Any]) -> Tuple[bool, str]:
        """Test SQL Server connection"""
        try:
            import pyodbc
            
            # Build connection string
            if config.get('instance'):
                server = f"{config.get('host')}\\{config.get('instance')}"
            else:
                server = f"{config.get('host')},{config.get('port', 1433)}"
            
            conn_str = (
                f"DRIVER={{ODBC Driver 17 for SQL Server}};"
                f"SERVER={server};"
                f"DATABASE={config.get('database')};"
                f"UID={config.get('username')};"
                f"PWD={config.get('password')}"
            )
            
            conn = pyodbc.connect(conn_str, timeout=5)
            conn.close()
            return True, "Connection successful"
        except ImportError:
            return False, "pyodbc package not installed. Run: pip install pyodbc"
        except Exception as e:
            return False, str(e)
    
    @staticmethod
    def test_oracle(config: Dict[str, Any]) -> Tuple[bool, str]:
        """Test Oracle connection"""
        try:
            import cx_Oracle
            
            dsn = cx_Oracle.makedsn(
                config.get('host'),
                config.get('port', 1521),
                service_name=config.get('serviceName', config.get('database'))
            )
            
            conn = cx_Oracle.connect(
                user=config.get('username'),
                password=config.get('password'),
                dsn=dsn
            )
            conn.close()
            return True, "Connection successful"
        except ImportError:
            return False, "cx_Oracle package not installed. Run: pip install cx_Oracle"
        except Exception as e:
            return False, str(e)
    
    @staticmethod
    def test_redis(config: Dict[str, Any]) -> Tuple[bool, str]:
        """Test Redis connection"""
        try:
            import redis
            
            r = redis.Redis(
                host=config.get('host'),
                port=config.get('port', 6379),
                password=config.get('password'),
                db=config.get('db', 0),
                socket_connect_timeout=5
            )
            r.ping()
            r.close()
            return True, "Connection successful"
        except ImportError:
            return False, "redis package not installed. Run: pip install redis"
        except Exception as e:
            return False, str(e)
    
    @staticmethod
    def test_generic(config: Dict[str, Any]) -> Tuple[bool, str]:
        """Generic test for other database types (simulated)"""
        # For databases without actual connectors, simulate success
        db_type = config.get('type', 'Unknown')
        return True, f"Simulated connection test for {db_type} passed"
    
    @staticmethod
    def test_connection(db_type: str, config: Dict[str, Any]) -> Tuple[bool, str, int]:
        """
        Route to appropriate test method based on database type
        Returns: (success: bool, message: str, latency_ms: int)
        """
        start_time = time.time()
        
        db_type_lower = db_type.lower()
        
        # Map database types to test functions
        test_functions = {
            'postgresql': DatabaseService.test_postgresql,
            'mysql': DatabaseService.test_mysql,
            'mongodb': DatabaseService.test_mongodb,
            'sql server': DatabaseService.test_sqlserver,
            'sqlserver': DatabaseService.test_sqlserver,
            'oracle': DatabaseService.test_oracle,
            'redis': DatabaseService.test_redis,
        }
        
        # Get the appropriate test function
        test_func = test_functions.get(db_type_lower, DatabaseService.test_generic)
        
        # Execute test
        success, message = test_func(config)
        
        # Calculate latency
        latency_ms = int((time.time() - start_time) * 1000)
        
        return success, message, latency_ms
    
    @staticmethod
    def get_schema(connection) -> Dict[str, Any]:
        """
        Get database schema (tables, views, etc.)
        This is a simplified version - implement actual schema retrieval based on DB type
        """
        # Simulated schema for now
        schema = {
            'tables': [
                {
                    'name': 'users',
                    'columns': ['id', 'name', 'email', 'created_at']
                },
                {
                    'name': 'products',
                    'columns': ['id', 'name', 'price', 'category', 'stock']
                },
                {
                    'name': 'orders',
                    'columns': ['id', 'user_id', 'product_id', 'quantity', 'order_date']
                },
                {
                    'name': 'categories',
                    'columns': ['id', 'name', 'description', 'parent_id']
                }
            ],
            'views': [],
            'procedures': []
        }
        
        return schema