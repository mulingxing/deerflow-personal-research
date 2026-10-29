"""Run the original API with this checkout's own environment settings."""

import os
from pathlib import Path
import runpy
import sys

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env", override=True)
runpy.run_path(str(ROOT / "server.py"), run_name="__main__")
