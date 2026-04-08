import sys
from pathlib import Path

# Ensure src/ is importable before package is installed
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
