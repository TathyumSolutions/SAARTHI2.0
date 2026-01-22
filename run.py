"""
Saarthi Enterprise API - Application Entry Point
"""
from app import create_app

app = create_app()

if __name__ == '__main__':
    print("I am currently in run.py")
    app.run(debug=True, host='0.0.0.0', port=5000)
