"""Per-user install and uninstall performed by FetchVolt.exe itself (no PowerShell 7 needed).

Same locations and registry entries as Install-NetBooster.ps1, so both can manage one install.
Every path and registry key is injected through Layout so tests never touch the real user profile.
"""
import ctypes
import datetime
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid
import winreg

import psutil
from version import VERSION

PROCESS_NAMES = {'net booster.exe', 'portweave.exe', 'portflock.exe', 'fetchvolt.exe'}
LAUNCHER_HEADER = '@rem FetchVolt managed terminal launcher'
LAUNCHER = LAUNCHER_HEADER + r'''
@echo off
set "FV_DIR=%~dp0"
"%~dp0Net Booster.exe" %*
if not "%errorlevel%"=="42" exit /b %errorlevel%
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -Command "$p=Join-Path $env:FV_DIR '.update-result.json';for($i=0;$i -lt 120;$i++){try{$r=Get-Content -LiteralPath $p -Raw|ConvertFrom-Json;if($r.state -ne 'pending'){Write-Host $r.message;exit [int]$r.exitCode}}catch{};Start-Sleep -Seconds 1};Write-Error 'Update result timed out; check the installation before retrying.';exit 1"
exit /b %errorlevel%
'''.replace('\n', '\r\n')
SHORTCUT_SCRIPT = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:FV_LINK);$s.TargetPath=$env:FV_TARGET;"
                   "$s.WorkingDirectory=$env:FV_DIR;$s.Description='FetchVolt downloader and network monitor';$s.Save()")


class InstallerError(Exception):
    """Message is safe to show the user."""


class Layout:
    def __init__(self, local=None, programs=None, uninstall_key=r'Software\Microsoft\Windows\CurrentVersion\Uninstall\NetBooster',
                 environment_key='Environment', run_key=r'Software\Microsoft\Windows\CurrentVersion\Run', broadcast=True, install=None):
        local = Path(local or os.environ['LOCALAPPDATA'])
        self.default_install = local / 'Programs' / 'Net Booster'
        self.install = Path(install) if install else self.default_install
        self.data = local / 'Net Booster'
        self.programs = Path(programs or Path(os.environ['APPDATA']) / 'Microsoft/Windows/Start Menu/Programs')
        self.exe = self.install / 'Net Booster.exe'
        self.launcher = self.install / 'fetchvolt.cmd'
        self.shortcut = self.programs / 'FetchVolt.lnk'
        self.uninstall_key, self.environment_key, self.run_key, self.broadcast = uninstall_key, environment_key, run_key, broadcast
        self._kwargs = dict(local=local, programs=self.programs, uninstall_key=uninstall_key, environment_key=environment_key,
                            run_key=run_key, broadcast=broadcast)

    def at(self, install):
        """The same layout with a different install folder."""
        return Layout(**self._kwargs, install=install)

    @property
    def is_default(self):
        return os.path.normcase(str(self.install)) == os.path.normcase(str(self.default_install))

    def installed(self):
        """The layout recorded by a previous install, so uninstall removes the folder that was really used."""
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.uninstall_key) as key:
                recorded = winreg.QueryValueEx(key, 'InstallLocation')[0]
        except FileNotFoundError:
            return self
        return self.at(recorded) if recorded and Path(recorded).is_absolute() else self


def validate_directory(path):
    """Return a safe install folder, or raise a message the wizard can show as is."""
    text = str(path).strip().strip('"')
    if not text:
        raise InstallerError('Choose an install folder.')
    folder = Path(text)
    if not folder.is_absolute() or text.startswith('\\\\'):
        raise InstallerError('Choose a folder on a local drive, for example C:\\Users\\you\\FetchVolt.')
    if folder.parent == folder:
        raise InstallerError('Choose a folder, not a whole drive.')
    plain(folder)
    if folder.exists():
        if not folder.is_dir():
            raise InstallerError('That path is a file. Choose a folder.')
        entries = {entry.name.lower() for entry in folder.iterdir()}
        if entries and 'net booster.exe' not in entries:
            raise InstallerError('That folder already contains other files. Choose an empty or new folder.')
    else:
        # Missing intermediate folders are fine (install() creates them) if a real drive or folder sits above them.
        ancestor = folder.parent
        while not ancestor.exists() and ancestor.parent != ancestor:
            ancestor = ancestor.parent
        if not ancestor.is_dir():
            raise InstallerError('That drive or folder is not available.')
    return folder


