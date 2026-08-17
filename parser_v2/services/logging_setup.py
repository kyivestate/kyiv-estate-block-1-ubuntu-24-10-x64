"""Structured logging."""
from __future__ import annotations
import logging, sys
from pathlib import Path
LOG_DIR = Path("logs"); LOG_DIR.mkdir(exist_ok=True)

def get_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger(f"parser_v2.{name}")
    if logger.handlers: return logger
    logger.setLevel(level)
    fmt = logging.Formatter("[%(asctime)s] %(levelname)-7s %(name)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    sh = logging.StreamHandler(sys.stdout); sh.setFormatter(fmt); logger.addHandler(sh)
    fh = logging.FileHandler(LOG_DIR / "parser_v2.log", encoding="utf-8"); fh.setFormatter(fmt); logger.addHandler(fh)
    return logger
