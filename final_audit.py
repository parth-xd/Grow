#!/usr/bin/env python3
"""
Comprehensive Codebase Audit Report
Analyzing import dependencies, Flask endpoints, and orphaned code
"""

import os
import re
import json

WORKSPACE = "/Users/parthsharma/Desktop/Grow"

# Files that are DEFINITELY used (static imports in app.py)
CORE_FILES_IMPORTED_BY_APP = [
    'bot', 'costs', 'news_sentiment', 'trade_journal', 'stock_thesis',
    'auto_analyzer', 'fundamental_analysis', 'stock_search', 'trade_chart_manager',
    'thesis_manager', 'fno_trader', 'config', 'db_manager',
    'token_refresher', 'auto_metadata', 'deep_analysis', 'research_engine',
    'market_intelligence', 'commodity_tracker', 'supply_chain_collector',
    'world_news_collector', 'enhanced_nlp', 'fno_backtester',
    'thesis_analyzer', 'price_fetcher', 'backtester', 'trailing_stop',
    'trade_origin_manager', 'paper_trader', 'fii_tracker'
]

def extract_flask_endpoints(app_py_path):
    """Extract all Flask endpoints from app.py."""
    endpoints = []
    with open(app_py_path, 'r') as f:
        content = f.read()
    
    pattern = r'@app\.route\(["\']([^"\']+)["\'](?:,\s*methods=\[([^\]]+)\])?\)'
    for match in re.finditer(pattern, content):
        path = match.group(1)
        methods = match.group(2) or 'GET'
        methods = [m.strip().strip('"\'') for m in methods.split(',')]
        endpoints.append({
            'path': path,
            'methods': methods,
        })
    
    return endpoints

def categorize_file(filename):
    """Categorize a file by its purpose."""
    if filename.startswith('_'):
        return 'Test/Debug'
    if filename.startswith('test_'):
        return 'Test/Debug'
    if 'check_' in filename:
        return 'Test/Debug'
    if filename in CORE_FILES_IMPORTED_BY_APP:
        return 'Core System'
    if 'telegram' in filename:
        return 'Telegram'
    if 'bot' in filename or 'trade' in filename or 'executor' in filename or 'trader' in filename or filename == 'paper_trader':
        return 'Trading'
    if 'db_' in filename or 'database' in filename or 'migrate' in filename:
        return 'Database'
    if 'collect' in filename or 'fetch' in filename or 'import' in filename:
        return 'Data Collection'
    if 'analyze' in filename or 'analysis' in filename or 'confidence' in filename or 'research' in filename:
        return 'Analysis'
    if filename in ['token_refresher', 'verify_api', 'sanity_check']:
        return 'Infrastructure'
    if filename in ['costs', 'stock_search', 'stock_thesis', 'enhanced_nlp', 'news_sentiment',
                    'market_context', 'options_strategies', 'predictor']:
        return 'Analysis'
    if 'metadata' in filename or 'tracker' in filename or 'intelligence' in filename:
        return 'Analysis'
    if 'real_market' in filename or 'live_trade' in filename:
        return 'Trading'
    if 'backtest' in filename:
        return 'Analysis'
    if filename == 'scheduler':
        return 'Infrastructure'
    if filename == 'config':
        return 'Core System'
    if filename == 'app':
        return 'Core System'
    return 'Other'

