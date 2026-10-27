"""Shared test setup for the backend suite."""

import os
import sys
from pathlib import Path

# Keep tests independent of developer credentials and live observability services.
os.environ["LANGFUSE_ENABLED"] = "false"

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
