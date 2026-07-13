# Saarthi Enterprise - HTML Pages Structure

## Overview

The Saarthi Enterprise platform now includes **44 separate HTML pages** with consistent navigation. All pages share the same left sidebar menu, allowing seamless navigation throughout the application.

## Page Structure

### Base Template
All pages extend from `base.html` which includes:
- Header with logo and mode selector
- Left sidebar with all navigation menus
- Content area for page-specific content
- Consistent styling and JavaScript

### Navigation Features
- ✅ Same left sidebar (RHS menu) on all pages
- ✅ Click menu items to navigate between pages
- ✅ All pages open in the same window
- ✅ Active page highlighting
- ✅ Collapsible sub-menus
- ✅ Responsive design

## Complete Page List

### 1. Data Sources - Unstructured Data (RAG)
| Page | Route | File |
|------|-------|------|
| Documents | `/unstructured-data/documents` | `templates/unstructured/documents.html` |
| Images | `/unstructured-data/images` | `templates/unstructured/images.html` |
| Videos | `/unstructured-data/videos` | `templates/unstructured/videos.html` |
| Audio Files | `/unstructured-data/audio` | `templates/unstructured/audio.html` |
| Email Archives | `/unstructured-data/email-archives` | `templates/unstructured/email_archives.html` |

### 2. Data Sources - Database Connectors
| Page | Route | File |
|------|-------|------|
| Oracle Database | `/database/oracle` | `templates/databases/oracle.html` |
| SAP HANA | `/database/sap-hana` | `templates/databases/sap_hana.html` |
| SAP ERP | `/database/sap-erp` | `templates/databases/sap_erp.html` |
| Salesforce | `/database/salesforce` | `templates/databases/salesforce.html` |
| Microsoft Dynamics | `/database/microsoft-dynamics` | `templates/databases/microsoft_dynamics.html` |
| PostgreSQL | `/database/postgresql` | `templates/databases/postgresql.html` |
| MySQL | `/database/mysql` | `templates/databases/mysql.html` |
| MongoDB | `/database/mongodb` | `templates/databases/mongodb.html` |
| Snowflake | `/database/snowflake` | `templates/databases/snowflake.html` |
| Google BigQuery | `/database/bigquery` | `templates/databases/bigquery.html` |
| Redis | `/database/redis` | `templates/databases/redis.html` |
| Amazon RDS | `/database/amazon-rds` | `templates/databases/amazon_rds.html` |
| Azure SQL | `/database/azure-sql` | `templates/databases/azure_sql.html` |
| Teradata | `/database/teradata` | `templates/databases/teradata.html` |
| Apache Cassandra | `/database/cassandra` | `templates/databases/cassandra.html` |

### 3. AI & Models
| Page | Route | File |
|------|-------|------|
| Claude 4.5 Sonnet | `/models/claude-sonnet` | `templates/models/claude_sonnet.html` |
| GPT-4 Turbo | `/models/gpt4-turbo` | `templates/models/gpt4_turbo.html` |
| Llama 3.3 70B | `/models/llama` | `templates/models/llama.html` |
| Gemini Pro | `/models/gemini-pro` | `templates/models/gemini_pro.html` |
| Mixtral 8x7B | `/models/mixtral` | `templates/models/mixtral.html` |
| Configure New Model | `/models/configure-new` | `templates/models/configure_new.html` |

### 4. Active Connections
| Page | Route | File |
|------|-------|------|
| SAP HANA Production | `/connections/sap-hana-prod` | `templates/connections/sap_hana_prod.html` |
| Oracle ERP Database | `/connections/oracle-erp` | `templates/connections/oracle_erp.html` |
| Salesforce CRM | `/connections/salesforce-crm` | `templates/connections/salesforce_crm.html` |
| PostgreSQL Main | `/connections/postgresql-main` | `templates/connections/postgresql_main.html` |
| MongoDB Analytics | `/connections/mongodb-analytics` | `templates/connections/mongodb_analytics.html` |
| Configure New Connection | `/connections/configure-new` | `templates/connections/configure_new.html` |

### 5. Management
| Page | Route | File |
|------|-------|------|
| Role Management | `/management/role-management` | `templates/management/role_management.html` |
| User Groups | `/management/user-groups` | `templates/management/user_groups.html` |
| Permissions | `/management/permissions` | `templates/management/permissions.html` |
| Audit Logs | `/management/audit-logs` | `templates/management/audit_logs.html` |
| System Logs | `/management/system-logs` | `templates/management/system_logs.html` |
| Power Automate | `/management/power-automate` | `templates/management/power_automate.html` |
| RPA Workflows | `/management/rpa-workflows` | `templates/management/rpa_workflows.html` |

### 6. API Connectors
| Page | Route | File |
|------|-------|------|
| REST APIs | `/api-connectors/rest-apis` | `templates/api_connectors/rest_apis.html` |
| GraphQL | `/api-connectors/graphql` | `templates/api_connectors/graphql.html` |
| Webhooks | `/api-connectors/webhooks` | `templates/api_connectors/webhooks.html` |
| Zapier Integration | `/api-connectors/zapier` | `templates/api_connectors/zapier.html` |
| Custom Workflows | `/api-connectors/custom-workflows` | `templates/api_connectors/custom_workflows.html` |

### 7. Home/Dashboard
| Page | Route | File |
|------|-------|------|
| Main Dashboard | `/` or `/index` | `templates/index.html` |

## Total Count: 45 Pages

## How It Works

### Navigation Flow
```
User clicks on menu item in left sidebar
    ↓
Flask route handler receives request
    ↓
Renders appropriate HTML template
    ↓
Page loads with same sidebar
    ↓
User can click another menu item to navigate
```

