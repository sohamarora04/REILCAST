#!/bin/bash
# ReliCast launcher for macOS/Linux: double-click in Finder, or ./run.command
cd "$(dirname "$0")"
python3 run.py "$@"
