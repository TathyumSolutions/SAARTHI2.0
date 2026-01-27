from flask import Blueprint, render_template

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def index():
    return render_template('index.html')

@main_bp.route('/database_connections')
def database_connections():
    return render_template('database_connections.html')

@main_bp.route('/unstructured_data')
def unstructured_data():
    return render_template('unstructured_data.html')