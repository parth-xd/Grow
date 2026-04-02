#!/bin/bash

# Quick token refresh script
# Usage: ./refresh-token.sh

set -e

cd "$(dirname "$0")"

echo "🔄 Refreshing Groww API token..."

.venv/bin/python3 << 'EOF'
from token_refresher import check_and_refresh
import os

result = check_and_refresh()

if result:
    print("✅ Token refreshed successfully")
    
    # Show token info
    token = os.getenv('GROWW_ACCESS_TOKEN', '')
    if token:
        print(f"✅ Token: {token[:50]}...")
else:
    print("❌ Token refresh failed")
    exit(1)
EOF

echo ""
echo "📊 Checking token validity..."

.venv/bin/python3 << 'EOF'
import os, json, base64
from datetime import datetime

token = os.getenv("GROWW_ACCESS_TOKEN", "")
if token:
    try:
        parts = token.split('.')
        payload = parts[1]
        padding = 4 - len(payload) % 4
        if padding != 4:
            payload += '=' * padding
        decoded = base64.urlsafe_b64decode(payload)
        data = json.loads(decoded)
        exp = data.get('exp')
        if exp:
            exp_time = datetime.fromtimestamp(exp)
            now = datetime.now()
            diff = (exp - now.timestamp()) / 3600
            print(f"✅ Token valid, expires in {diff:.1f} hours ({exp_time})")
    except Exception as e:
        print(f"Token decode error: {e}")
else:
    print("❌ No token found")
EOF
