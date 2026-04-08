# Saarthi Enterprise API - Complete Endpoint Documentation

## Table of Contents
1. [Authentication APIs](#authentication-apis)
2. [Workspace APIs](#workspace-apis)
3. [LLM Provider APIs](#llm-provider-apis)
4. [Database Connection APIs](#database-connection-apis)
5. [Query Execution APIs](#query-execution-apis)
6. [Datasource APIs](#datasource-apis)
7. [Analytics APIs](#analytics-apis)
8. [Chat APIs](#chat-apis)
9. [History & Audit APIs](#history--audit-apis)
10. [Export APIs](#export-apis)
11. [Model Configuration APIs](#model-configuration-apis)
12. [User Management APIs](#user-management-apis)


Start PostgreSQL in Docker on port 5433 (different from the existing 5432)
docker run --name postgres-container \
  -e POSTGRES_PASSWORD=mypassword123 \
  -e POSTGRES_USER=myflaskuser \
  -e POSTGRES_DB=myflaskdb \
  -p 5433:5432 \
  -d postgres:13

# Wait for it to start
echo "Waiting for PostgreSQL to start..."
sleep 10

# Check if Docker container is running
docker ps

psql -h localhost -p 5433 -U myflaskuser -d myflaskdb433
Unable to find image 'postgres:13' locally
13: Pulling from library/postgres
d7ecded7702a: Pull complete 
80e8d95fdf53: Pull complete 
fcfd49225910: Pull complete 
947bdcac0ea3: Pull complete 
097f34b018c0: Pull complete 
4d2c7a7b3dba: Pull complete 
8cb000c698bc: Pull complete 
ba168ff08d42: Pull complete 
bad194149a82: Pull complete 
5f1cded65589: Pull complete 
7d0650bb210f: Pull complete 
23a39b1003e9: Pull complete 
21f7a31efcb7: Pull complete 
ae52c8ce1a35: Pull complete 
Digest: sha256:4689940c683801b4ab839ab3b0a0a3555a5fe425371422310944e89eca7d8068
Status: Downloaded newer image for postgres:13
2b95f5b3497b6672d9e1335e7b3579e34ff597358d335e7522ce135ee8767946
Waiting for PostgreSQL to start...
CONTAINER ID   IMAGE         COMMAND                  CREATED          STATUS          PORTS                                         NAMES
2b95f5b3497b   postgres:13   "docker-entrypoint.s…"   12 seconds ago   Up 11 seconds   0.0.0.0:5433->5432/tcp, [::]:5433->5432/tcp   postgres-container
Password for user myflaskuser: 
psql (16.11 (Ubuntu 16.11-0ubuntu0.24.04.1), server 13.23 (Debian 13.23-1.pgdg13+1))
Type "help" for help.

myflaskdb=# SELECT 1
myflaskdb-# CREATE TABLE A (B NUMER)
myflaskdb-# SELECT * FROM A
myflaskdb-# ;
ERROR:  syntax error at or near "CREATE"
LINE 2: CREATE TABLE A (B NUMER)
        ^
myflaskdb=# SELECT 1
CREATE TABLE A (B NUMER)
SELECT * FROM A
;
ERROR:  syntax error at or near "CREATE"
LINE 2: CREATE TABLE A (B NUMER)
        ^
myflaskdb=# CREATE TABLE test_table (
    id INTEGER,
    name VARCHAR(50)
);
CREATE TABLE
myflaskdb=# INSERT INTO test_table (id, name) VALUES (1, 'Test Data');
INSERT 0 1
myflaskdb=# SELECT * FROM test_table;
 id |   name    
----+-----------
  1 | Test Data
(1 row)

myflaskdb=# \dt
             List of relations
 Schema |    Name    | Type  |    Owner    
--------+------------+-------+-------------
 public | test_table | table | myflaskuser
(1 row)

myflaskdb=# \conninfo
You are connected to database "myflaskdb" as user "myflaskuser" on host "localhost" (address "::1") at port "5433".
myflaskdb=# 


---

sudo apt-get update && sudo apt-get install -y postgresql postgresql-contrib && sudo service postgresql start && sudo -u postgres psql -c "CREATE DATABASE myflaskdb;" && sudo -u postgres psql -c "CREATE USER myflaskuser WITH PASSWORD 'mypassword123';" && sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE myflaskdb TO myflaskuser;" && sudo -u postgres psql -c "ALTER DATABASE myflaskdb OWNER TO myflaskuser;" && sudo sed -i 's/local   all             all                                     peer/local   all             all                                     md5/' /etc/postgresql/*/main/pg_hba.conf && sudo service postgresql restart && pip install psycopg2-binary flask && echo "PostgreSQL setup complete!"

## Authentication APIs

### 1. Login
**Endpoint:** `POST /api/auth/login`

**Request:**
```json
{
  "email": "user@example.com",
  "password": "password123"
}
```

**Response:**
```json
{
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "user": {
    "id": 1,
    "email": "user@example.com",
    "name": "John Doe",
    "role": "editor"
  }
}
```

### 2. Register
**Endpoint:** `POST /api/auth/register`

**Request:**
```json
{
  "email": "newuser@example.com",
  "password": "password123",
  "name": "Jane Smith"
}
```

---

## Workspace APIs

### 1. Get All Workspaces
**Endpoint:** `GET /api/workspaces`

**Headers:** `Authorization: Bearer <token>`

**Response:**
```json
{
  "workspaces": [
    {
      "id": 1,
      "name": "Sales Analytics",
      "description": "Sales team data workspace",
      "created_at": "2024-01-15T10:00:00Z",
      "database_count": 3,
      "member_count": 5
    }
  ]
}
```

### 2. Create Workspace
**Endpoint:** `POST /api/workspaces`

**Request:**
```json
{
  "name": "Marketing Insights",
  "description": "Marketing data analysis workspace"
}
```

---

## LLM Provider APIs

### 1. Get Available Providers
**Endpoint:** `GET /api/llm/providers`

**Response:**
```json
{
  "providers": [
    {
      "id": "openai",
      "name": "OpenAI",
      "models": ["gpt-4", "gpt-3.5-turbo"],
      "status": "active"
    },
    {
      "id": "anthropic",
      "name": "Anthropic",
      "models": ["claude-3-opus", "claude-3-sonnet"],
      "status": "active"
    }
  ]
}
```

### 2. Set Active Model
**Endpoint:** `POST /api/llm/models/active`

**Request:**
```json
{
  "model_id": "gpt-4",
  "provider": "OpenAI",
  "workspace_id": 1
}
```

---

## Database Connection APIs

### 1. Create Database Connection
**Endpoint:** `POST /api/databases`

**Request:**
```json
{
  "name": "Production PostgreSQL",
  "type": "PostgreSQL",
  "host": "db.example.com",
  "port": 5432,
  "database": "production_db",
  "username": "db_user",
  "password": "secure_password",
  "workspace_id": 1
}
```

### 2. Test Connection
**Endpoint:** `POST /api/databases/{db_id}/test`

**Response:**
```json
{
  "status": "success",
  "latency_ms": 45,
  "message": "Connection successful"
}
```

### 3. Get Database Schema
**Endpoint:** `GET /api/databases/{db_id}/schema`

**Response:**
```json
{
  "schema": {
    "tables": [
      {
        "name": "customers",
        "columns": [
          {"name": "id", "type": "integer", "primary_key": true},
          {"name": "name", "type": "varchar", "nullable": false},
          {"name": "email", "type": "varchar", "nullable": true}
        ]
      }
    ]
  }
}
```

---

## Query Execution APIs

### 1. Execute Natural Language Query
**Endpoint:** `POST /api/queries/execute`

**Request:**
```json
{
  "query": "Show me top 10 customers by revenue in the last quarter",
  "database_id": 1,
  "workspace_id": 1
}
```

**Response:**
```json
{
  "results": [
    {"customer_id": 101, "name": "Acme Corp", "revenue": 1500000},
    {"customer_id": 102, "name": "TechStart Inc", "revenue": 1200000}
  ],
  "sql": "SELECT customer_id, name, SUM(revenue) as revenue FROM sales WHERE date >= '2023-10-01' GROUP BY customer_id, name ORDER BY revenue DESC LIMIT 10",
  "execution_time_ms": 123,
  "row_count": 10
}
```

### 2. Translate to SQL
**Endpoint:** `POST /api/queries/translate`

**Request:**
```json
{
  "query": "Show average order value by month",
  "database_id": 1
}
```

**Response:**
```json
{
  "sql": "SELECT DATE_TRUNC('month', order_date) as month, AVG(order_total) as avg_order_value FROM orders GROUP BY DATE_TRUNC('month', order_date) ORDER BY month",
  "explanation": "This query calculates the average order value grouped by month"
}
```

### 3. Save Query
**Endpoint:** `POST /api/queries/saved`

**Request:**
```json
{
  "name": "Monthly Revenue Report",
  "query": "Show total revenue by month",
  "sql": "SELECT DATE_TRUNC('month', date) as month, SUM(revenue) FROM sales GROUP BY month",
  "workspace_id": 1
}
```

---

## Chat APIs

### 1. Create Chat Session
**Endpoint:** `POST /api/chat/sessions`

**Request:**
```json
{
  "title": "Q4 Sales Analysis",
  "workspace_id": 1
}
```

### 2. Send Message
**Endpoint:** `POST /api/chat/message`

**Request:**
```json
{
  "session_id": 1,
  "message": "What were our top selling products last month?",
  "mode": "query"
}
```

**Response:**
```json
{
  "response": "Based on the sales data, here are the top 5 products from last month...",
  "query_result": {
    "data": [...],
    "sql": "SELECT product_name, SUM(quantity) as total_sold..."
  },
  "suggestions": [
    "Show me the revenue for these products",
    "Compare with previous month"
  ]
}
```

---

## Analytics APIs

### 1. Get Dashboard Data
**Endpoint:** `GET /api/analytics/dashboard?workspace_id=1&date_range=30d`

**Response:**
```json
{
  "metrics": {
    "total_revenue": 5200000,
    "total_orders": 8543,
    "avg_order_value": 608.5,
    "growth_rate": 12.5
  },
  "charts": [
    {
      "id": "revenue_trend",
      "type": "line",
      "data": {...}
    }
  ]
}
```

### 2. Generate Insights
**Endpoint:** `POST /api/analytics/insights`

**Request:**
```json
{
  "database_id": 1,
  "table": "sales",
  "columns": ["revenue", "date", "region"]
}
```

**Response:**
```json
{
  "insights": [
    {
      "type": "trend",
      "title": "Revenue Growth",
      "description": "Revenue has increased 15% month-over-month",
      "confidence": 0.92
    },
    {
      "type": "anomaly",
      "title": "Unusual Pattern Detected",
      "description": "Sales in the Northeast region dropped 20% last week",
      "confidence": 0.87
    }
  ]
}
```

---

## Export APIs

### 1. Export to CSV
**Endpoint:** `POST /api/export/csv`

**Request:**
```json
{
  "query_id": 123
}
```

**Response:** CSV file download

### 2. Export to Excel
**Endpoint:** `POST /api/export/excel`

**Request:**
```json
{
  "query_id": 123,
  "sheet_name": "Q4 Results"
}
```

**Response:** Excel file download

### 3. Schedule Export
**Endpoint:** `POST /api/export/schedule`

**Request:**
```json
{
  "type": "report",
  "format": "excel",
  "schedule": "daily",
  "time": "08:00",
  "recipients": ["manager@example.com"],
  "workspace_id": 1
}
```

---

## List of Values (LOV) Endpoints

These endpoints populate dropdown lists and selection options in the UI:

### 1. Database Types
**Endpoint:** `GET /api/databases/types`

**Response:**
```json
{
  "types": [
    "PostgreSQL",
    "MySQL",
    "MongoDB",
    "SQL Server",
    "Oracle",
    "BigQuery",
    "Snowflake",
    "Redshift"
  ]
}
```

### 2. LLM Providers
**Endpoint:** `GET /api/llm/providers`

**Response:**
```json
{
  "providers": [
    "OpenAI",
    "Anthropic",
    "Azure OpenAI",
    "AWS Bedrock",
    "Google Vertex AI",
    "Local Models"
  ]
}
```

### 3. User Roles
**Endpoint:** `GET /api/users/roles`

**Response:**
```json
{
  "roles": [
    "admin",
    "editor",
    "viewer",
    "analyst"
  ]
}
```

### 4. Datasource Types
**Endpoint:** `GET /api/datasources/types`

**Response:**
```json
{
  "types": [
    "api",
    "file",
    "s3",
    "gcs",
    "azure_blob",
    "ftp",
    "sftp"
  ]
}
```

### 5. Chart Types
**Response:**
```json
{
  "types": [
    "bar",
    "line",
    "pie",
    "scatter",
    "area",
    "heatmap"
  ]
}
```

---

## Error Codes

| Code | Description |
|------|-------------|
| 400 | Bad Request |
| 401 | Unauthorized |
| 403 | Forbidden |
| 404 | Not Found |
| 409 | Conflict |
| 422 | Validation Error |
| 500 | Internal Server Error |

## Rate Limiting

- Default: 60 requests per minute per user
- Authenticated users: 120 requests per minute
- Admin users: Unlimited

## Pagination

For list endpoints, use query parameters:
- `page` - Page number (default: 1)
- `per_page` - Items per page (default: 20, max: 100)

Example: `GET /api/queries/history?page=2&per_page=50`
