"""Locate installed assets and entry points in source and frozen builds."""
from pathlib import Path
import sys


def package_root():
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent
