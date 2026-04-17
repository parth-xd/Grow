#!/bin/bash
set -e

echo "🔨 Building Grow Trading Platform..."
echo "📍 Current directory: $(pwd)"

# Check versions
echo "📋 Node.js version:"
node --version
echo "📋 npm version:"
npm --version

# Install Python dependencies
echo "📦 Installing Python dependencies from $(pwd)/requirements.txt..."
pip install -r requirements.txt

# Install Node dependencies and build frontend
if [ ! -d "frontend" ]; then
  echo "❌ Frontend directory not found at $(pwd)/frontend"
  exit 1
fi

echo "📂 Entering frontend directory..."
cd frontend
echo "📍 Now in: $(pwd)"

# Verify package.json exists
if [ ! -f "package.json" ]; then
  echo "❌ package.json not found in frontend directory"
  exit 1
fi

echo "📦 Installing frontend dependencies..."
npm cache clean --force
npm install --omit=dev

# Verify vite is installed
if ! npm list vite > /dev/null 2>&1; then
  echo "⚠️  vite not found, trying with legacy peer deps..."
  npm install --omit=dev --legacy-peer-deps
fi

# Double check vite is available
echo "🔍 Checking for vite..."
npm list vite || {
  echo "❌ vite still not found after install"
  echo "Installed packages:"
  ls -la node_modules | head -20
  exit 1
}

echo "🏗️  Building frontend with vite..."
npm run build

if [ ! -d "dist" ]; then
  echo "❌ Build failed - dist directory not created"
  exit 1
fi

echo "✅ Frontend build successful"

# Return to root directory
cd ..
echo "📍 Back in: $(pwd)"
echo "✅ Build completed successfully!"
