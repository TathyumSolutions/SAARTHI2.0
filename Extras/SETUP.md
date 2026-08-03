# Saarthi Enterprise API - Setup Guide

## Quick Start

### 1. Prerequisites Check
```bash
# Check Python version (3.9+ required)
python --version

# Check PostgreSQL installation
psql --version

# Check Redis installation
redis-cli --version
```

### 2. Clone and Setup Virtual Environment
```bash
# Navigate to project directory
cd saarthi_enterprise_api

# Create virtual environment
python -m venv venv

# Activate virtual environment
# On Linux/Mac:
source venv/bin/activate

# On Windows:
venv\Scripts\activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables
```bash
# Copy example environment file
cp .env.example .env

# Edit .env file with your configuration
nano .env  # or use your preferred editor
```

**Required Configuration:**
- `SECRET_KEY` - Generate a secure random key
- `DATABASE_URL` - PostgreSQL connection string
- `JWT_SECRET_KEY` - JWT authentication secret
- `OPENAI_API_KEY` - OpenAI API key (if using OpenAI)
- `ANTHROPIC_API_KEY` - Anthropic API key (if using Claude)

### 5. Setup Database
```bash
# Create database
createdb saarthi_db

# Initialize Flask-Migrate
flask db init

# Create migration
flask db migrate -m "Initial migration"

# Apply migration
flask db upgrade
```

### 6. Run the Application
```bash
# Development mode
python run.py

# Or with Flask CLI
flask run

# Production mode with Gunicorn
gunicorn --bind 0.0.0.0:5000 --workers 4 run:app
```

### 7. Test the Installation
```bash
# Test health endpoint
curl http://localhost:5000/health

# Expected response:
# {"status": "healthy", "service": "Saarthi Enterprise API"}
```

## Docker Setup (Alternative)

### Using Docker Compose
```bash
# Build and start all services
docker-compose up -d

# View logs
docker-compose logs -f

# Stop services
docker-compose down
```

This will start:
- Flask API (port 5000)
- PostgreSQL (port 5432)
- Redis (port 6379)
- MongoDB (port 27017)

## Next Steps

### 1. Create Admin User
```bash
flask shell
```

```python
from app import db
from app.models import User

admin = User(
    email='admin@example.com',
    name='Admin User',
    role='admin',
    status='active'
)
admin.set_password('secure_password')
db.session.add(admin)
db.session.commit()
```

### 2. Test API Endpoints
Use the provided Postman collection or test with curl:

```bash
# Register a user
curl -X POST http://localhost:5000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "password": "password123",
    "name": "Test User"
  }'

# Login
curl -X POST http://localhost:5000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "password": "password123"
  }'
```

### 3. Access the UI
Open your browser and navigate to:
```
http://localhost:5000
```

## Development Workflow

### Making Changes
1. Create a feature branch
2. Make your changes
3. Run tests: `pytest`
4. Commit and push

### Database Migrations
```bash
# After model changes
flask db migrate -m "Description of changes"
flask db upgrade
```

### Running Tests
```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=app tests/

# Run specific test file
pytest tests/test_auth.py -v
```

## Troubleshooting

### Common Issues

**1. Database connection error**
- Check PostgreSQL is running: `sudo service postgresql status`
- Verify DATABASE_URL in .env
- Ensure database exists: `psql -l`

**2. Module import errors**
- Ensure virtual environment is activated
- Reinstall dependencies: `pip install -r requirements.txt`

**3. Permission errors**
- Check file permissions
- Ensure virtual environment ownership

**4. Port already in use**
- Find process: `lsof -i :5000`
- Kill process or use different port

### Getting Help
- Check logs: `tail -f logs/app.log`
- Enable debug mode: Set `FLASK_ENV=development`
- Check API_DOCUMENTATION.md for endpoint details

## Production Deployment

### Environment Setup
1. Set `FLASK_ENV=production`
2. Use strong secret keys
3. Configure production database
4. Set up SSL/TLS certificates
5. Configure reverse proxy (Nginx)
6. Set up monitoring and logging
7. Configure backups

### Security Checklist
- [ ] Change default secret keys
- [ ] Use environment variables for secrets
- [ ] Enable HTTPS
- [ ] Configure CORS properly
- [ ] Set up rate limiting
- [ ] Enable audit logging
- [ ] Regular security updates
- [ ] Database backups configured

## Support

For issues or questions:
- Check documentation in README.md
- Review API_DOCUMENTATION.md
- Contact: support@saarthi.com
