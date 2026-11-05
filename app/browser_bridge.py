"""Allowlisted native messaging and a durable, per-user browser download inbox.

There is no socket listener. Browser processes can submit URLs, never paths,
commands, cookies, headers, adapter IDs, or security-policy overrides.
"""
from contextlib import contextmanager
import ctypes
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import struct
import subprocess
import sys
from version import VERSION
from runtime_paths import is_packaged, executable, resource_root
import time
from urllib.parse import urlsplit, unquote
from uuid import uuid4

HOST = 'com.rajeshkumarg.portflock'
FIREFOX_ID = 'portflock@rajeshkumarg.com'
MAX_MESSAGE = 24 * 1024
MAX_PENDING = 50
EXTENSION_FILES = ('background.js', 'policy.js', 'popup.html', 'popup.js', 'popup.css')


def extension_id():
    manifest = json.loads((resource_root() / 'extension' / 'manifest.json').read_text('utf-8'))
    import base64
    digest = hashlib.sha256(base64.b64decode(manifest['key'], validate=True)).hexdigest()[:32]
    return ''.join(chr(ord('a') + int(char, 16)) for char in digest)


def allowed_caller(args):
    # Chromium passes origin first. Firefox passes host-manifest path then add-on ID.
    origin = 'chrome-extension://' + extension_id() + '/'
    return bool(args) and (args[0] == origin or (
        len(args) == 2 and args[1] == FIREFOX_ID and Path(args[0]).name == 'firefox-host.json'))


def native_invocation(args):
    return bool(args) and (args[0].startswith('chrome-extension://') or
                          len(args) > 1 and args[1] == FIREFOX_ID)


def plain_directory(folder):
    folder = Path(folder)
    for parent in (folder, *folder.parents):
        try:
            info = parent.lstat()
        except FileNotFoundError:
            continue
        if info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError('Browser integration refuses linked directories.')
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def data_directory():
    # Persist the resolved path during setup so packaged installers, browsers
    # and the desktop agree even with MSIX filesystem redirection.
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\PortFlock\BrowserIntegration') as key:
            root = winreg.QueryValueEx(key, 'DataRoot')[0]
        if not isinstance(root, str) or not Path(root).is_absolute():
            raise ValueError('Invalid browser data root.')
        return plain_directory(root).resolve(strict=True)
    except FileNotFoundError:
        return plain_directory(Path(os.environ['LOCALAPPDATA']) / 'Net Booster' / 'browser').resolve(strict=True)


def validate_public_url(url):
    if not isinstance(url, str) or not 1 <= len(url) <= 16384 or any(ord(c) <= 32 for c in url):
        raise ValueError('Use a direct public HTTPS URL.')
    parts = urlsplit(url)
    if (parts.scheme != 'https' or not parts.hostname or parts.username is not None
            or parts.password is not None or parts.fragment or parts.port not in (None, 443)):
        raise ValueError('Use HTTPS without credentials, fragments, or custom ports.')
    host = parts.hostname.lower().rstrip('.')
    if host == 'localhost' or host.endswith(('.localhost', '.local', '.internal')) or '.' not in host:
        raise ValueError('Local network downloads stay in the browser.')
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if not re.fullmatch(r'[a-z0-9.-]+', host) or '..' in host:
            raise ValueError('Invalid download hostname.') from None
    else:
        if not address.is_global:
            raise ValueError('A public download address is required.')
    return url


def safe_filename(value, identifier):
    if not isinstance(value, str) or len(value) > 512:
        raise ValueError('Invalid download filename.')
    # Browser paths are hints; never accept a caller-controlled destination.
    name = re.split(r'[/\\]', value)[-1]
    name = ''.join(c for c in name if ord(c) >= 32 and c not in '<>:"/\\|?*').strip(' .')[:140]
    if not name or os.path.isreserved(name):
        name = 'download.bin'
    path = Path(name)
    return path.stem + '-' + identifier[:12] + path.suffix


