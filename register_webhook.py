import os
import base64
import requests
import secrets

base_url = os.environ.get('JODO_BASE_URL')
api_key = os.environ.get('JODO_API_KEY')
api_secret = os.environ.get('JODO_API_SECRET')

auth_string = base64.b64encode(f'{api_key}:{api_secret}'.encode()).decode()

webhook_secret = secrets.token_hex(32)
print(f"Generated webhook secret (SAVE THIS): {webhook_secret}")

payload = {
    "event_code": "page.payment.settled",
    "url": "https://dps-store.vercel.app/jodo/webhook",
    "failure_notification_email": "aaryanrb0612@gmail.com",
    "secret_key": webhook_secret
}

response = requests.post(
    f'{base_url}/api/v1/integrations/erp/webhooks',
    headers={
        'Authorization': f'Basic {auth_string}',
        'Content-Type': 'application/json'
    },
    json=payload
)

print(f"Status Code: {response.status_code}")
print(f"Response: {response.text}")