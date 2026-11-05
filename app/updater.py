"""Publisher-authenticated updates for the managed, per-user Windows install."""
import base64
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import zipfile

from runtime_paths import executable, is_packaged, resource_root
from update_key import PUBLIC_KEY_XML
from version import VERSION

UPDATE_URL = 'https://rajeshkumarg-14.github.io/fetchvolt-site/update.json'
class UpdateError(ValueError):
    """Controlled, user-facing updater failure."""


MAX_ZIP = 128 * 1024 * 1024
MAX_EXPANDED = 256 * 1024 * 1024
FILES = {'FetchVolt.exe', 'Install-NetBooster.ps1', 'Uninstall-NetBooster.ps1', 'NOTICE.md',
         'LICENSE', 'LICENSING.md', 'THIRD-PARTY-NOTICES.txt', 'INSTALL.txt', 'PAYLOAD-SHA256.txt'}


def version(value):
    if not isinstance(value, str) or not re.fullmatch(r'(0|[1-9]\d{0,4})\.(0|[1-9]\d{0,4})\.(0|[1-9]\d{0,4})', value):
        raise UpdateError('Invalid release version.')
    parts = tuple(map(int, value.split('.')))
    if max(parts) > 65535:
        raise UpdateError('Invalid release version.')
    return parts


def plain(path):
    path = Path(path)
    for item in (path, *path.parents):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise UpdateError('Updates refuse linked paths.')
    return path


def local_appdata():
    buffer = ctypes.create_unicode_buffer(32768)
    if ctypes.windll.shell32.SHGetFolderPathW(None, 0x1c, None, 0, buffer):
        raise OSError('Could not locate the local user profile.')
    return Path(buffer.value)


def install_directory():
    return plain(local_appdata() / 'Programs' / 'Net Booster')


def powershell():
    return Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise UpdateError('Duplicate update field.')
        result[key] = value
    return result


def verify_signature(payload, signature):
    script = '''$ErrorActionPreference='Stop';$p=[Console]::In.ReadToEnd()|ConvertFrom-Json;
$rsa=New-Object Security.Cryptography.RSACryptoServiceProvider;$rsa.PersistKeyInCsp=$false;
try {$rsa.FromXmlString('__KEY__');if(!$rsa.VerifyData([Convert]::FromBase64String($p.payload),'SHA256',[Convert]::FromBase64String($p.signature))){exit 2}} finally {$rsa.Dispose()}'''.replace('__KEY__', PUBLIC_KEY_XML)
    result = subprocess.run([str(powershell()), '-NoProfile', '-NonInteractive', '-Command', script],
                            input=json.dumps({'payload': base64.b64encode(payload).decode(),
                                              'signature': base64.b64encode(signature).decode()}).encode(),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=subprocess.CREATE_NO_WINDOW, timeout=15)
    if result.returncode:
        raise UpdateError('The update publisher signature could not be verified.')


def parse_manifest(raw):
    if len(raw) > 40 * 1024:
        raise UpdateError('Update metadata is too large.')
    envelope = json.loads(raw, object_pairs_hook=unique_object)
    if not isinstance(envelope, dict) or set(envelope) != {'algorithm', 'payload', 'signature'} or envelope['algorithm'] != 'rsa-pkcs1v15-sha256':
        raise UpdateError('Unsupported update signature format.')
    payload = base64.b64decode(envelope['payload'], validate=True)
    signature = base64.b64decode(envelope['signature'], validate=True)
    if not 1 <= len(payload) <= 24576 or len(signature) != 384:
        raise UpdateError('Invalid signed update size.')
    verify_signature(payload, signature)
    manifest = json.loads(payload, object_pairs_hook=unique_object)
    if not isinstance(manifest, dict) or set(manifest) != {'format', 'version', 'url', 'bytes', 'sha256', 'files'} or type(manifest['format']) is not int or manifest['format'] != 1:
        raise UpdateError('Invalid signed update fields.')
    version(manifest['version'])
    expected = f"https://github.com/Rajeshkumarg-14/fetchvolt-site/releases/download/v{manifest['version']}/FetchVolt-Setup-{manifest['version']}.zip"
    if manifest['url'] != expected:
        raise UpdateError('Update URL is outside the official release path.')
    if type(manifest['bytes']) is not int or not 1 <= manifest['bytes'] <= MAX_ZIP or not isinstance(manifest['sha256'], str) or not re.fullmatch('[a-f0-9]{64}', manifest['sha256']):
        raise UpdateError('Invalid update size or hash.')
    files = manifest['files']
    if not isinstance(files, dict) or set(files) != FILES:
        raise UpdateError('Unexpected update payload files.')
    total = 0
    for entry in files.values():
        if not isinstance(entry, dict) or set(entry) != {'bytes', 'sha256'} or type(entry['bytes']) is not int or not 1 <= entry['bytes'] <= MAX_ZIP or not isinstance(entry['sha256'], str) or not re.fullmatch('[a-f0-9]{64}', entry['sha256']):
            raise UpdateError('Invalid payload file bounds.')
        total += entry['bytes']
    if total > MAX_EXPANDED:
        raise UpdateError('Expanded update is too large.')
    return manifest


