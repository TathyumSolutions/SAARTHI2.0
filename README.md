# Saarthi Enterprise API

Enterprise Data Intelligence Platform - Flask API Backend

## 🚀 Overview

Saarthi is an enterprise-grade data intelligence platform that enables natural language querying across multiple data sources using AI/LLM technology. This Flask API provides the backend infrastructure for the platform.

sudo apt-get update && sudo apt-get install -y postgresql postgresql-contrib && sudo service postgresql start && sudo -u postgres psql -c "CREATE DATABASE myflaskdb;" && sudo -u postgres psql -c "CREATE USER myflaskuser WITH PASSWORD 'mypassword123';" && sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE myflaskdb TO myflaskuser;" && sudo -u postgres psql -c "ALTER DATABASE myflaskdb OWNER TO myflaskuser;" && sudo sed -i 's/local   all             all                                     peer/local   all             all                                     md5/' /etc/postgresql/*/main/pg_hba.conf && sudo service postgresql restart && pip install psycopg2-binary flask && echo "PostgreSQL setup complete!"

## 📁 Project Structure

```
saarthi_enterprise_api/
├── app/
│   ├── __init__.py                 # Flask app factory
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes/                 # API route modules
│   │       ├── auth_routes.py      # Authentication endpoints
│   │       ├── workspace_routes.py # Workspace management
│   │       ├── llm_routes.py       # LLM provider management
│   │       ├── database_routes.py  # Database connections
│   │       ├── query_routes.py     # Query execution
│   │       ├── datasource_routes.py # Data source management
│   │       ├── analytics_routes.py  # Analytics & insights
│   │       ├── chat_routes.py      # Conversational interface
│   │       ├── history_routes.py   # Activity & audit logs
│   │       ├── export_routes.py    # Data export
│   │       ├── model_config_routes.py # Model configuration
│   │       └── user_routes.py      # User management
│   ├── models/                     # Database models
│   │   ├── user.py
│   │   ├── workspace.py
│   │   ├── database_connection.py
│   │   ├── datasource.py
│   │   ├── query.py
│   │   ├── chat.py
│   │   ├── analytics.py
│   │   ├── model_config.py
│   │   └── audit.py
│   ├── services/                   # Business logic
│   │   ├── llm_service.py
│   │   ├── database_service.py
│   │   └── export_service.py
│   ├── utils/                      # Utilities
│   │   ├── decorators.py
│   │   ├── validators.py
│   │   └── helpers.py
│   ├── static/                     # Static files
│   └── templates/                  # HTML templates
│       └── index.html              # Main application UI
├── config/
│   └── config.py                   # Configuration settings
├── tests/                          # Test suite
├── requirements.txt                # Python dependencies
├── .env.example                    # Environment variables template
├── run.py                          # Application entry point
└── README.md                       # This file
```

## 🔧 Installation

### Prerequisites
- Python 3.9+
- PostgreSQL 13+
- Redis (for caching)
- MongoDB (optional, for document storage)
- Docker Desktop** (Required to run the core database and AI stack)

### Setup Steps

1. **Clone the repository**
```bash
git clone <repository-url>
cd saarthi_enterprise_api
```

2. **Create virtual environment**
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. **Install dependencies**
```bash
pip install -r requirements.txt
```

4. **Configure environment**
```bash
cp .env.example .env
# Edit .env with your configuration
```

5. **Initialize database**
```bash
flask db init
flask db migrate
flask db upgrade
```

6. **Run the application**
```bash
python run.py
```

The API will be available at `http://localhost:5000`

## 📚 API Documentation

### Base URL
```
http://localhost:5000/api
```

### Authentication
All protected endpoints require a JWT token in the Authorization header:
```
Authorization: Bearer <your-jwt-token>
```

### Key Endpoints

#### Authentication
- `POST /api/auth/login` - User login
- `POST /api/auth/register` - User registration
- `POST /api/auth/logout` - User logout
- `GET /api/auth/profile` - Get user profile

#### Workspaces
- `GET /api/workspaces` - List all workspaces
- `POST /api/workspaces` - Create new workspace
- `GET /api/workspaces/{id}` - Get workspace details
- `PUT /api/workspaces/{id}` - Update workspace
- `DELETE /api/workspaces/{id}` - Delete workspace

#### LLM Management
- `GET /api/llm/providers` - Get available LLM providers
- `GET /api/llm/models` - Get available models
- `POST /api/llm/models/active` - Set active model
- `GET /api/llm/config` - Get LLM configuration
- `POST /api/llm/test` - Test LLM connection

#### Database Connections
- `GET /api/databases` - List database connections
- `POST /api/databases` - Create new connection
- `POST /api/databases/{id}/test` - Test connection
- `GET /api/databases/{id}/schema` - Get database schema
- `GET /api/databases/{id}/tables` - List tables

