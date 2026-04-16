#!/usr/bin/env python3
"""
Comprehensive codebase audit - analyze imports, dependencies, and orphaned code.
"""
import os
import re
import json
from collections import defaultdict

WORKSPACE = "/Users/parthsharma/Desktop/Grow"

def get_all_py_files():
    """Get all Python files in workspace."""
    return [f[:-3] for f in os.listdir(WORKSPACE) 
            if f.endswith('.py') and os.path.isfile(os.path.join(WORKSPACE, f))]

def extract_imports(filepath):
    """Extract all imports from a Python file."""
    imports = set()
    try:
        with open(filepath, 'r') as f:
            content = f.read()
        
        # Find all import statements
        import_pattern = r'^(?:from\s+([\w.]+)\s+)?import\s+([\w,\s*]+)'
        for match in re.finditer(import_pattern, content, re.MULTILINE):
            from_module = match.group(1)
            import_items = match.group(2)
            
            # Handle from X import Y
            if from_module:
                # Extract first module name
                base_module = from_module.split('.')[0]
                imports.add(base_module)
            
            # Handle import X
            if import_items and '*' not in import_items:
                for item in import_items.split(','):
                    item = item.strip().split(' as ')[0].strip()
                    base_module = item.split('.')[0]
                    if base_module:
                        imports.add(base_module)
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
    
    return imports

def get_local_module_imports(filepath):
    """Get imports of local modules (other Python files in this workspace)."""
    all_files = get_all_py_files()
    imports = extract_imports(filepath)
    
    local_imports = set()
    for imp in imports:
        if imp in all_files:
            local_imports.add(imp)
    
    return local_imports

def main():
    all_files = get_all_py_files()
    print(f"Found {len(all_files)} Python files\n")
    
    # Build dependency graph
    dependencies = {}  # file -> set of files it imports
    imported_by = defaultdict(set)  # file -> set of files that import it
    
    for filename in all_files:
        filepath = os.path.join(WORKSPACE, f"{filename}.py")
        local_imports = get_local_module_imports(filepath)
        dependencies[filename] = local_imports
        
        for imported in local_imports:
            imported_by[imported].add(filename)
    
    # Find orphaned files (never imported by anything)
    orphaned = []
    for filename in all_files:
        if filename not in imported_by and filename not in ['app', 'config', 'scheduler']:
            orphaned.append(filename)
    
    print("=" * 80)
    print("ORPHANED CODE (Never imported, potential candidates for removal)")
    print("=" * 80)
    for f in sorted(orphaned):
        print(f"  - {f}.py")
    print(f"\nTotal orphaned: {len(orphaned)}\n")
    
    # Find core/central modules (imported by many files)
    print("=" * 80)
    print("CORE MODULES (imported by 5+ other files)")
    print("=" * 80)
    core_modules = {}
    for module, importers in sorted(imported_by.items(), key=lambda x: -len(x[1])):
        if len(importers) >= 5:
            core_modules[module] = importers
            print(f"\n{module}.py - imported by {len(importers)} files:")
            for importer in sorted(importers):
                print(f"  - {importer}.py")
    
    # Check which files import from app.py (should be none)
    print("\n" + "=" * 80)
    print("DEPENDENCY ANALYSIS")
    print("=" * 80)
    print(f"\nFiles importing from app.py: {list(imported_by.get('app', []))}")
    
    # Find files that don't import anything (leaf nodes)
    print("\nLEAF NODES (Files that don't import any local modules):")
    leaf_nodes = [f for f in all_files if len(dependencies.get(f, set())) == 0]
    for f in sorted(leaf_nodes):
        print(f"  - {f}.py")
    print(f"Total leaf nodes: {len(leaf_nodes)}\n")
    
    # Categorize files by purpose (based on filenames)
    print("=" * 80)
    print("FILE CATEGORIZATION")
    print("=" * 80)
    
    categories = {
        'Core/API': [],
        'Testing/Debug': [],
        'Data Collection': [],
        'CLI Tools': [],
        'Database': [],
        'Trading': [],
        'Analysis': [],
        'Configuration': [],
        'Legacy/Duplicates': [],
        'Telegram': [],
        'Infrastructure': [],
    }
    
    for filename in all_files:
        if filename.startswith('_'):
            categories['Testing/Debug'].append(filename)
        elif filename.startswith('test_'):
            categories['Testing/Debug'].append(filename)
        elif 'check_' in filename:
            categories['Testing/Debug'].append(filename)
        elif filename in ['app', 'config', 'scheduler']:
            categories['Core/API'].append(filename)
        elif 'bot' in filename or 'trade' in filename or 'executor' in filename or 'trader' in filename:
            categories['Trading'].append(filename)
        elif 'db_' in filename or 'database' in filename or 'migrate' in filename:
            categories['Database'].append(filename)
        elif 'telegram' in filename:
            categories['Telegram'].append(filename)
        elif 'collect' in filename or 'fetch' in filename or 'import' in filename:
            categories['Data Collection'].append(filename)
        elif 'analyze' in filename or 'analysis' in filename or 'confidence' in filename or 'research' in filename:
            categories['Analysis'].append(filename)
        elif filename in ['token_refresher', 'verify_api', 'sanity_check']:
            categories['CLI Tools'].append(filename)
        elif filename in ['costs', 'stock_search', 'stock_thesis', 'enhanced_nlp', 'news_sentiment', 'market_context', 'options_strategies', 'predictor']:
            categories['Analysis'].append(filename)
        elif 'metadata' in filename or 'tracker' in filename or 'intelligence' in filename or 'sentiment' in filename or 'news' in filename or 'commodity' in filename:
            categories['Analysis'].append(filename)
        elif 'refresh' in filename or 'token' in filename or 'verify' in filename:
            categories['Infrastructure'].append(filename)
        elif filename in ['real_market_trading', 'live_trade_executor', 'paper_trader']:
            categories['Trading'].append(filename)
        elif filename in ['backtester', 'fno_backtester', 'backtester']:
            categories['Analysis'].append(filename)
        else:
            categories['Infrastructure'].append(filename)
    
    for category, files in categories.items():
        if files:
            print(f"\n{category}: ({len(files)} files)")
            for f in sorted(files):
                orphan_marker = " ⚠️ ORPHANED" if f in orphaned else ""
                print(f"  - {f}.py{orphan_marker}")
    
    # Summary stats
    print("\n" + "=" * 80)
    print("SUMMARY STATISTICS")
    print("=" * 80)
    print(f"Total Python files: {len(all_files)}")
    print(f"Orphaned files: {len(orphaned)} ({len(orphaned)*100//len(all_files)}%)")
    print(f"Core modules (5+ imports): {len(core_modules)}")
    print(f"Leaf nodes (0 local imports): {len(leaf_nodes)} ({len(leaf_nodes)*100//len(all_files)}%)")
    
    # Save results to JSON
    results = {
        'total_files': len(all_files),
        'orphaned': sorted(orphaned),
        'core_modules': {k: list(v) for k, v in core_modules.items()},
        'categories': {k: v for k, v in categories.items() if v},
        'leaf_nodes': sorted(leaf_nodes),
        'dependencies': {k: list(v) for k, v in dependencies.items()},
        'imported_by': {k: list(v) for k, v in imported_by.items() if v},
    }
    
    with open('audit_results.json', 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"\n✓ Results saved to audit_results.json")

if __name__ == '__main__':
    main()