def fetch(url, limit, output=None, expected_size=None):
    from net_booster import request
    lease, response = request(url, 0, {}, public_only=True, timeout=10, header_timeout=15, response_timeout=90, redirect_limit=5)
    try:
        if response.status != 200 or response.getheader('Content-Encoding', 'identity') != 'identity':
            raise UpdateError('The update server did not return an uncompressed file.')
        length = response.getheader('Content-Length')
        if length is not None and (int(length) > limit or expected_size is not None and int(length) != expected_size):
            raise UpdateError('Update response size does not match its signed metadata.')
        result = bytearray()
        count = 0
        while True:
            block = response.read(min(65536, limit + 1 - count))
            lease.check()
            if not block:
                break
            count += len(block)
            if count > limit:
                raise UpdateError('Update response exceeded its size limit.')
            if output:
                output.write(block)
            else:
                result.extend(block)
        if expected_size is not None and count != expected_size:
            raise UpdateError('The update download was incomplete.')
        return bytes(result)
    finally:
        response.close()
        lease.close()


def unpack(archive_path, folder, manifest):
    from windows_security import scan_file
    if archive_path.stat().st_size != manifest['bytes'] or digest_file(archive_path) != manifest['sha256']:
        raise UpdateError('The update archive failed SHA-256 verification.')
    with zipfile.ZipFile(archive_path) as archive:
        entries = archive.infolist()
        if len(entries) != len(FILES) or {item.filename for item in entries} != FILES:
            raise UpdateError('Unexpected or duplicate update archive entries.')
        for item in entries:
            record = manifest['files'][item.filename]
            if item.file_size != record['bytes'] or item.flag_bits & 1 or stat.S_ISLNK(item.external_attr >> 16):
                raise UpdateError('Invalid payload archive entry.')
            destination = plain(folder / item.filename)
            with archive.open(item) as source, destination.open('xb') as target:
                size = 0
                while block := source.read(65536):
                    size += len(block)
                    if size > record['bytes']:
                        raise UpdateError('Expanded file exceeded its signed size.')
                    target.write(block)
            if size != record['bytes'] or digest_file(destination) != record['sha256']:
                raise UpdateError('A payload file failed integrity verification.')
            Path(str(destination) + ':Zone.Identifier').write_bytes(b'[ZoneTransfer]\r\nZoneId=3\r\n')
            scan_file(destination)


def digest_file(path):
    with path.open('rb') as file:
        return hashlib.file_digest(file, 'sha256').hexdigest()


def check():
    raw = fetch(UPDATE_URL, 40 * 1024)
    return parse_manifest(raw), raw