#### Query Execution
- `POST /api/queries/execute` - Execute natural language query
- `POST /api/queries/sql` - Execute raw SQL
- `POST /api/queries/translate` - Translate NL to SQL
- `GET /api/queries/history` - Get query history
- `POST /api/queries/saved` - Save query

#### Chat Interface
- `GET /api/chat/sessions` - List chat sessions
- `POST /api/chat/sessions` - Create chat session
- `POST /api/chat/message` - Send message
- `POST /api/chat/stream` - Stream response (SSE)

#### Analytics
- `GET /api/analytics/dashboard` - Get dashboard data
- `POST /api/analytics/insights` - Generate AI insights
- `POST /api/analytics/charts` - Create visualization
- `POST /api/analytics/reports` - Generate report

#### Export
- `POST /api/export/csv` - Export to CSV
- `POST /api/export/excel` - Export to Excel
- `POST /api/export/pdf` - Export to PDF
- `POST /api/export/schedule` - Schedule recurring export

## 🔐 Security

### Authentication
- JWT-based authentication
- Token expiration: 1 hour (configurable)
- Refresh token support

### Authorization
- Role-based access control (RBAC)
- Roles: Admin, Editor, Viewer, Analyst
- Workspace-level permissions

### Data Protection
- Database credentials encrypted at rest
- API keys stored securely
- SQL injection prevention
- Input validation and sanitization

## 🌐 Environment Variables

Key environment variables (see `.env.example`):

```env
# Flask
SECRET_KEY=your-secret-key
FLASK_ENV=development

# Database
DATABASE_URL=postgresql://user:pass@localhost/saarthi_db

# JWT
JWT_SECRET_KEY=your-jwt-secret

# LLM Providers
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
AZURE_OPENAI_KEY=...
```

## 🧪 Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=app tests/

# Run specific test file
pytest tests/test_auth.py
```

## 📊 Database Schema

### Main Tables
- `users` - User accounts
- `workspaces` - Workspace organization
- `database_connections` - Database configurations
- `datasources` - External data sources
- `queries` - Query execution history
- `saved_queries` - Reusable queries
- `chat_sessions` - Chat conversations
- `chat_messages` - Individual messages
- `charts` - Visualization configurations
- `reports` - Analytics reports
- `model_configurations` - LLM settings
- `audit_logs` - Compliance tracking
- `activities` - User activity tracking

## 🚢 Deployment

The easiest way to spin up the entire Saarthi platform infrastructure (Flask web server, PostgreSQL, MongoDB, Redis, Qdrant, and Ollama) is using Docker Compose.

1. **Build and Launch the Containers**
   Make sure Docker Desktop is running on your machine, then run:
   ```bash
   docker-compose build --no-cache
   docker-compose up -d
   docker exec -it saarthi20-db-1 psql -U saarthi -c "CREATE DATABASE databrige_db;" 

2. **🧠 Download the Local LLM Models (Ollama)**
   The Ollama container runs locally but starts empty. Before running the pipeline or clicking "Process", you must pull the specific models used by the multi-agent system. 
   
   Run these commands in your terminal:
   ```bash
   docker exec -it ollama ollama pull llama3
   docker exec -it ollama ollama pull llama3:latest
   docker exec -it ollama ollama pull phi3:mini

### Docker
```bash
docker build -t saarthi-api .
docker run -p 5000:5000 saarthi-api
```

### Production Checklist
- [ ] Set `FLASK_ENV=production`
- [ ] Use strong `SECRET_KEY` and `JWT_SECRET_KEY`
- [ ] Configure production database
- [ ] Set up Redis for caching
- [ ] Enable HTTPS
- [ ] Configure CORS properly
- [ ] Set up monitoring and logging
- [ ] Configure rate limiting
- [ ] Set up backup strategy

## 📝 Development

### Code Style
- Follow PEP 8 guidelines
- Use type hints where appropriate
- Write docstrings for functions
- Keep functions small and focused

### Git Workflow
1. Create feature branch from `main`
2. Make changes with descriptive commits
3. Write/update tests
4. Submit pull request
5. Code review and merge

## 🔄 API Response Format

### Success Response
```json
{
  "status": "success",
  "data": { ... },
  "message": "Operation completed",
  "timestamp": "2024-01-22T10:30:00Z"
}
```

### Error Response
```json
{
  "status": "error",
  "error": "Error message",
  "timestamp": "2024-01-22T10:30:00Z"
}
```

## 🤝 Contributing

Contributions are welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

## 📄 License

[Your License Here]

## 📞 Support

For support, email: support@saarthi.com
Documentation: https://docs.saarthi.com
hello 
