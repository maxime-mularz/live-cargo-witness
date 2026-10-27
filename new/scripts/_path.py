"""Make the ``lcw`` package importable when a script is run directly."""
import sys
from pathlib import Path

NEW_DIR = Path(__file__).resolve().parents[1]
if str(NEW_DIR) not in sys.path:
    sys.path.insert(0, str(NEW_DIR))
