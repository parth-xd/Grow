#!/usr/bin/env python3
import json, base64, sys
from datetime import datetime

token = 'eyJraWQiOiJaTUtjVXciLCJhbGciOiJFUzI1NiJ9.eyJleHAiOjE3NzUwODk4MDAsImlhdCI6MTc3NTA0Mzc0MCwibmJmIjoxNzc1MDQzNzQwLCJzdWIiOiJ7XCJ0b2tlblJlZklkXCI6XCJlODZjMTNmMi04OGQ3LTRjZTQtYmZiZC02YmVlNTkxZDQ3YzVcIixcInZlbmRvckludGVncmF0aW9uS2V5XCI6XCJlMzFmZjIzYjA4NmI0MDZjODg3NGIyZjZkODQ5NTMxM1wiLFwidXNlckFjY291bnRJZFwiOlwiMjk2YTA3Y2MtNTM5OC00NThmLWExMzctNmZlY2YwN2YyMjI1XCIsXCJkZXZpY2VJZFwiOlwiOTRjODZhMzAtYWE0MS01NjVlLWJiNzYtMGJhZGYwMDM4Mjg0XCIsXCJzZXNzaW9uSWRcIjpcIjhkZWJmNTMyLWU4YTYtNDc1Zi04OTM1LTg3NjIwZmEwZTc0N1wiLFwiYWRkaXRpb25hbERhdGFcIjpcIno1NC9NZzltdjE2WXdmb0gvS0EwYkdHVGxhRGsvMVJkdm1RS2hqclU5WnhSTkczdTlLa2pWZDNoWjU1ZStNZERhWXBOVi9UOUxIRmtQejFFQisybTdRPT1cIixcInJvbGVcIjpcIm9yZGVyLWJhc2ljLGxpdmVfZGF0YS1iYXNpYyxub25fdHJhZGluZy1iYXNpYyxvcmRlcl9yZWFkX29ubHktYmFzaWNcIixcInNvdXJjZUlwQWRkcmVzc1wiOm51bGwsXCJ0d29GYUV4cGlyeVRzXCI6MTc3NTA4OTgwMDAwMCxcInZlbmRvck5hbWVcIjpcImdyb3d3QXBpXCJ9IiwiaXNzIjoiYXBleC1hdXRoLXByb2QtYXBwIn0.nwSxEHdTGis3hVLLczVuEeqzXWcdOXlIdYqQl3XXgzqkWKhKf4NvJPcAtOdwx00K4rfbb6KwbUoGys3wHYaYUA'
parts = token.split('.')
payload = parts[1]
padding = 4 - len(payload) % 4
if padding != 4:
    payload += '=' * padding
decoded = base64.urlsafe_b64decode(payload)
data = json.loads(decoded)

print(f"Token exp: {data.get('exp')}")
exp_time = datetime.fromtimestamp(data.get('exp'))
print(f"Expires: {exp_time}")
print(f"Now: {datetime.now()}")
print(f"Valid: {datetime.now().timestamp() < data.get('exp')}")
