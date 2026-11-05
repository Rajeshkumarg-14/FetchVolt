"""Runtime paths shared by source, PyInstaller and native-compiled builds."""
from pathlib import Path
import sys


def is_packaged():
    return bool(getattr(sys, 'frozen', False) or '__compiled__' in globals())


def executable():
    # Nuitka onefile sys.executable can refer to the extracted child; argv[0]
    # identifies the outer executable for registration and relaunching.
    return Path(sys.argv[0] if '__compiled__' in globals() else sys.executable).resolve()


def resource_root():
    folder = Path(__file__).parent
    return folder if is_packaged() else folder.parent
