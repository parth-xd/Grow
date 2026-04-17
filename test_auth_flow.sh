#!/bin/bash
# Test the authentication flow end-to-end

set -e

API_URL="${VITE_API_URL:-https://groww-api-m853.onrender.com}"
FRONTEND_URL="${FRONTEND_URL:-https://grow-ten.vercel.app}"

echo "🧪 Testing Grow Authentication Flow"
echo "=================================="
echo ""
echo "Backend API: $API_URL"
echo "Frontend: $FRONTEND_URL"
echo ""

# Test 1: Health check
echo "TEST 1: Health Check"
echo "-------------------"
curl -s "$API_URL/api/health" | jq . || echo "❌ Health check failed"
echo ""

# Test 2: Check environment variables
echo "TEST 2: Configuration Check"
echo "----------------------------"
echo "GOOGLE_CLIENT_ID: ${GOOGLE_CLIENT_ID:-(not set)}"
echo "DATABASE_URL: ${DATABASE_URL:-(not set)}"
echo "JWT_SECRET: ${JWT_SECRET:-(not set)}"
echo "FLASK_ENV: ${FLASK_ENV:-(not set)}"
echo ""

# Test 3: Direct database connection
echo "TEST 3: Direct Database Connection Test"
echo "---------------------------------------"
if [ -n "$DATABASE_URL" ]; then
  python3 << 'EOF'
import os
from sqlalchemy import create_engine, text

db_url = os.getenv('DATABASE_URL')
print(f"Testing connection to: {db_url[:50]}...")

try:
    engine = create_engine(
        db_url,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 10},
        pool_timeout=10,
    )
    
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1"))
        print("✅ Direct database connection successful")
except Exception as e:
    print(f"❌ Direct database connection failed: {e}")
    import traceback
    traceback.print_exc()
EOF
else
  echo "❌ DATABASE_URL not set in environment"
fi
echo ""

echo "✅ Diagnostic tests complete"
