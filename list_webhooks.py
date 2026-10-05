import os
import base64
import requests

base_url = os.environ.get('JODO_BASE_URL')
api_key = os.environ.get('JODO_API_KEY')
api_secret = os.environ.get('JODO_API_SECRET')

auth_string = base64.b64encode(f'{api_key}:{api_secret}'.encode()).decode()

response = requests.get(
    f'{base_url}/api/v1/integrations/erp/webhooks',
    headers={
        'Authorization': f'Basic {auth_string}',
        'Content-Type': 'application/json'
    }
)

print(f"Status Code: {response.status_code}")
print(f"Response: {response.text}")