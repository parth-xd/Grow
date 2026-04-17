#!/bin/bash
set -e

echo "🔨 Building Grow Trading Platform..."

# Check Node version
echo "📋 Node.js version:"
node --version
echo "📋 npm version:"
npm --version

# Install Python dependencies
echo "📦 Installing Python dependencies..."
pip install -r requirements.txt

# Install Node dependencies and build frontend
if [ -d "frontend" ]; then
  echo "📦 Installing frontend dependencies..."
  cd frontend
  
  # Clean npm cache to avoid issues
  npm cache clean --force
  
  # Install dependencies - verbose output
  npm install --omit=dev --verbose || {
    echo "❌ npm install failed"
    echo "Trying with legacy peer deps..."
    npm install --omit=dev --legacy-peer-deps
  }
  
  echo "🏗️  Building frontend..."
  npm run build || {
    echo "❌ Build failed - checking files..."
    ls -la
    npm run build --verbose
  }
  
  cd ..
  echo "✅ Frontend built successfully"
else
  echo "❌ Frontend directory not found"
  exit 1
fi

echo "✅ Build completed successfully!"
