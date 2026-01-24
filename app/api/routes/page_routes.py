"""
Main HTML Pages Routes
Serves the frontend HTML pages with navigation
"""
from flask import Blueprint, render_template

bp = Blueprint('pages', __name__)

print( "I am in the page_routes.py file" )
# Home/Dashboard
@bp.route('/')
@bp.route('/index')
def index():
    """Main dashboard page"""
    return render_template('index.html')

# Data Sources - Unstructured Data
@bp.route('/unstructured_data')
def unstructured_data():
    print( "Rendering unstructured_data.html" )
    """Main unstructured data upload page"""
    return render_template('unstructured_data.html')

# Legacy routes (can be removed if not needed)
@bp.route('/unstructured-data/documents')
def documents():
    return render_template('unstructured/documents.html')

@bp.route('/unstructured-data/images')
def images():
    return render_template('unstructured/images.html')

@bp.route('/unstructured-data/videos')
def videos():
    return render_template('unstructured/videos.html')

@bp.route('/unstructured-data/audio')
def audio():
    return render_template('unstructured/audio.html')

@bp.route('/unstructured-data/email-archives')
def email_archives():
    return render_template('unstructured/email_archives.html')

# Data Sources - Database Connectors
@bp.route('/database/oracle')
def oracle():
    return render_template('databases/oracle.html')

@bp.route('/database/sap-hana')
def sap_hana():
    return render_template('databases/sap_hana.html')

@bp.route('/database/sap-erp')
def sap_erp():
    return render_template('databases/sap_erp.html')

@bp.route('/database/salesforce')
def salesforce():
    return render_template('databases/salesforce.html')

@bp.route('/database/microsoft-dynamics')
def microsoft_dynamics():
    return render_template('databases/microsoft_dynamics.html')

@bp.route('/database/postgresql')
def postgresql():
    return render_template('databases/postgresql.html')

@bp.route('/database/mysql')
def mysql():
    return render_template('databases/mysql.html')

@bp.route('/database/mongodb')
def mongodb():
    return render_template('databases/mongodb.html')

@bp.route('/database/snowflake')
def snowflake():
    return render_template('databases/snowflake.html')

@bp.route('/database/bigquery')
def bigquery():
    return render_template('databases/bigquery.html')

@bp.route('/database/redis')
def redis():
    return render_template('databases/redis.html')

@bp.route('/database/amazon-rds')
def amazon_rds():
    return render_template('databases/amazon_rds.html')

@bp.route('/database/azure-sql')
def azure_sql():
    return render_template('databases/azure_sql.html')

@bp.route('/database/teradata')
def teradata():
    return render_template('databases/teradata.html')

@bp.route('/database/cassandra')
def cassandra():
    return render_template('databases/cassandra.html')

# AI Models
@bp.route('/models/claude-sonnet')
def claude_sonnet():
    return render_template('models/claude_sonnet.html')

@bp.route('/models/gpt4-turbo')
def gpt4_turbo():
    return render_template('models/gpt4_turbo.html')

@bp.route('/models/llama')
def llama():
    return render_template('models/llama.html')

@bp.route('/models/gemini-pro')
def gemini_pro():
    return render_template('models/gemini_pro.html')

@bp.route('/models/mixtral')
def mixtral():
    return render_template('models/mixtral.html')

@bp.route('/models/configure-new')
def configure_new_model():
    return render_template('models/configure_new.html')

# Active Connections
@bp.route('/connections/sap-hana-prod')
def sap_hana_prod():
    return render_template('connections/sap_hana_prod.html')

@bp.route('/connections/oracle-erp')
def oracle_erp():
    return render_template('connections/oracle_erp.html')

@bp.route('/connections/salesforce-crm')
def salesforce_crm():
    return render_template('connections/salesforce_crm.html')

@bp.route('/connections/postgresql-main')
def postgresql_main():
    return render_template('connections/postgresql_main.html')

@bp.route('/connections/mongodb-analytics')
def mongodb_analytics():
    return render_template('connections/mongodb_analytics.html')

@bp.route('/connections/configure-new')
def configure_new_connection():
    return render_template('connections/configure_new.html')

# Management
@bp.route('/management/role-management')
def role_management():
    return render_template('management/role_management.html')

@bp.route('/management/user-groups')
def user_groups():
    return render_template('management/user_groups.html')

@bp.route('/management/permissions')
def permissions():
    return render_template('management/permissions.html')

@bp.route('/management/audit-logs')
def audit_logs():
    return render_template('management/audit_logs.html')

@bp.route('/management/system-logs')
def system_logs():
    return render_template('management/system_logs.html')

@bp.route('/management/power-automate')
def power_automate():
    return render_template('management/power_automate.html')

@bp.route('/management/rpa-workflows')
def rpa_workflows():
    return render_template('management/rpa_workflows.html')

# API Connectors
@bp.route('/api-connectors/rest-apis')
def rest_apis():
    return render_template('api_connectors/rest_apis.html')

@bp.route('/api-connectors/graphql')
def graphql():
    return render_template('api_connectors/graphql.html')

@bp.route('/api-connectors/webhooks')
def webhooks():
    return render_template('api_connectors/webhooks.html')

@bp.route('/api-connectors/zapier')
def zapier():
    return render_template('api_connectors/zapier.html')

@bp.route('/api-connectors/custom-workflows')
def custom_workflows():
    return render_template('api_connectors/custom_workflows.html')
