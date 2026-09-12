#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Start the optional local Bridge UI service."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent / 'lib'))
from ui_service import main
if __name__ == '__main__':
    sys.exit(main())