def plain(path):
    """Refuse links anywhere on the path, as the PowerShell installer does."""
    for item in (Path(path), *Path(path).parents):
        if item.exists() and (item.is_symlink() or getattr(item, 'is_junction', lambda: False)()):
            raise InstallerError(f'Refusing to use a linked path: {item}')


def running_copies(layout, ignore=()):
    """Processes running the installed executable, excluding this process and its launcher parent."""
    skip = {os.getpid(), os.getppid(), *ignore}
    found = []
    for process in psutil.process_iter(['pid', 'exe']):
        try:
            if process.info['pid'] not in skip and process.info['exe'] and \
                    os.path.normcase(process.info['exe']) == os.path.normcase(str(layout.exe)):
                found.append(process.info['pid'])
        except psutil.Error:
            pass
    return found


def _broadcast(layout):
    if layout.broadcast:
        result = ctypes.c_size_t()
        ctypes.windll.user32.SendMessageTimeoutW(0xffff, 0x1a, 0, 'Environment', 2, 1000, ctypes.byref(result))


def _path_entries(layout):
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, layout.environment_key, 0, winreg.KEY_READ) as key:
        try:
            value, kind = winreg.QueryValueEx(key, 'Path')
        except FileNotFoundError:
            return [], winreg.REG_EXPAND_SZ
    return [part for part in value.split(';') if part], kind


def _write_path(layout, parts, kind):
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, layout.environment_key, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, 'Path', 0, kind, ';'.join(parts))
    _broadcast(layout)


def add_to_path(layout):
    parts, kind = _path_entries(layout)
    if str(layout.install) not in parts:
        _write_path(layout, [*parts, str(layout.install)], kind)


def remove_from_path(layout):
    parts, kind = _path_entries(layout)
    if str(layout.install) in parts:
        _write_path(layout, [part for part in parts if part != str(layout.install)], kind)


def create_shortcut(layout):
    environment = {**os.environ, 'FV_LINK': str(layout.shortcut), 'FV_TARGET': str(layout.exe), 'FV_DIR': str(layout.install)}
    powershell = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    result = subprocess.run([str(powershell), '-NoProfile', '-NonInteractive', '-Command', SHORTCUT_SCRIPT],
                            env=environment, capture_output=True, timeout=30)
    if result.returncode:
        raise InstallerError('Could not create the Start menu shortcut.')


def license_text():
    from runtime_paths import resource_root
    return (resource_root() / 'LICENSE').read_text('utf-8')


def copy_notices(layout):
    from runtime_paths import resource_root
    for name in ('LICENSE', 'LICENSING.md', 'NOTICE.md'):
        source = resource_root() / name
        if source.is_file():
            shutil.copyfile(source, layout.install / name)


def install(layout=None, source=None, *, accept_license=False, shortcut=True, add_path=True):
    if not accept_license:
        raise InstallerError('Accept the license terms to install FetchVolt.')
    layout = layout or Layout()
    if source is None:
        from runtime_paths import executable, is_packaged
        if not is_packaged():
            raise InstallerError('Install from the FetchVolt.exe release, not from source.')
        source = executable()
    source = Path(source)
    for path in (layout.exe, layout.launcher, layout.shortcut, source):
        plain(path)
    if os.path.normcase(str(source.resolve())) == os.path.normcase(str(layout.exe.resolve())):
        raise InstallerError('This copy already is the installed one. Run FetchVolt.exe from another folder to update it.')
    if running_copies(layout):
        raise InstallerError('Close the installed copy of FetchVolt before updating it.')
    layout.install.mkdir(parents=True, exist_ok=True)
    if shortcut:
        layout.programs.mkdir(parents=True, exist_ok=True)
    staged = layout.install / f'.NetBooster-{uuid.uuid4().hex}.tmp'
    try:
        shutil.copyfile(source, staged)
        if staged.stat().st_size != source.stat().st_size:
            raise InstallerError('The copied executable did not match its source.')
        os.replace(staged, layout.exe)
    finally:
        staged.unlink(missing_ok=True)
    layout.launcher.write_bytes(LAUNCHER.encode('ascii'))
    copy_notices(layout)
    if shortcut:
        create_shortcut(layout)
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, layout.uninstall_key, 0, winreg.KEY_SET_VALUE) as key:
        for name, value in {'DisplayName': 'FetchVolt', 'InstallLocation': str(layout.install), 'DisplayIcon': str(layout.exe),
                            'UninstallString': f'"{layout.exe}" --uninstall', 'CliPath': str(layout.install),
                            'DisplayVersion': VERSION,
                            'LicenseAccepted': f'PolyForm Noncommercial 1.0.0; FetchVolt {VERSION}; {datetime.date.today().isoformat()}'}.items():
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
    if add_path:
        add_to_path(layout)
    return layout.install


