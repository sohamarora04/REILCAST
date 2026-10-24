#!/usr/bin/env python3
"""ReliCast launcher:  python run.py  [dashboard | demo | experiments | send | recv]"""
import os
import sys

if sys.version_info < (3, 8):
    sys.exit("ReliCast needs Python 3.8 or newer (found %s). Install it from python.org" % sys.version.split()[0])

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from relicast.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
