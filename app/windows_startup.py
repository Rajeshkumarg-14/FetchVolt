"""Per-user Windows startup registration."""
from pathlib import Path
import sys
import winreg
from runtime_paths import is_packaged, executable

RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
VALUE_NAME = 'PortFlock'


def command():
    if not is_packaged():
        return None
    return f'"{executable()}" --startup'


def preferences():
    expected = command()
    if expected is None:
        return {'enabled': False, 'supported': False}
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
        enabled = value == expected
    except FileNotFoundError:
        enabled = False
    return {'enabled': enabled, 'supported': True}


def set_enabled(enabled):
    if type(enabled) is not bool:
        raise ValueError('Windows startup requires a true or false value.')
    expected = command()
    if expected is None:
        raise ValueError('Windows startup is available in the installed executable.')
    if enabled:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, expected)
    else:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE) as key:
                value, _ = winreg.QueryValueEx(key, VALUE_NAME)
                if value == expected:
                    winreg.DeleteValue(key, VALUE_NAME)
        except FileNotFoundError:
            pass
    return preferences()
