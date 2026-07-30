"""
Configuration settings for different environments
"""
import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()

class Config:
    """Base configuration"""
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY', 'jwt-secret-key')
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=1)
    # Default is headers only - query-string tokens (needed for the SSE
    # Chain of Thought stream, since browsers' native EventSource can't set
    # custom headers) are opted into per-route with
    # @jwt_required(locations=["query_string"]), not globally. Query
    # strings routinely end up in server access logs and browser history,
    # so every other endpoint should only ever accept the Authorization
    # header.
    JWT_TOKEN_LOCATION = ['headers']
    JWT_QUERY_STRING_NAME = 'token'
    
    # CORS
    CORS_HEADERS = 'Content-Type'
    
    # Database
    #SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL', 'sqlite:///saarthi.db')
    #SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL', 'postgresql://saarthi:password@db:5432/saarthi_db')
    SQLALCHEMY_DATABASE_URI = os.getenv(
    'DATABASE_URL',
    'sqlite:///saarthi.db'
)
    # MongoDB
    MONGODB_URI = os.getenv('MONGODB_URI', 'mongodb://localhost:27017/saarthi_db')
    
    # Redis
    REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
    
    # LLM API Keys
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
    ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')
    AZURE_OPENAI_KEY = os.getenv('AZURE_OPENAI_KEY')
    AZURE_OPENAI_ENDPOINT = os.getenv('AZURE_OPENAI_ENDPOINT')
    
    # AWS
    AWS_ACCESS_KEY_ID = os.getenv('AWS_ACCESS_KEY_ID')
    AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')
    AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')

class DevelopmentConfig(Config):
    """Development configuration"""
    DEBUG = True
    TESTING = False

class ProductionConfig(Config):
    """Production configuration"""
    DEBUG = False
    TESTING = False

class TestingConfig(Config):
    """Testing configuration"""
    DEBUG = True
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///test_saarthi.db'

config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}
