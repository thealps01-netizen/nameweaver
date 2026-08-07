"""logger.py — Centralised logging setup for Nameweaver.

Creates a rotating log file under %LOCALAPPDATA%/Nameweaver/logs/
and exposes a get_logger() helper used by every module.
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

# ── Log directory ──────────────────────────────────────────────────────────────
if getattr(sys, "frozen", False):
    _BASE = os.path.join(
        os.environ.get("LOCALAPPDATA", os.path.dirname(sys.executable)),
        "Nameweaver",
    )
else:
    _BASE = os.path.dirname(os.path.abspath(__file__))

LOG_DIR  = os.path.join(_BASE, "logs")
LOG_FILE = os.path.join(LOG_DIR, "nameweaver.log")

os.makedirs(LOG_DIR, exist_ok=True)

# ── Root logger ────────────────────────────────────────────────────────────────
_fmt = logging.Formatter(
    fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

_file_handler = RotatingFileHandler(
    LOG_FILE,
    maxBytes=1 * 1024 * 1024,  # 1 MB per file
    backupCount=2,              # max ~3 MB total on disk
    encoding="utf-8",
)
_file_handler.setFormatter(_fmt)
_file_handler.setLevel(logging.DEBUG)

_root = logging.getLogger("nameweaver")
_root.setLevel(logging.DEBUG)
if not _root.handlers:
    _root.addHandler(_file_handler)
_root.propagate = False


def get_logger(name: str = "nameweaver") -> logging.Logger:
    """Return a child logger under the 'nameweaver' namespace."""
    if name == "nameweaver":
        return _root
    return _root.getChild(name.replace("nameweaver.", ""))
