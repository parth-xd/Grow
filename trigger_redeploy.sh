#!/bin/bash
# Force Render to do a clean redeploy

echo "🔄 Triggering Render redeploy via Git push..."
echo ""
echo "The deployment should auto-start in dashboard.render.com"
echo ""

# Create a dummy commit to force redeploy
cd /Users/parthsharma/Desktop/Grow

echo "📝 Creating redeploy trigger commit..."
echo "# Render redeploy trigger at $(date)" >> REDEPLOY_TRIGGER.txt

git add REDEPLOY_TRIGGER.txt
git commit -m "trigger: force clean redeploy in Render"
git push origin main

echo ""
echo "✅ Push complete. Render should start redeploying now."
echo ""
echo "🔗 Check status: https://dashboard.render.com"
echo "   Look for the Grow API service and monitor its logs"
echo ""
echo "⏱️  Wait 2-3 minutes for full deployment"
