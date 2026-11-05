"""Require a successful Microsoft Defender scan before publishing a download."""
import ctypes
from pathlib import Path
import subprocess

from diagnostics import LOGGER

SCAN_TIMEOUT = 300


class ScanError(OSError):
    """The file did not pass the required Windows malware scan."""


def defender_path():
    program_files = ctypes.create_unicode_buffer(260)
    result = ctypes.windll.shell32.SHGetFolderPathW(None, 0x26, None, 0, program_files)
    if result or not program_files.value:
        raise ScanError('Could not locate Microsoft Defender Antivirus.')
    return Path(program_files.value) / 'Windows Defender' / 'MpCmdRun.exe'


def scan_file(path):
    LOGGER.info('defender-scan-started')
    try:
        result = subprocess.run(
            [str(defender_path()), '-Scan', '-ScanType', '3', '-File', str(path), '-DisableRemediation'],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW, timeout=SCAN_TIMEOUT, check=False,
        )
    except subprocess.TimeoutExpired:
        raise ScanError('Microsoft Defender did not finish the scan in time. The file was blocked.') from None
    except OSError:
        raise ScanError('Microsoft Defender could not be started. The file was blocked.') from None
    if result.returncode != 0:
        LOGGER.warning('defender-scan-blocked exit_code=%s', result.returncode)
        raise ScanError('Microsoft Defender detected a threat or could not verify the file. The file was blocked.')
    LOGGER.info('defender-scan-clean')
