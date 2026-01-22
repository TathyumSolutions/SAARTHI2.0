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

---

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
