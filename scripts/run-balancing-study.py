#!/usr/bin/env python3
"""Compatibility entrypoint; equivalent to pcb-thermal study CASE [options]."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from pcb_thermal.cli import main
raise SystemExit(main(['study', *sys.argv[1:]]))