def main():
    print("=" * 100)
    print("COMPREHENSIVE CODEBASE AUDIT - TRADING BOT SYSTEM")
    print("=" * 100)
    print()
    
    # Get all files
    all_files = sorted([f[:-3] for f in os.listdir(WORKSPACE) 
                       if f.endswith('.py') and os.path.isfile(os.path.join(WORKSPACE, f))])
    
    # Extract Flask endpoints
    app_py = os.path.join(WORKSPACE, 'app.py')
    endpoints = extract_flask_endpoints(app_py)
    
    print(f"SYSTEM OVERVIEW")
    print("-" * 100)
    print(f"Total Python files: {len(all_files)}")
    print(f"Total Flask endpoints: {len(endpoints)}")
    print(f"Files imported by app.py: {len(CORE_FILES_IMPORTED_BY_APP)}")
    print()
    
    # Categorize all files
    categories = {}
    for f in all_files:
        cat = categorize_file(f)
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(f)
    
    print("1. FILE CATEGORIZATION")
    print("-" * 100)
    for cat in sorted(categories.keys()):
        files = categories[cat]
        print(f"\n{cat}: ({len(files)} files)")
        for f in sorted(files):
            used_by_app = " ✓" if f in CORE_FILES_IMPORTED_BY_APP else ""
            print(f"  - {f}.py{used_by_app}")
    
    # Identify truly orphaned code (not imported by app, not core, not test)
    orphaned = []
    for f in all_files:
        cat = categorize_file(f)
        if f not in CORE_FILES_IMPORTED_BY_APP and cat not in ['Test/Debug', 'Core System', 'Infrastructure'] and not f.startswith('_'):
            # Check if it's actually called from app.py dynamically
            with open(os.path.join(WORKSPACE, f'{f}.py'), 'r') as file:
                content = file.read()
                # Check if this is a standalone CLI tool or utility
                has_main = '__name__' in content and '__main__' in content
                if has_main:
                    orphaned.append((f, 'CLI Tool'))
                else:
                    orphaned.append((f, 'Potentially Unused'))
    
    if orphaned:
        print()
        print()
        print("2. POTENTIALLY ORPHANED CODE (Never explicitly imported)")
        print("-" * 100)
        print(f"\n⚠️  Found {len(orphaned)} files that may be dead code:")
        print()
        for f, reason in sorted(orphaned):
            print(f"  - {f}.py ({reason})")
            # Try to infer purpose
            if 'simulate' in f or 'find' in f or 'verify' in f or 'list' in f:
                print(f"    → Purpose: Likely a CLI/debugging utility")
            elif 'migrate' in f or 'aggregate' in f:
                print(f"    → Purpose: Likely a one-time data migration")
            elif 'analyze' in f or 'threshold' in f:
                print(f"    → Purpose: Analysis/research tool")
    
    # List all Flask endpoints
    print()
    print()
    print("3. FLASK ENDPOINTS DEFINED IN APP.PY")
    print("-" * 100)
    print(f"\nTotal endpoints: {len(endpoints)}\n")
    
    # Group by prefix
    endpoint_groups = {}
    for ep in endpoints:
        path = ep['path']
        if path == '/':
            group = 'Root'
        else:
            # Get first part of path
            parts = path.split('/')
            group = parts[1] if len(parts) > 1 else 'Other'
        
        if group not in endpoint_groups:
            endpoint_groups[group] = []
        endpoint_groups[group].append(ep)
    
    for group in sorted(endpoint_groups.keys()):
        eps = endpoint_groups[group]
        print(f"{group.upper()} ({len(eps)} endpoints):")
        for ep in sorted(eps, key=lambda x: x['path']):
            print(f"  {ep['methods'][0]:6} {ep['path']}")
        print()
    
    # Frontend API calls
    print()
    print("4. FRONTEND API CALLS (from index.html)")
    print("-" * 100)
    html_path = os.path.join(WORKSPACE, 'index.html')
    if os.path.exists(html_path):
        with open(html_path, 'r') as f:
            html_content = f.read()
        
        # Find API calls
        api_pattern = r"['\"]\/api\/[^'\"]*['\"]"
        frontend_apis = set(re.findall(api_pattern, html_content))
        frontend_apis = [api.strip('\'"') for api in frontend_apis]
        
        print(f"\nFound {len(set(frontend_apis))} unique API calls in frontend:\n")
        for api in sorted(set(frontend_apis)):
            print(f"  {api}")
        
        # Check for unused endpoints
        unused_endpoints = []
        for ep in endpoints:
            if ep['path'] not in [api for api in frontend_apis]:
                unused_endpoints.append(ep)
        
        if unused_endpoints:
            print()
            print(f"\n⚠️  Endpoints NOT called from frontend ({len(unused_endpoints)}):")
            for ep in sorted(unused_endpoints, key=lambda x: x['path'])[:30]:
                print(f"  {ep['methods'][0]:6} {ep['path']}")
            if len(unused_endpoints) > 30:
                print(f"  ... and {len(unused_endpoints) - 30} more")
    
    # Summary
    print()
    print()
    print("5. SUMMARY & RECOMMENDATIONS")
    print("-" * 100)
    print()
    print(f"✓ Core Production Files: {len(CORE_FILES_IMPORTED_BY_APP)}")
    print(f"✓ Test/Debug Files: {len(categories.get('Test/Debug', []))}")
    print(f"✓ CLI Tools: {sum(1 for f, r in orphaned if r == 'CLI Tool')}")
    print(f"⚠️  Potentially Orphaned: {len(orphaned)}")
    print()
    print("RECOMMENDATIONS:")
    print()
    print("1. SAFE TO REMOVE (Test/Debug Only):")
    for f in sorted(categories.get('Test/Debug', []))[:10]:
        print(f"   - {f}.py")
    if len(categories.get('Test/Debug', [])) > 10:
        print(f"   ... and {len(categories.get('Test/Debug', [])) - 10} more test files")
    
    print()
    print("2. REVIEW FOR REMOVAL (One-time Utilities):")
    cli_tools = [f for f, r in orphaned if r == 'CLI Tool']
    for f in sorted(cli_tools):
        print(f"   - {f}.py")
    
    print()
    print("3. CORE PRODUCTION FILES (KEEP):")
    for f in sorted(CORE_FILES_IMPORTED_BY_APP)[:15]:
        print(f"   - {f}.py")
    if len(CORE_FILES_IMPORTED_BY_APP) > 15:
        print(f"   ... and {len(CORE_FILES_IMPORTED_BY_APP) - 15} more")

if __name__ == '__main__':
    main()