class Inbox:
    def __init__(self, folder=None):
        self.folder = plain_directory(folder) if folder is not None else data_directory()
        self.path = self.folder / 'inbox.sqlite3'
        if self.path.exists() and self.path.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError('Refusing a linked inbox.')
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, url TEXT NOT NULL, filename TEXT NOT NULL, state TEXT NOT NULL, created REAL NOT NULL)')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=3)
        try:
            db.execute('PRAGMA synchronous=FULL')
            with db:
                yield db
        finally:
            db.close()

    def submit(self, message):
        if (not isinstance(message, dict) or set(message) != {'op', 'url', 'filename', 'requestId'}
                or message['op'] != 'download' or not isinstance(message['requestId'], str)
                or not re.fullmatch(r'[a-f0-9]{32}', message['requestId'])):
            raise ValueError('Invalid browser request.')
        url = validate_public_url(message['url'])
        identifier = message['requestId']
        name = safe_filename(message['filename'], identifier)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT url,filename,state FROM requests WHERE id=?', (identifier,)).fetchone()
            if existing:
                if existing[0:2] != (url, name) or existing[2] in ('withdrawn', 'cancelled', 'failed'):
                    raise ValueError('This request ID cannot be reused.')
                return identifier
            if db.execute("SELECT count(*) FROM requests WHERE state IN ('pending','queued')").fetchone()[0] >= MAX_PENDING:
                raise ValueError('The browser transfer queue is full.')
            db.execute("DELETE FROM requests WHERE state NOT IN ('pending','queued') AND created < ?", (time.time() - 86400,))
            db.execute("DELETE FROM requests WHERE id IN (SELECT id FROM requests WHERE state NOT IN ('pending','queued') ORDER BY created DESC LIMIT -1 OFFSET 200)")
            db.execute('INSERT INTO requests VALUES (?,?,?,?,?)', (identifier, url, name, 'pending', time.time()))
        return identifier

    def pending(self, restore=False):
        with self.connect() as db:
            return db.execute("SELECT id,url,filename FROM requests WHERE state='pending'" +
                              (" OR state='queued'" if restore else '') + ' ORDER BY created LIMIT 50').fetchall()

    def mark(self, identifier, state):
        if state not in ('queued', 'saved', 'failed', 'cancelled', 'withdrawn'):
            raise ValueError('Invalid browser transfer state.')
        with self.connect() as db:
            db.execute('UPDATE requests SET state=? WHERE id=?', (state, identifier))
            if state in ('saved', 'failed', 'cancelled', 'withdrawn'):
                db.execute("UPDATE requests SET url='' WHERE id=?", (identifier,))

    def status(self, identifier):
        if not isinstance(identifier, str) or not re.fullmatch(r'[a-f0-9]{32}', identifier):
            raise ValueError('Invalid transfer ID.')
        with self.connect() as db:
            row = db.execute('SELECT state FROM requests WHERE id=?', (identifier,)).fetchone()
        return row[0] if row else 'unknown'


def read_exact(stream, size):
    result = bytearray()
    while len(result) < size:
        chunk = stream.read(size - len(result))
        if not chunk:
            raise ValueError('Incomplete native message.')
        result.extend(chunk)
    return bytes(result)


def read_message(stream):
    size = struct.unpack('<I', read_exact(stream, 4))[0]
    if not 1 <= size <= MAX_MESSAGE:
        raise ValueError('Native message is too large.')
    return json.loads(read_exact(stream, size).decode('utf-8'))


def write_message(stream, value):
    payload = json.dumps(value, separators=(',', ':')).encode('utf-8')
    stream.write(struct.pack('<I', len(payload)) + payload)
    stream.flush()


def native_stream(kind):
    # PyInstaller --windowed sets sys.stdin/stdout to None. Use the inherited
    # Windows pipe handles directly; never open a console or print to stdout.
    import msvcrt
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetStdHandle.restype = wintypes.HANDLE
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.DuplicateHandle.argtypes = [wintypes.HANDLE, wintypes.HANDLE, wintypes.HANDLE,
                                     ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    handle = kernel.GetStdHandle(-10 if kind == 'rb' else -11)
    duplicate = wintypes.HANDLE()
    process = kernel.GetCurrentProcess()
    if not kernel.DuplicateHandle(process, handle, process, ctypes.byref(duplicate), 0, False, 2):
        raise OSError('Native messaging pipe is unavailable.')
    fd = msvcrt.open_osfhandle(duplicate.value, os.O_BINARY | (os.O_RDONLY if kind == 'rb' else os.O_WRONLY))
    return os.fdopen(fd, kind, buffering=0)


def wake_desktop():
    if not is_packaged():
        raise ValueError('Install FetchVolt before enabling browser integration.')
    subprocess.Popen([str(executable()), '--browser-wake'], close_fds=True, creationflags=subprocess.CREATE_NO_WINDOW)


def host(args):
    if not allowed_caller(args):
        return 1
    import threading
    timer = threading.Timer(20, lambda: os._exit(1))
    timer.daemon = True
    timer.start()
    with native_stream('rb') as incoming, native_stream('wb') as outgoing:
        try:
            message = read_message(incoming)
            inbox = Inbox()
            if isinstance(message, dict) and message == {'op': 'ping'}:
                response = {'ok': True, 'version': VERSION}
            elif isinstance(message, dict) and set(message) == {'op', 'id'} and message['op'] == 'status':
                response = {'ok': True, 'state': inbox.status(message['id'])}
            else:
                identifier = inbox.submit(message)
                try:
                    wake_desktop()
                except (OSError, ValueError):
                    inbox.mark(identifier, 'withdrawn')
                    raise
                response = {'ok': True, 'accepted': True, 'id': identifier}
            write_message(outgoing, response)
        except (OSError, ValueError, TypeError, KeyError, sqlite3.Error):
            write_message(outgoing, {'ok': False, 'error': 'FetchVolt did not accept this download. Keep it in the browser.'})
    timer.cancel()
    return 0


@contextmanager
def app_instance():
    """A per-profile process lock also prevents repeated browser wake windows."""
    import msvcrt
    path = data_directory() / 'desktop.lock'
    with path.open('a+b') as file:
        if not path.stat().st_size:
            file.write(b'0'); file.flush()
        file.seek(0)
        try:
            msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            yield False
            return
        try:
            yield True
        finally:
            file.seek(0)
            msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