### Example Navigation

```python
# User clicks "SAP HANA" in Database Connectors
# Browser navigates to: /database/sap-hana

# Flask route handler:
@bp.route('/database/sap-hana')
def sap_hana():
    return render_template('databases/sap_hana.html')

# Template renders with base.html sidebar
# All menu items remain accessible
```

## Customizing Pages

### To Add Content to a Page:

1. **Open the HTML file:**
   ```bash
   vim app/templates/databases/sap_hana.html
   ```

2. **Modify the content block:**
   ```html
   {% block content %}
   <div style="max-width: 1200px;">
       <h1>Your Custom Content</h1>
       
       <!-- Add your forms, tables, charts here -->
       
   </div>
   {% endblock %}
   ```

3. **Add page-specific JavaScript:**
   ```html
   {% block extra_scripts %}
   <script>
       // Your custom JavaScript
       function myFunction() {
           console.log('Custom function');
       }
   </script>
   {% endblock %}
   ```

4. **Add page-specific CSS:**
   ```html
   {% block extra_styles %}
   <style>
       .my-custom-class {
           color: var(--accent-green);
       }
   </style>
   {% endblock %}
   ```

## Adding API Calls to Pages

### Example: Fetching Data

```html
{% block extra_scripts %}
<script>
    async function loadData() {
        try {
            const response = await fetch('/api/databases/1/schema', {
                headers: {
                    'Authorization': 'Bearer ' + localStorage.getItem('token')
                }
            });
            const data = await response.json();
            console.log('Data:', data);
            
            // Update page with data
            displayData(data);
        } catch (error) {
            console.error('Error:', error);
        }
    }

    function displayData(data) {
        // Render data on page
    }

    // Load data when page loads
    document.addEventListener('DOMContentLoaded', loadData);
</script>
{% endblock %}
```

### Example: Submitting Form

```html
{% block content %}
<div style="max-width: 1200px;">
    <form id="configForm">
        <input type="text" name="host" placeholder="Database Host">
        <input type="number" name="port" placeholder="Port">
        <button type="submit">Connect</button>
    </form>
</div>
{% endblock %}

{% block extra_scripts %}
<script>
    document.getElementById('configForm').addEventListener('submit', async (e) => {
        e.preventDefault();
        
        const formData = new FormData(e.target);
        const data = Object.fromEntries(formData);
        
        try {
            const response = await fetch('/api/databases', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer ' + localStorage.getItem('token')
                },
                body: JSON.stringify(data)
            });
            
            const result = await response.json();
            alert('Success: ' + result.message);
        } catch (error) {
            alert('Error: ' + error.message);
        }
    });
</script>
{% endblock %}
```

## Features in Each Page Template

### Current Template Includes:
- ✅ Page title and description
- ✅ Configuration panel with form inputs
- ✅ Data table with sample data
- ✅ Action buttons (Edit, Delete)
- ✅ Consistent styling matching the theme
- ✅ Ready for customization

### Each Page Has:
```html
1. Header Section
   - Title
   - Description

2. Configuration Panel
   - Settings form
   - Save button

3. Data Table
   - Sample rows
   - Action buttons
   - Status badges

4. Script Section
   - Page-specific JavaScript
   - API integration ready
```

## Directory Structure

```
app/templates/
├── base.html                          # Base template with sidebar
├── index.html                         # Main dashboard
├── unstructured/                      # Unstructured data pages
│   ├── documents.html
│   ├── images.html
│   ├── videos.html
│   ├── audio.html
│   └── email_archives.html
├── databases/                         # Database connector pages
│   ├── oracle.html
│   ├── sap_hana.html
│   ├── sap_erp.html
│   ├── salesforce.html
│   ├── microsoft_dynamics.html
│   ├── postgresql.html
│   ├── mysql.html
│   ├── mongodb.html
│   ├── snowflake.html
│   ├── bigquery.html
│   ├── redis.html
│   ├── amazon_rds.html
│   ├── azure_sql.html
│   ├── teradata.html
│   └── cassandra.html
├── models/                            # AI model pages
│   ├── claude_sonnet.html
│   ├── gpt4_turbo.html
│   ├── llama.html
│   ├── gemini_pro.html
│   ├── mixtral.html
│   └── configure_new.html
├── connections/                       # Active connection pages
│   ├── sap_hana_prod.html
│   ├── oracle_erp.html
│   ├── salesforce_crm.html
│   ├── postgresql_main.html
│   ├── mongodb_analytics.html
│   └── configure_new.html
├── management/                        # Management pages
│   ├── role_management.html
│   ├── user_groups.html
│   ├── permissions.html
│   ├── audit_logs.html
│   ├── system_logs.html
│   ├── power_automate.html
│   └── rpa_workflows.html
└── api_connectors/                    # API connector pages
    ├── rest_apis.html
    ├── graphql.html
    ├── webhooks.html
    ├── zapier.html
    └── custom_workflows.html
```

## Testing Navigation

### Start the Flask Server:
```bash
python run.py
```

### Open Browser:
```
http://localhost:5000
```

### Test Navigation:
1. Click any menu item in the left sidebar
2. Page should load with same sidebar
3. Click another menu item
4. Navigation should work seamlessly
5. Active page should be highlighted

## Next Steps

1. **Customize each page** with specific functionality
2. **Add API integration** for data fetching
3. **Implement forms** for configuration
4. **Add data visualizations** where needed
5. **Connect to backend APIs** for real functionality

## Notes

- All pages use the same color scheme and styling
- Navigation is client-side (no page reload needed in future if using AJAX)
- Pages are ready for GET/POST operations
- Template structure makes it easy to add new pages
- Sidebar navigation is consistent across all pages
