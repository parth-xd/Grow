# Render Build Failure Troubleshooting

## To Check Render Logs:
1. Go to https://dashboard.render.com
2. Select your Web Service
3. Click "Logs" tab
4. Look for errors in the "Build" section

## Common Build Failures & Solutions:

### 1. **npm ERR! ERR! code ERESOLVE**
**Cause**: Peer dependency conflicts  
**Fix**: Already added `--legacy-peer-deps` fallback to build.sh

### 2. **vite build: command not found**
**Cause**: Vite not installed in node_modules  
**Fix**: npm install failing - check if npm install output has errors
**Solution**: Make sure package.json has vite as devDependency (it does ✓)

### 3. **EACCES: permission denied**
**Cause**: File permission issues  
**Fix**: Not usually an issue on Render, but if seen:
```bash
npm cache clean --force
rm -rf node_modules
npm install --omit=dev
```

### 4. **Node.js version mismatch**
**Cause**: Render using old/new Node vs what app expects  
**Fix**: Created `.nvmrc` file specifying Node 18

### 5. **Out of memory during build**
**Cause**: Render environment is memory-constrained  
**Fix**: Check if build completes locally but fails on Render
**Solution**: May need Render Pro plan for more memory

### 6. **Build succeeds but no dist folder appears**
**Cause**: Build output not persisted  
**Fix**: Check that vite.config.js has correct outDir (it does: `dist/`)

## What To Report:
If build still fails after these fixes, share the actual error from Render logs that shows:
- The exact error message
- Which command failed (npm install? npm run build?)
- The full stack trace if available

## Current Setup:
- ✅ Node version specified in `.nvmrc` (18.x)
- ✅ Build script updated with error handling
- ✅ Legacy peer deps fallback added
- ✅ package-lock.json exists (for reproducible installs)
- ✅ Vite configured correctly
- ✅ All dependencies listed in package.json

## Next Steps:
1. Commit `.nvmrc` and updated `build.sh` to GitHub
2. Go to Render Dashboard
3. Click your Web Service
4. Click "Manual Deploy" → "Deploy latest commit"
5. Watch the "Build" logs for any errors
6. Share the specific error message if it still fails
