"""
Test Authentication Routes
"""
import pytest
from app import create_app, db
from app.models import User
from app.models.chat import ChatSession
from app.routes.chat_routes import _load_chat_history_for_session

@pytest.fixture
def app():
    """Create application for testing"""
    app = create_app('testing')
    
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()

@pytest.fixture
def client(app):
    """Create test client"""
    return app.test_client()

@pytest.fixture
def auth_headers(client):
    """Get authentication headers"""
    # Create test user
    response = client.post('/api/auth/register', json={
        'email': 'test@example.com',
        'password': 'password123',
        'name': 'Test User'
    })
    
    # Login
    response = client.post('/api/auth/login', json={
        'email': 'test@example.com',
        'password': 'password123'
    })
    
    token = response.json['access_token']
    return {'Authorization': f'Bearer {token}'}

def test_register_user(client):
    """Test user registration"""
    # TODO: Implement test
    pass

def test_login_user(client):
    """Test user login"""
    # TODO: Implement test
    pass

def test_get_profile(client, auth_headers):
    """Test getting user profile"""
    # TODO: Implement test
    pass

def test_logout_user(client, auth_headers):
    """Test user logout"""
    # TODO: Implement test
    pass


def test_load_chat_history_for_session_returns_saved_chat(app):
    """Session history should be restored from the database before the next answer is generated."""
    with app.app_context():
        user = User(email='history@example.com', password='password123', name='History User')
        db.session.add(user)
        db.session.commit()

        session = ChatSession(
            session_id='sess-123',
            title='Follow-up chat',
            chat_history='<div>Earlier assistant answer</div>',
            company_code='ACME',
            user_id=user.id,
        )
        db.session.add(session)
        db.session.commit()

        assert _load_chat_history_for_session('sess-123', user) == '<div>Earlier assistant answer</div>'
