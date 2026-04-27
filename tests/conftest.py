"""conftest.py — add src/ to sys.path so hermes_os is importable."""

from __future__ import annotations

import sys
from pathlib import Path

# src-layout: make src/ visible as hermes_os
src_path = Path(__file__).parent.parent / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))