def _delete_later(layout):
    """A running executable cannot delete itself; a detached shell retries until it exits."""
    exe, folder = layout.exe, layout.install
    command = (f'ping -n 4 127.0.0.1 >nul & del /f /q "{exe}" 2>nul || (ping -n 8 127.0.0.1 >nul & del /f /q "{exe}" 2>nul)'
               f' & rmdir "{folder}" 2>nul')
    subprocess.Popen(['cmd.exe', '/d', '/c', command], creationflags=0x08000000 | 0x00000008, close_fds=True)


def uninstall(layout=None, remove_history=False, current_exe=None):
    layout = (layout or Layout()).installed()
    for path in (layout.exe, layout.launcher, layout.shortcut, layout.install):
        plain(path)
    if running_copies(layout) or remove_history and any(
            (p.info['name'] or '').lower() in PROCESS_NAMES and p.info['pid'] not in (os.getpid(), os.getppid())
            for p in psutil.process_iter(['pid', 'name'])):
        raise InstallerError('Close FetchVolt before uninstalling.')
    pending = layout.install / '.update-result.json'
    if pending.is_file() and pending.stat().st_size <= 4096:
        import json
        try:
            status = json.loads(pending.read_text('utf-8'))
            if status.get('state') == 'pending' and psutil.pid_exists(int(status.get('pid', 0))):
                raise InstallerError('Wait for the verified update to finish before uninstalling.')
        except (ValueError, OSError):
            pass
    try:
        from browser_setup import remove_registration
        remove_registration()
    except Exception:  # best effort: browser registrations must not block removal
        pass
    remove_from_path(layout)
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, layout.uninstall_key)
    except FileNotFoundError:
        pass
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, layout.run_key, 0, winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE) as key:
            if winreg.QueryValueEx(key, 'PortFlock')[0] == f'"{layout.exe}" --startup':
                winreg.DeleteValue(key, 'PortFlock')
    except FileNotFoundError:
        pass
    layout.shortcut.unlink(missing_ok=True)
    if layout.launcher.is_file() and layout.launcher.read_text('ascii', 'ignore').startswith(LAUNCHER_HEADER):
        layout.launcher.unlink()
    for name in ('LICENSE', 'LICENSING.md', 'NOTICE.md', 'Uninstall-NetBooster.ps1', '.update-result.json', '.update-lock'):
        (layout.install / name).unlink(missing_ok=True)
    for stage in layout.install.glob('.fetchvolt-update-*'):
        marker = stage / 'complete.marker'
        if stage.is_dir() and marker.is_file() and marker.read_text('utf-8') == 'FetchVolt update completed\n':
            plain(stage)
            shutil.rmtree(stage)
    if remove_history:
        for name in ('history.sqlite3', 'history.sqlite3-journal', 'history.sqlite3-wal', 'history.sqlite3-shm'):
            (layout.data / name).unlink(missing_ok=True)
    own = current_exe and os.path.normcase(str(Path(current_exe).resolve())) == os.path.normcase(str(layout.exe.resolve()))
    if own:
        _delete_later(layout)
    else:
        layout.exe.unlink(missing_ok=True)
        for folder in (layout.install, layout.data if remove_history else None):
            if folder and folder.is_dir() and not any(folder.iterdir()):
                folder.rmdir()
    return own
