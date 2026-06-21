# conftest.py — shared fixtures
import sys
import os

# Ensure the src layout is importable when running pytest from project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
