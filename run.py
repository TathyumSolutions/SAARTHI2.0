"""
Saarthi Enterprise API - Application Entry Point
"""
import os
from app import create_app

# create_app() used to always default to 'development' regardless of how
# the app was actually deployed - FLASK_ENV=production in docker-compose
# was never read anywhere, so the app never actually ran in production
# config (and the insecure default SECRET_KEY check below would never
# have fired). Read it here so the environment variable does something.
_config_name = os.getenv('FLASK_ENV', 'development')
app = create_app(_config_name)

if __name__ == '__main__':
    print("🚀 Starting Saarthi application...")
    print("📍 Server running at: http://localhost:5000")
    print("📊 Database Connections: http://localhost:5000/database_connections")
    # debug=True enables the Werkzeug interactive debugger, which allows
    # arbitrary remote code execution if this port is ever reachable -
    # never on outside of local development.
    app.run(host='0.0.0.0', port=5000, debug=(_config_name != 'production'), threaded=True)
