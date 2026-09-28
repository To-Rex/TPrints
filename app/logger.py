"""Log: faylga (rotatsiya bilan) + UI uchun xotiradagi ring bufer."""
import logging
import os
import threading
from collections import deque
from logging.handlers import RotatingFileHandler

from .config import LOG_DIR

_ring = deque(maxlen=500)
_ring_lock = threading.Lock()


class _RingHandler(logging.Handler):
    def emit(self, record):
        try:
            msg = self.format(record)
        except Exception:
            return
        with _ring_lock:
            _ring.append(msg)


def setup_logger() -> logging.Logger:
    logger = logging.getLogger("tprints")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s  %(levelname)-7s %(message)s", "%H:%M:%S")

    os.makedirs(LOG_DIR, exist_ok=True)
    fh = RotatingFileHandler(os.path.join(LOG_DIR, "tprints.log"),
                             maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s"))
    logger.addHandler(fh)

    rh = _RingHandler()
    rh.setFormatter(fmt)
    logger.addHandler(rh)
    return logger


def tail_logs(n=200):
    """UI uchun oxirgi n ta log qatori."""
    with _ring_lock:
        return list(_ring)[-n:]
