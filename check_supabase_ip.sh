#!/bin/bash
# Check Supabase Network Access Settings

cat << 'EOF'

🔒 CHECKING SUPABASE IP WHITELIST
==================================

HOW TO CHECK IN SUPABASE DASHBOARD:
1. Go to https://app.supabase.com
2. Select your project
3. Go to Settings → Database
4. Scroll down to "Network" section
5. Look at "IP Whitelist" / "Firewall Rules"

WHAT YOU'LL SEE:
- If whitelist is ENABLED: Only IPs on the list can connect
- If whitelist is DISABLED: Any IP can connect (default for new projects)

RENDER'S IPs:
Render uses dynamic IPs from:
- 52.0.0.0/8 (AWS US regions)
- 44.55.243.0/24
- 44.55.242.0/24
- See: https://render.com/docs/regions

SOLUTION FOR SUPABASE:
═══════════════════════
Option 1: DISABLE IP WHITELIST (easiest for development)
  1. Go to Supabase Settings → Database
  2. Find "Network" or "Firewall Rules"
  3. DISABLE the IP whitelist / firewall
  4. Click "Apply"

Option 2: ADD RENDER IPs TO WHITELIST
  1. Go to Supabase Settings → Database
  2. Find "Network" or "Firewall Rules"  
  3. Add these IPs/ranges:
     - 52.0.0.0/8
     - 44.55.243.0/24
     - 44.55.242.0/24
  4. Click "Apply"

EOF

# Test if we can connect to Render's network
echo ""
echo "🧪 TESTING CONNECTION..."
echo "========================"

python3 << 'PYEOF'
import os
import socket

db_url = os.getenv('DATABASE_URL', '')
if not db_url:
    print("❌ DATABASE_URL not set")
    exit(1)

# Extract host from DATABASE_URL
# Format: postgresql://user:password@host:port/database
try:
    # postgresql://user:pass@host:port/database?sslmode=require
    parts = db_url.split('@')[1].split(':')[0]
    host = parts.split('/')[0]
    print(f"📍 Database Host: {host}")
    
    # Try to resolve DNS
    try:
        ip = socket.gethostbyname(host)
        print(f"✅ DNS resolved to: {ip}")
    except socket.gaierror as e:
        print(f"❌ DNS resolution failed: {e}")
        exit(1)
    
    # Try to connect to port 5432
    print(f"\n🔌 Testing TCP connection to {host}:5432...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5)
    
    try:
        result = sock.connect_ex((host, 5432))
        if result == 0:
            print("✅ TCP connection successful (port 5432 reachable)")
        else:
            print(f"❌ TCP connection failed (errno {result})")
            print("   This usually means:")
            print("   - IP whitelist is blocking the connection, OR")
            print("   - Firewall is blocking port 5432, OR")
            print("   - Database server is down")
    finally:
        sock.close()
        
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()

PYEOF

echo ""
echo "📋 SUMMARY:"
echo "==========="
echo "1. If TCP connection FAILED → Check Supabase IP whitelist"
echo "2. If TCP connection PASSED → Try querying database directly"
echo "3. If queries fail → Check connection string format"
