#import requests
#from langchain_core.tools import tool

#@tool
#def fetch_external_system_log(item_id: int) -> str:
#    """
#    Fetch live administrative logs and task status updates from the external system by ID.
#    Use this tool ONLY when the user explicitly asks for system task logs, updates, or statuses by a number ID.
#    """
    # Using a free, reliable test web link endpoint
#    url = f"https://jsonplaceholder.typicode.com/todos/{item_id}"
    
#    try:
        # 1. Hit the web endpoint link
#        response = requests.get(url, timeout=5)
        
        # 2. Check if the link returned data successfully (Status 200)
 #       if response.status_code == 200:
 #           data = response.json()
            
            # 3. Format the raw JSON data into text for your LLM brain to read
 #           status = "Completed" if data.get("completed") else "Pending"
 #           return f"--- LIVE EXTERNAL DATA FOUND ---\nTask Title: {data.get('title')}\nStatus: {status}\n---------------------------------"
 #       else:
 #           return f"External API Error: System returned status code {response.status_code}"
            
 #   except requests.exceptions.RequestException as e:
 #       return f"Network Error: Unable to connect to the external system link. Details: {str(e)}"