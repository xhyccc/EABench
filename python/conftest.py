"""Pytest configuration for EABench Python tests.

This file is automatically discovered by pytest and adds the
``python/`` directory to ``sys.path`` so that ``src.*`` imports
resolve correctly when tests are run from the repo root or from
within the ``python/`` directory.
"""

import sys
import os

# Ensure the python/ directory (this file's parent) is on sys.path so that
# `from src.xxx import ...` works in all test modules.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)
