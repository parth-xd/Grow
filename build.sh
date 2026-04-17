#!/bin/bash
set -e

echo "🔨 Building Grow Trading Platform..."
echo "📍 Current directory: $(pwd)"

# Check versions
echo "📋 Node.js version:"
node --version
echo "📋 npm version:"
npm --version

# Install Python dependencies only
echo "📦 Installing Python dependencies from $(pwd)/requirements.txt..."
pip install -r requirements.txt

# No need to build frontend - using simple HTML/JS dashboard served by Flask
echo "✅ Python dependencies installed successfully"
echo "✅ Dashboard is pure HTML/JS - no build step needed"
echo "✅ Build completed successfully!"
