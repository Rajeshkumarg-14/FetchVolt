"""Bounded, local diagnostic logging for the desktop app."""
from datetime import datetime
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
from traceback import extract_tb

LOGGER = logging.getLogger('portflock')
LOGGER.addHandler(logging.NullHandler())
LOG_BYTES = 1024 * 1024
SESSION_FILES = 3
RETAINED_FILES = 12


def log_directory():
    return Path(os.environ['LOCALAPPDATA']) / 'Net Booster' / 'logs'


def configure(directory=None):
    folder = Path(directory) if directory is not None else log_directory()
    folder.mkdir(parents=True, exist_ok=True)
    folder = folder.resolve(strict=True)
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    path = folder / f'portflock-{stamp}-{os.getpid()}.log'
    handler = RotatingFileHandler(path, maxBytes=LOG_BYTES, backupCount=SESSION_FILES - 1, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s [%(threadName)s] %(message)s'))
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False
    LOGGER.addHandler(handler)
    logs = sorted(folder.glob('portflock-*.log*'), key=lambda item: (item.name.split('.log')[0], -len(item.suffixes)), reverse=True)
    for old in logs[RETAINED_FILES:]:
        try:
            old.unlink()
        except OSError:
            # Another running instance may still own this log on Windows.
            continue
    return path


def failure(event, error, transfer_id=None):
    """Keep exception locations and numeric codes without raw exception text."""
    code = getattr(error, 'winerror', None) or getattr(error, 'errno', None)
    locations = ' > '.join(
        f'{Path(frame.filename).name}:{frame.lineno}'
        for frame in extract_tb(error.__traceback__, limit=-5)
    )
    LOGGER.warning('%s transfer=%s error=%s code=%s at=%s',
                   event, transfer_id, type(error).__name__, code if isinstance(code, int) else None,
                   locations or '-')
