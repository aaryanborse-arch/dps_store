import os
import base64

key = os.environ.get('JODO_API_KEY')
secret = os.environ.get('JODO_API_SECRET')

print(f"Key from env: {key}")
print(f"Secret from env: {secret}")

auth_string = base64.b64encode(f'{key}:{secret}'.encode()).decode()
print(f"Built Authorization value: Basic {auth_string}")