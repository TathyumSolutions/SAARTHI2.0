"""
Saarthi Enterprise API - Application Entry Point
"""
from app import create_app

app = create_app()

if __name__ == '__main__':
    print("🚀 Starting Saarthi application...")
    print("📍 Server running at: http://localhost:5000")
    print("📊 Database Connections: http://localhost:5000/database_connections")
    app.run(host='0.0.0.0', port=5000, debug=True)
