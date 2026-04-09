"""Compatibility entrypoint for `uvicorn backend.main:app`."""

from pathlib import Path
import sys

_BACKEND_DIR = Path(__file__).resolve().parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.main import app
