#!/usr/bin/env python3
"""
Quick token refresh utility
Usage: python3 refresh_token_cli.py [--check|--refresh]
"""

import os
import sys
import json
import base64
from datetime import datetime

def check_token():
    """Check current token validity."""
    token = os.getenv("GROWW_ACCESS_TOKEN", "")
    if not token:
        print("❌ No token found in environment")
        return False
    
    try:
        parts = token.split('.')
        if len(parts) != 3:
            print("❌ Invalid token format")
            return False
        
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
            
            if diff > 0:
                print(f"✅ Token is valid")
                print(f"   Expires at: {exp_time}")
                print(f"   Expires in: {diff:.1f} hours")
                return True
            else:
                print(f"❌ Token expired {-diff:.1f} hours ago")
                return False
    except Exception as e:
        print(f"❌ Token check failed: {e}")
        return False

def refresh():
    """Refresh the token."""
    print("🔄 Refreshing Groww API token...")
    
    try:
        from token_refresher import check_and_refresh
        result = check_and_refresh()
        
        if result:
            print("✅ Token refreshed successfully")
            # Now check it
            print()
            return check_token()
        else:
            print("❌ Token refresh failed")
            return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "--check"
    
    if action == "--refresh":
        success = refresh()
        sys.exit(0 if success else 1)
    elif action == "--check":
        success = check_token()
        sys.exit(0 if success else 1)
    else:
        print("Usage: python3 refresh_token_cli.py [--check|--refresh]")
        print("  --check   : Check token validity (default)")
        print("  --refresh : Refresh token")
        sys.exit(1)

if __name__ == "__main__":
    main()