def _prepare(manifest, raw):
    if version(manifest['version']) <= version(VERSION):
        raise UpdateError('Only a newer release can be installed.')
    install = install_directory().resolve(strict=True)
    if not is_packaged() or executable() != install / 'Net Booster.exe':
        raise UpdateError('Automatic updates require the managed per-user installation. Install the setup bundle first.')
    from browser_bridge import app_instance, data_directory
    with app_instance() as acquired:
        if not acquired:
            raise UpdateError('Close the FetchVolt window before updating. Save active downloads normally.')
    candidate = shutil.which('pwsh.exe')
    pwsh = Path(candidate) if candidate else None
    if not pwsh or not pwsh.is_file():
        raise UpdateError('PowerShell 7 is required to apply updates under your Windows execution policy.')
    for old in install.glob('.fetchvolt-update-*'):
        plain(old)
        marker = old / 'complete.marker'
        if marker.is_file() and marker.read_text('utf-8') == 'FetchVolt update completed\n':
            for parent, directories, files in os.walk(old, followlinks=False):
                for name in directories + files:
                    plain(Path(parent) / name)
            shutil.rmtree(old)
    if len(list(install.glob('.fetchvolt-update-*'))) >= 3:
        raise UpdateError('Review prior failed update staging folders before trying again.')
    folder = Path(tempfile.mkdtemp(prefix='.fetchvolt-update-', dir=install))
    queued = False
    try:
        archive = folder / 'package.zip'
        with archive.open('xb') as target:
            fetch(manifest['url'], manifest['bytes'], target, manifest['bytes'])
        unpack(archive, folder, manifest)
        (folder / 'update.json').write_bytes(raw)
        template = (resource_root() / 'scripts/Apply-Update.ps1').read_text('utf-8')
        worker = folder / 'apply.ps1'
        worker.write_text(template.replace('__PUBLIC_KEY_XML__', PUBLIC_KEY_XML), encoding='utf-8', newline='\n')
        (folder / 'lock-path.txt').write_text(str(data_directory() / 'desktop.lock'), encoding='utf-8')
        result = plain(install / '.update-result.json')
        result.write_text(json.dumps({'state': 'pending', 'message': 'Applying verified update after CLI exit.'}), encoding='utf-8')
        log = (folder / 'worker.log').open('wb')
        try:
            process = subprocess.Popen([str(pwsh), '-NoProfile', '-NonInteractive', '-File', str(worker), '-WaitPid', str(os.getpid())],
                                       stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                       creationflags=subprocess.CREATE_NO_WINDOW, close_fds=True)
        finally:
            log.close()
        result.write_text(json.dumps({'state': 'pending', 'pid': process.pid, 'message': 'Applying verified update after CLI exit.'}), encoding='utf-8')
        try:
            code = process.wait(timeout=1)
            if code:
                raise UpdateError('Windows blocked the update worker. Check your PowerShell policy; it was not bypassed.')
        except subprocess.TimeoutExpired:
            queued = True
        if not queued:
            raise UpdateError('The update worker exited before installation was queued.')
        return folder
    finally:
        if not queued:
            # Exactly the newly created staging directory under the validated install.
            if folder.parent == install and folder.name.startswith('.fetchvolt-update-'):
                shutil.rmtree(folder)


def prepare(manifest, raw):
    import msvcrt
    import psutil
    install = install_directory().resolve(strict=True)
    if not is_packaged() or executable() != install / 'Net Booster.exe':
        raise UpdateError('Automatic updates require the managed per-user installation. Install the setup bundle first.')
    guard_path = plain(install / '.update-lock')
    with guard_path.open('a+b') as guard:
        if not guard_path.stat().st_size:
            guard.write(b'0'); guard.flush()
        guard.seek(0)
        try:
            msvcrt.locking(guard.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise UpdateError('Another update command is already running.') from None
        try:
            result = plain(install / '.update-result.json')
            if result.is_file():
                if result.stat().st_size > 4096:
                    raise UpdateError('Review the prior update result before trying again.')
                status = json.loads(result.read_text('utf-8'))
                if status.get('state') == 'pending' and type(status.get('pid')) is int and psutil.pid_exists(status['pid']):
                    raise UpdateError('Another verified update is already being applied.')
            return _prepare(manifest, raw)
        finally:
            guard.seek(0)
            msvcrt.locking(guard.fileno(), msvcrt.LK_UNLCK, 1)
