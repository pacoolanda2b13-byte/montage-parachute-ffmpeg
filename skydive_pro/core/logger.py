"""
logger.py — Configuration centralisée du logging pour SkyDive Pro.

Usage :
    from core.logger import get_logger
    log = get_logger(__name__)
    log.info("Traitement démarré")
    log.warning("Librosa absent, audio désactivé")
    log.error("FFmpeg a échoué", exc_info=True)
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path


_CONFIGURED = False


def _configure_once() -> None:
    """Configure le root logger une seule fois."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    _CONFIGURED = True

    level_name = os.environ.get("SKYDIVE_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname).1s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Handler console (stderr pour ne pas polluer stdout JSON du CLI)
    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(formatter)
    console.setLevel(level)

    # Handler fichier (optionnel via env)
    handlers = [console]
    log_dir = os.environ.get("SKYDIVE_LOG_DIR")
    if log_dir:
        try:
            log_path = Path(log_dir) / "skydive_pro.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            file_h = logging.FileHandler(log_path, encoding="utf-8")
            file_h.setFormatter(formatter)
            file_h.setLevel(level)
            handlers.append(file_h)
        except OSError:
            pass

    root = logging.getLogger("skydive_pro")
    root.setLevel(level)
    for h in handlers:
        root.addHandler(h)
    root.propagate = False


def get_logger(name: str) -> logging.Logger:
    """Retourne un logger nommé, configuré lazy."""
    _configure_once()
    # Préfixe skydive_pro pour isoler de Flask/autres
    if not name.startswith("skydive_pro"):
        name = f"skydive_pro.{name}"
    return logging.getLogger(name)
