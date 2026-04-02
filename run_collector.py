#!/usr/bin/env python3
import sys
sys.path.insert(0, '/Users/parthsharma/Desktop/Grow')

from scheduler import _task_collect_5min_candles

try:
    _task_collect_5min_candles()
    print("Collection task completed")
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
