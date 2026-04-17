#!/bin/bash
set -e

echo "🔨 Building Grow Trading Platform..."

# Install Python dependencies
echo "📦 Installing Python dependencies..."
pip install -r requirements.txt

# Install Node dependencies and build frontend
if [ -d "frontend" ]; then
  echo "📦 Installing frontend dependencies..."
  cd frontend
  npm install --omit=dev
  
  echo "🏗️  Building frontend..."
  npm run build
  
  cd ..
  echo "✅ Frontend built successfully"
else
  echo "⚠️  Frontend directory not found"
fi

echo "✅ Build completed successfully!"
