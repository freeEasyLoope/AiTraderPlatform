"""A-Share Simulation Trading System — CLI Entry."""

import sys
import os

# Force UTF-8 on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.cli.app import main

if __name__ == "__main__":
    main()
