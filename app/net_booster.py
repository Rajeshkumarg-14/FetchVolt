"""Net Booster desktop downloader for Windows."""
import concurrent.futures
from collections import deque
import hashlib
import http.client
import ipaddress
import os
from functools import partial as bind
from itertools import chain
from pathlib import Path
from datetime import datetime
import queue
import re
import socket
import shutil
import sqlite3
import ssl
import struct
import tempfile
import threading
import time
import tkinter as tk
from tkinter import filedialog, ttk
import appearance
import recovery as recovery_store
from diagnostics import failure
from network_monitor import History, changes, mbps, snapshot
from windows_security import ScanError, scan_file
from urllib.parse import quote, unquote, urljoin, urlsplit

CHUNK = 2 * 1024 * 1024
READ_BUFFER = 64 * 1024
MAX_CONNECTIONS = 7
STREAMS_PER_LINK = 4  # one TCP stream cannot fill a fast, high-latency link (cellular/USB tether)
MAX_FILE_SIZE = 128 * 1024 ** 3
HEADER_TIMEOUT = 30
RANGE_TIMEOUT = 120
STREAM_TIMEOUT = 6 * 60 * 60
TLS = ssl.create_default_context()


class StorageError(RuntimeError):
    """A destination write failed independently of the network adapter."""


class ResponseLease:
    """Keep an absolute timeout on a socket even if the server trickles data."""
    def __init__(self, connection, url):
        self.url = url
        self.connection = connection
        self.socket = connection.sock
        self.expired = threading.Event()
        self.timer = None

    def arm(self, seconds):
        self.disarm()
        self.check()
        self.timer = threading.Timer(seconds, self._expire)
        self.timer.daemon = True
        self.timer.start()

    def _expire(self):
        self.expired.set()
        try:
            self.socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def disarm(self):
        if self.timer:
            self.timer.cancel()
            self.timer.join()
            self.timer = None

    def check(self):
        if self.expired.is_set():
            raise TimeoutError('The server exceeded the response time limit.')

    def close(self):
        self.disarm()
        self.connection.close()


def validate_url(url):
    if not isinstance(url, str) or not 1 <= len(url) <= 16384 or any(ord(char) < 32 for char in url):
        raise ValueError('Enter a valid direct HTTPS URL.')
    parts = urlsplit(url)
    if parts.scheme != 'https' or not parts.hostname or parts.username is not None:
        raise ValueError('Enter a direct HTTPS URL without embedded credentials.')
    _ = parts.port
    return parts


def is_public_address(address):
    ip = ipaddress.ip_address(address)
    return ip.is_global and not ip.is_multicast and not ip.is_reserved


def request(url, adapter, headers, *, public_only=False, timeout=15, header_timeout=HEADER_TIMEOUT,
            response_timeout=None, redirect_limit=8):
    for _ in range(redirect_limit):
        parts = validate_url(url)
        conn = http.client.HTTPSConnection(parts.hostname, parts.port, timeout=timeout, context=TLS)

        def connect(address, timeout, source_address):
            last_error = None
            endpoints = socket.getaddrinfo(*address, family=socket.AF_INET, type=socket.SOCK_STREAM)
            if public_only:
                endpoints = [entry for entry in endpoints if is_public_address(entry[4][0])]
                if not endpoints:
                    raise ValueError('MCP downloads require a public HTTPS address.')
            deadline = time.monotonic() + timeout
            for family, kind, proto, _, endpoint in endpoints:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('Could not connect to the server in time.')
                try:
                    sock = socket.socket(family, kind, proto)
                except OSError as error:
                    last_error = error
                    continue
                try:
                    sock.settimeout(remaining)
                    # Winsock IP_UNICAST_IF takes the interface index in network byte order.
                    sock.setsockopt(socket.IPPROTO_IP, 31, struct.pack('!I', adapter))
                    sock.connect(endpoint)
                    return sock
                except OSError as error:
                    sock.close()
                    last_error = error
            raise last_error or OSError('No IPv4 endpoint found.')

        conn._create_connection = connect
        target = quote(parts.path or '/', safe="/%:@!$&'()*+,;=-._~")
        if parts.query:
            target += '?' + quote(parts.query, safe="!$&'()*+,;=:/?@%-._~")
        lease = None
        response = None
        try:
            conn.connect()
            lease = ResponseLease(conn, url)
            lease.arm(header_timeout)
            conn.request('GET', target, headers={'Accept-Encoding': 'identity', **headers})
            response = conn.getresponse()
            lease.disarm()
            lease.check()
            if response.status not in (301, 302, 303, 307, 308):
                lease.arm(response_timeout if response_timeout is not None else (RANGE_TIMEOUT if response.status == 206 else STREAM_TIMEOUT))
                return lease, response
            with response:
                location = response.getheader('Location')
                if not location:
                    raise ValueError('Redirect missing a destination.')
                next_url = urljoin(url, location)
                if urlsplit(next_url).scheme != 'https':
                    raise ValueError('The server redirected HTTPS to an insecure URL.')
                url = next_url
        except BaseException:
            if response is not None:
                response.close()
            (lease or conn).close()
            raise
        lease.close()
    raise ValueError('Too many redirects.')


def publish(partial, destination, *, overwrite=True, expected_sha256=None):
    # Apply Mark of the Web before the completed file becomes visible.
    with open(f'{partial}:Zone.Identifier', 'wb') as zone:
        zone.write(b'[ZoneTransfer]\r\nZoneId=3\r\n')
    before = partial.stat()
    if expected_sha256 is not None:
        with partial.open('rb') as file:
            digest = hashlib.file_digest(file, 'sha256').hexdigest()
        if digest != expected_sha256:
            raise ValueError('The downloaded file did not match its expected SHA-256.')
    scan_file(partial)
    try:
        after = partial.stat()
    except FileNotFoundError:
        raise ScanError('Windows removed the download during scanning.') from None
    if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
        raise ScanError('The staged file changed during scanning. The file was blocked.')
    if overwrite:
        partial.replace(destination)
    else:
        # On Windows, rename refuses to replace an existing destination.
        partial.rename(destination)


def content_length(response):
    value = response.getheader('Content-Length')
    transfer = response.getheader('Transfer-Encoding')
    encoding = response.getheader('Content-Encoding', 'identity')
    if encoding.lower() != 'identity':
        raise ValueError('The server returned an unsupported content encoding.')
    if transfer is not None:
        if transfer.lower() != 'chunked' or value is not None:
            raise ValueError('The server returned ambiguous download framing.')
        return None
    if value is None or not re.fullmatch(r'[0-9]{1,15}', value):
        raise ValueError('The server did not provide a valid download length.')
    return int(value)


def check_size(size, directory):
    if size > MAX_FILE_SIZE:
        raise ValueError('The file exceeds the 128 GiB download limit.')
    if size > shutil.disk_usage(directory).free:
        raise OSError('There is not enough space to save the file.')


class DownloadCancelled(RuntimeError):
    """The user cancelled the download."""


class DownloadStopped(RuntimeError):
    """The app is closing while retained chunks remain recoverable."""


class RangePaused(RuntimeError):
    """Retry this uncommitted range when the user resumes."""



class LiveLinks:
    """An explicit per-job adapter selection for range-capable downloads."""
    def __init__(self, links):
        self._lock = threading.Lock()
        self._links = links.copy()
        self._mode = 'checking'
        self._revision = 0
        self._paused = False
        self._held = False
        self._cancelled = False
        self._retrying = False
        self._preserve = False
        self._responses = set()
        self._wake = threading.Event()

    def snapshot(self):
        with self._lock:
            return self._mode, self._revision, self._links.copy()

    def set_mode(self, mode, links=None):
        with self._lock:
            self._mode = mode
            if links is not None:
                self._links = links.copy()

    def update(self, links):
        if not 1 <= len(links) <= MAX_CONNECTIONS:
            raise ValueError('Select at least one available connection.')
        with self._lock:
            if self._mode != 'range':
                return False
            if links != self._links:
                self._links = links.copy()
                self._revision += 1
                self._wake.set()
            return True

    def status(self):
        with self._lock:
            return dict(paused=self._paused, held=self._held, cancelled=self._cancelled, retrying=self._retrying)

    def hold(self, enabled):
        with self._lock:
            changed = enabled and not self._held
            self._held = bool(enabled)
            self._wake.set()
            responses = tuple(self._responses) if changed else ()
        for response in responses:
            response._expire()

    def wait_ready(self):
        while self.status()['held']:
            self.wait(.2)
        if self.status()['cancelled']:
            self.check()

    def attach(self, response):
        if isinstance(response, ResponseLease):
            with self._lock:
                self._responses.add(response)
        self.check()

    def detach(self, response):
        with self._lock:
            self._responses.discard(response)

    def pause(self):
        with self._lock:
            if self._mode != 'range' or self._cancelled:
                return False
            self._paused = True
            self._wake.set()
            responses = tuple(self._responses)
        for response in responses:
            response._expire()
        return True

    def resume(self):
        with self._lock:
            if self._cancelled:
                return False
            self._paused = False
            self._wake.set()
            return True

    def cancel(self, preserve=False):
        with self._lock:
            self._preserve = preserve
            self._cancelled = True
            self._wake.set()
            responses = tuple(self._responses)
        for response in responses:
            response._expire()

    def check(self):
        with self._lock:
            if self._cancelled:
                if self._preserve:
                    raise DownloadStopped('Progress saved for recovery.')
                raise DownloadCancelled('Download cancelled.')
            if self._paused or self._held:
                raise RangePaused()

    def wait(self, seconds):
        self._wake.wait(seconds)
        self._wake.clear()
        if self.status()['cancelled']:
            self.check()

    def retrying(self, value):
        with self._lock:
            self._retrying = value


def run_live_ranges(selection, offsets, fetch):
    pending = {}
    retry = deque()
    failed = set()
    revision = -1
    exhausted = False
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_CONNECTIONS * STREAMS_PER_LINK,
                                                thread_name_prefix='live-range') as pool:
        while True:
            status = selection.status()
            if status['cancelled']:
                selection.check()
            for future in tuple(pending):
                if not future.done():
                    continue
                name, adapter, offset = pending.pop(future)
                try:
                    future.result()
                except RangePaused:
                    retry.append(offset)
                except (OSError, http.client.HTTPException) as error:
                    failure('range-worker-retrying', error)
                    status = selection.status()
                    if not status['paused'] and not status['held']:
                        failed.add((name, adapter))
                    retry.append(offset)
            if selection.status()['paused'] or selection.status()['held']:
                selection.wait(.2)
                continue
            _, current_revision, links = selection.snapshot()
            if current_revision != revision:
                failed.clear()
                revision = current_revision
            for name, adapter in links.items():
                if (name, adapter) in failed:
                    continue
                active = sum(item[0] == name for item in pending.values())
                while active < STREAMS_PER_LINK:
                    offset = retry.popleft() if retry else next(offsets, None)
                    if offset is None:
                        exhausted = True
                        break
                    future = pool.submit(fetch, name, offset, adapter)
                    pending[future] = name, adapter, offset
                    active += 1
                if exhausted:
                    break
            if not pending:
                if exhausted and not retry:
                    return
                selection.retrying(True)
                selection.wait(5)
                failed.clear()
                continue
            selection.retrying(bool(retry))
            concurrent.futures.wait(pending, timeout=.2, return_when=concurrent.futures.FIRST_COMPLETED)


def download(url, destination, links, report, **options):
    identifier = options.get('recovery_id')
    if identifier:
        with recovery_store.claim(identifier):
            return _download(url, destination, links, report, **options)
    return _download(url, destination, links, report, **options)


def _download(url, destination, links, report, *, public_only=False, overwrite=True, expected_sha256=None, live_links=None, recovery_id=None, ranged=True):
    options = dict(public_only=public_only, overwrite=overwrite, expected_sha256=expected_sha256)
    fetch_response = bind(request, public_only=True) if public_only else request
    if not 1 <= len(links) <= MAX_CONNECTIONS:
        raise ValueError(f'Select one to {MAX_CONNECTIONS} connections.')
    started = time.monotonic()
    totals = dict.fromkeys(links, 0)
    lock = threading.Lock()
    destination = Path(destination)
    record = recovery_store.load(recovery_id) if recovery_id else None
    if record and (record.data['url'] != url or record.data['target'] != str(destination.resolve())):
        raise ValueError('Recovery source or destination does not match.')
    if record:
        partial = record.partial
        expected_sha256 = record.data.get('sha256')
    else:
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix='.net-booster-', suffix='.part', delete=False) as temp:
            partial = Path(temp.name)
    saved = False
    preserve = True
    try:
        if live_links:
            live_links.wait_ready()
        primary = next(iter(links))
        try:
            probe = {'Range': 'bytes=0-0'} if ranged else {}
            conn, response = fetch_response(url, links[primary], probe)
        except (OSError, http.client.HTTPException):
            if len(links) == 1:
                raise
            remaining = {name: index for name, index in links.items() if name != primary}
            _, transferred = _download(url, destination, remaining, report, live_links=live_links, recovery_id=recovery_id, **options)
            return time.monotonic() - started, totals | transferred
        try:
            if live_links:
                live_links.attach(conn)
            with response:
                match = re.fullmatch(r'bytes 0-0/([1-9][0-9]{0,14})', response.getheader('Content-Range', ''))
                etag = response.getheader('ETag', '')
                if response.status == 200:
                    if record:
                        raise ValueError('The server cannot resume this staged file safely.')
                    if live_links:
                        live_links.set_mode('single', {primary: links[primary]})
                    expected = content_length(response)
                    if expected is not None:
                        check_size(expected, destination.parent)
                    next_report = 0
                    with partial.open('wb') as out:
                        while True:
                            if live_links:
                                live_links.check()
                            block = response.read1(READ_BUFFER)
                            if not block:
                                break
                            totals[primary] += len(block)
                            if totals[primary] > MAX_FILE_SIZE or expected is not None and totals[primary] > expected:
                                raise OSError('The response exceeded its allowed file size.')
                            out.write(block)
                            if time.monotonic() >= next_report:
                                report(totals.copy(), expected)
                                next_report = time.monotonic() + .2
                    if isinstance(conn, ResponseLease):
                        conn.disarm()
                        conn.check()
                    if expected is not None and totals[primary] != expected:
                        raise OSError('The download ended before the full file arrived.')
                    report(totals.copy(), totals[primary] if expected is None else expected)
                    publish(partial, destination, overwrite=overwrite, expected_sha256=expected_sha256)
                    saved = True
                    return time.monotonic() - started, totals
                empty = response.status == 416 and response.getheader('Content-Range') == 'bytes */0'
                if not empty and (response.status != 206 or not match):
                    raise ValueError(f'Unexpected server response (HTTP {response.status}).')
                size = 0 if empty else int(match[1])
                effective_url = conn.url if isinstance(conn, ResponseLease) else url
        finally:
            if live_links:
                live_links.detach(conn)
            conn.close()

        if record and (record.data['size'] != size or record.data['etag'] != etag):
            raise ValueError('The file changed on the server. Start a new download.')
        if size == 0 or not re.fullmatch(r'"[\x21\x23-\x7e\x80-\xff]*"', etag):
            if live_links:
                live_links.set_mode('single', {primary: links[primary]})
            _, transferred = _download(url, destination, {primary: links[primary]}, report, live_links=live_links, ranged=False, **options)
            return time.monotonic() - started, totals | transferred

        range_size = record.data['chunk'] if record else CHUNK * 2 if live_links else CHUNK
        completed = record.verified() if record else set()
        recovered = sum(min(range_size, size - offset) for offset in completed)
        check_size(size - recovered, destination.parent)
        with partial.open('r+b') as out:
            out.truncate(size)
        if recovery_id and record is None:
            record = recovery_store.create(recovery_id, url, destination, partial, size, etag, range_size, expected_sha256,
                                           restricted=public_only or not overwrite)
        if recovered:
            totals['Recovered'] = recovered
            report(totals.copy(), size)
        offsets = (offset for offset in range(0, size, range_size) if offset not in completed)
        retry = queue.SimpleQueue()
        aborted = threading.Event()
        deadline = started + STREAM_TIMEOUT

        def fetch(name, offset, adapter=None):
            if live_links:
                live_links.check()
            elif time.monotonic() >= deadline:
                raise TimeoutError('The download exceeded its time limit.')
            end = min(size, offset + range_size) - 1
            conn, response = fetch_response(effective_url, links[name] if adapter is None else adapter, {
                'Range': f'bytes={offset}-{end}', 'If-Range': etag,
            })
            try:
                if live_links:
                    live_links.attach(conn)
                with response:
                    if (
                        response.status != 206
                        or isinstance(conn, ResponseLease) and conn.url != effective_url
                        or response.getheader('Content-Range') != f'bytes {offset}-{end}/{size}'
                        or response.getheader('ETag', etag) != etag
                        or response.getheader('Content-Encoding', 'identity').lower() != 'identity'
                    ):
                        raise ValueError('The server returned an invalid range or the file changed.')
                    length = end - offset + 1
                    if response.getheader('Content-Length') is not None or response.getheader('Transfer-Encoding') is not None:
                        declared = content_length(response)
                        if declared is not None and declared != length:
                            raise ValueError('The server returned an invalid range length.')
                    try:
                        out = partial.open('r+b', buffering=0)
                        try:
                            out.seek(offset)
                        except OSError:
                            out.close()
                            raise
                    except OSError as error:
                        raise StorageError('Could not open the staged file for a range write.') from error
                    received = 0
                    digest = hashlib.sha256()
                    # Each worker has its own file handle and writes only its assigned range.
                    with out:
                        while True:
                            if live_links:
                                live_links.check()
                            block = response.read1(min(READ_BUFFER, length - received + 1))
                            if not block:
                                break
                            received += len(block)
                            digest.update(block)
                            if received > length:
                                raise ValueError('The server returned more bytes than requested.')
                            try:
                                if out.write(block) != len(block):
                                    raise OSError('Short disk write.')
                            except OSError as error:
                                raise StorageError('Could not write to the staged file.') from error
                        if record:
                            os.fsync(out.fileno())
                    if isinstance(conn, ResponseLease):
                        conn.disarm()
                        conn.check()
                    if received != length:
                        raise OSError('The server returned an incomplete chunk.')
            finally:
                if live_links:
                    live_links.detach(conn)
                conn.close()
            with lock:
                if record:
                    record.completed(offset, digest.hexdigest())
                totals[name] = totals.get(name, 0) + received
                report(totals.copy(), size)

        if live_links:
            live_links.set_mode('range')
            run_live_ranges(live_links, offsets, fetch)
            live_links.set_mode('scanning')
        else:
            def worker(name):
                while not aborted.is_set():
                    with lock:
                        offset = next(offsets, None)
                    if offset is None:
                        return
                    try:
                        fetch(name, offset)
                    except (OSError, http.client.HTTPException) as error:
                        failure('range-worker-retrying', error)
                        retry.put((offset, name))
                        return
                    except BaseException:
                        aborted.set()
                        raise

            with concurrent.futures.ThreadPoolExecutor(max_workers=len(links) * STREAMS_PER_LINK, thread_name_prefix=threading.current_thread().name + '-range') as pool:
                futures = [pool.submit(worker, name) for name in links for _ in range(STREAMS_PER_LINK)]
                for future in futures:
                    future.result()
            failed_chunks = []
            while not retry.empty():
                failed_chunks.append(retry.get())
            failed_links = {name for _, name in failed_chunks}
            order = sorted(links, key=lambda name: name in failed_links)
            for offset, failed in chain(failed_chunks, ((offset, None) for offset in offsets)):
                last_error = None
                for name in order:
                    if name == failed:
                        continue
                    try:
                        fetch(name, offset)
                        break
                    except (OSError, http.client.HTTPException) as error:
                        last_error = error
                else:
                    raise OSError('No selected adapter could retrieve a remaining file chunk.') from last_error
        if live_links and live_links.status()['cancelled']:
            live_links.check()
        if sum(totals.values()) != size:
            raise OSError('The download ended before the full file arrived.')
        publish(partial, destination, overwrite=overwrite, expected_sha256=expected_sha256)
        saved = True
        return time.monotonic() - started, totals
    except (DownloadCancelled, ScanError):
        preserve = False
        raise
    finally:
        if record is None or saved or not preserve:
            partial.unlink(missing_ok=True)
            if record:
                record.remove()


def table(parent, columns):
    frame = ttk.Frame(parent)
    frame.pack(fill='both', expand=True, pady=(8, 0))
    keys = [name for name, _ in columns]
    view = ttk.Treeview(frame, columns=keys, show='headings', selectmode='browse')
    for name, width in columns:
        numeric = name.endswith(('Mbps', 'MiB'))
        anchor = 'e' if numeric else 'w'
        view.heading(name, text=name, anchor=anchor)
        view.column(name, width=width, minwidth=width, stretch=name in ('Adapter', 'Details'), anchor=anchor)
    vertical = ttk.Scrollbar(frame, orient='vertical', command=view.yview)
    horizontal = ttk.Scrollbar(frame, orient='horizontal', command=view.xview)
    view.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
    view.grid(row=0, column=0, sticky='nsew')
    vertical.grid(row=0, column=1, sticky='ns')
    horizontal.grid(row=1, column=0, sticky='ew')
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(0, weight=1)
    return view


def main():
    root = tk.Tk()
    root.title('Net Booster')
    root.geometry('1040x640')
    root.minsize(740, 600)
    shell = ttk.Frame(root, padding=(24, 18), style='Shell.TFrame')
    shell.pack(fill='both', expand=True)
    header = ttk.Frame(shell, style='Shell.TFrame')
    header.pack(fill='x', pady=(0, 19))
    header.columnconfigure(0, weight=1)
    ttk.Label(header, text='Net Booster', style='Brand.TLabel').grid(row=0, column=0, sticky='w')
    ttk.Label(header, text='File transfers and network activity', style='Shell.TLabel').grid(
        row=1, column=0, sticky='w', pady=(2, 0))
    theme = tk.StringVar(value=appearance.preference())
    ttk.Label(header, text='Appearance', style='Shell.TLabel').grid(row=0, column=1, sticky='s')
    theme_select = ttk.Combobox(header, textvariable=theme, values=appearance.MODES, state='readonly', width=10)
    theme_select.grid(row=1, column=1, sticky='e', pady=(5, 0))
    theme_note = tk.StringVar()
    theme_error = ttk.Label(header, textvariable=theme_note, style='Shell.TLabel')
    nav = ttk.Frame(shell, style='Shell.TFrame')
    nav.pack(fill='x', pady=(0, 12))
    tabs = ttk.Notebook(shell)
    tabs.pack(fill='both', expand=True)
    tabs.enable_traversal()
    panel = ttk.Frame(tabs, padding=24)
    network = ttk.Frame(tabs, padding=24)
    activity = ttk.Frame(tabs, padding=24)
    tabs.add(panel, text='Download')
    tabs.add(network, text='Network')
    tabs.add(activity, text='History')
    navigation = []
    for index, label in enumerate(('Download', 'Network', 'History')):
        item = ttk.Button(nav, text=label, style='Nav.TButton', command=lambda i=index: tabs.select(i))
        item.pack(side='left', padx=(0, 6))
        navigation.append(item)
    network_status = tk.StringVar(value='Reading Windows adapter counters…')
    ttk.Label(network, text='Network activity', style='Heading.TLabel').pack(anchor='w')
    ttk.Label(network, textvariable=network_status, style='Muted.TLabel').pack(anchor='w', pady=(5, 0))
    ttk.Label(network, text='Rates include traffic from all apps. Link rate is the speed negotiated by the adapter.',
              style='Muted.TLabel').pack(anchor='w', pady=(2, 10))
    live = table(network, [
        ('Adapter', 205), ('Status', 96), ('IPv4 address', 125), ('Link rate', 91),
        ('Receive Mbps', 104), ('Send Mbps', 87), ('Received MiB', 105), ('Sent MiB', 74),
    ])
    history_status = tk.StringVar(value='Connection changes and download results are saved locally.')
    ttk.Label(activity, text='Connection and download history', style='Heading.TLabel').pack(anchor='w')
    ttk.Label(activity, textvariable=history_status, style='Muted.TLabel').pack(anchor='w', pady=(5, 10))
    events = table(activity, [
        ('Local time', 155), ('Type', 95), ('Adapter or file', 205), ('Result', 90), ('Details', 340),
    ])
    history = None
    try:
        history = History()
    except (OSError, sqlite3.Error) as error:
        history_status.set(f'History unavailable. {error}')

    def load_history():
        if history is None:
            return
        try:
            records = history.recent()
        except sqlite3.Error as error:
            history_status.set(f'Could not read history. {error}')
            return
        events.delete(*events.get_children())
        for index, (stamp, *record) in enumerate(records):
            events.insert('', 'end', values=(stamp[:19].replace('T', ' '), *record),
                          tags=('stripe',) if index % 2 else ())
        if not records:
            history_status.set('History will appear when adapters are detected or a download finishes.')

    def record(category, subject, outcome, details):
        if history is not None:
            try:
                history.add(category, subject, outcome, details)
                return True
            except sqlite3.Error as error:
                history_status.set(f'Could not save history. {error}')
        return False

    load_history()
    panel.columnconfigure(0, weight=1)
    form = ttk.Frame(panel)
    form.grid(row=0, column=0, sticky='nsew', padx=(0, 28))
    form.columnconfigure(0, weight=1)
    transfer = ttk.Frame(panel, padding=20, style='Inset.TFrame')
    transfer.grid(row=0, column=1, sticky='new')
    ttk.Label(form, text='New download', style='Heading.TLabel').grid(sticky='w')
    ttk.Label(form, text='Choose up to seven connections for one file.',
              style='Muted.TLabel').grid(sticky='w', pady=(5, 20))
    ttk.Label(form, text='HTTPS file URL', style='FieldLabel.TLabel').grid(sticky='w', pady=(0, 6))
    url = ttk.Entry(form)
    url.grid(sticky='ew')
    picker_header = ttk.Frame(form)
    picker_header.grid(sticky='ew', pady=(21, 6))
    ttk.Label(picker_header, text='Connections', style='FieldLabel.TLabel').pack(side='left')
    selection_text = tk.StringVar(value='0 selected')
    ttk.Label(picker_header, textvariable=selection_text, style='Muted.TLabel').pack(side='right')
    picker = ttk.Frame(form)
    picker.grid(sticky='ew')
    picker.columnconfigure(0, weight=1)
    adapters = tk.Listbox(picker, selectmode='multiple', exportselection=False, height=5,
                          font=('Segoe UI', 11), borderwidth=0, activestyle='none', highlightthickness=1)
    adapters.grid(row=0, column=0, sticky='ew')
    scrollbar = ttk.Scrollbar(picker, orient='vertical', command=adapters.yview)
    scrollbar.grid(row=0, column=1, sticky='ns', padx=(3, 0))
    adapters.configure(yscrollcommand=scrollbar.set)
    picker_note = tk.StringVar(value='Waiting for Windows to detect available connections…')
    ttk.Label(form, textvariable=picker_note, style='Muted.TLabel', wraplength=325).grid(
        sticky='w', pady=(7, 0))
    ttk.Label(transfer, text='Transfer', style='InsetTitle.TLabel').pack(anchor='w')
    progress_text = tk.StringVar(value='Ready')
    ttk.Label(transfer, textvariable=progress_text, style='Metric.TLabel').pack(anchor='w', pady=(11, 7))
    progress = appearance.Progress(root, transfer)
    progress.bar.pack(fill='x', pady=(0, 14))
    status = tk.StringVar(value='Paste a file link to start.')
    ttk.Label(transfer, textvariable=status, style='InsetMuted.TLabel', width=25,
              wraplength=172).pack(anchor='w')
    messages = queue.Queue()
    choices = {}

    last_sample = None
    previous_states = {}
    sampling = False

    def refresh():
        nonlocal sampling
        if sampling:
            return
        sampling = True

        def read():
            try:
                messages.put(('sample', snapshot()))
            except Exception as error:
                messages.put(('sample error', str(error)))

        threading.Thread(target=read, daemon=True).start()

    def update_network(sample):
        nonlocal last_sample, previous_states
        now, rows = sample
        old_time, old_rows = last_sample or (now, [])
        by_index = {row['index']: row for row in old_rows}
        current = {row['name']: (row['status'], row['ip']) for row in rows}
        changed = False
        for event in changes(previous_states, current):
            changed = record('Connection', *event) or changed
        if changed:
            history_status.set('Showing up to 500 recent events. History is saved locally.')
            load_history()
        previous_states = current

        present = set()
        for index, row in enumerate(rows):
            key = str(row['index'])
            present.add(key)
            prior = by_index.get(row['index'], {})
            comparable = row['status'] == prior.get('status') == 'Up'

            def rate(direction):
                value = mbps(prior.get(direction), row[direction], now - old_time) if comparable else None
                return f'{value:.2f}' if value is not None else '—'

            def volume(direction):
                value = row[direction]
                return f'{value / 1048576:,.1f}' if value is not None else '—'

            values = (
                row['name'], row['status'], row['ip'] or '—', row['link'],
                rate('rx'), rate('tx'), volume('rx'), volume('tx'),
            )
            tags = ('stripe',) if index % 2 else ()
            if live.exists(key):
                live.item(key, values=values, tags=tags)
            else:
                live.insert('', 'end', iid=key, values=values, tags=tags)
        for key in set(live.get_children()) - present:
            live.delete(key)
        last_sample = sample
        network_status.set(f'{len(rows)} adapters  |  Updated {datetime.now():%H:%M:%S}')

        found = {row['name']: row['index'] for row in rows if row['gateway'] and row['status'] == 'Up'}
        if choices != found or not found:
            previous = tuple(choices)
            selected = {previous[i] for i in adapters.curselection()}
            choices.clear()
            choices.update(sorted(found.items(), key=lambda item: (item[0] != 'Wi-Fi', item[0].casefold())))
            adapters.delete(0, 'end')
            for index, name in enumerate(choices):
                adapters.insert('end', f'  {name}')
                if name in selected or not previous and index == 0:
                    adapters.selection_set(index)
            selection_changed()

    def selection_changed(_=None):
        indices = adapters.curselection()
        if len(indices) > MAX_CONNECTIONS:
            for index in indices[MAX_CONNECTIONS:]:
                adapters.selection_clear(index)
            indices = indices[:MAX_CONNECTIONS]
        selection_text.set(f'{len(indices)} of {MAX_CONNECTIONS} selected')
        picker_note.set(
            'Click to toggle. The first selected connection checks the file.' if choices
            else 'No active IPv4 connection. Connect an adapter and refresh.'
        )

    def monitor():
        refresh()
        root.after(3500, monitor)

    def start():
        address = url.get().strip()
        try:
            parts = urlsplit(address)
        except ValueError as error:
            status.set(str(error))
            return
        names = tuple(choices)
        links = {names[index]: choices[names[index]] for index in adapters.curselection()[:MAX_CONNECTIONS]}
        if parts.scheme != 'https' or not parts.hostname or parts.username is not None or not links:
            status.set('Enter a direct HTTPS URL and select at least one connection.')
            return
        target = filedialog.asksaveasfilename(
            initialfile=Path(unquote(parts.path)).name or 'download.bin'
        )
        if not target:
            return
        button.state(['disabled'])
        progress.show(0)
        progress.show(None)
        progress_text.set('Starting')
        status.set('Connecting…')

        def run():
            try:
                elapsed, totals = download(address, target, links, lambda *args: messages.put(('progress', args)))
                messages.put(('done', (Path(target).name, elapsed, totals)))
            except Exception as error:
                messages.put(('error', (Path(target).name, str(error))))

        threading.Thread(target=run, daemon=True).start()

    def describe(totals):
        return '  |  '.join(f'{name}: {count / 1048576:.2f} MiB' for name, count in totals.items())

    def poll():
        nonlocal sampling
        while not messages.empty():
            kind, value = messages.get_nowait()
            if kind == 'sample':
                sampling = False
                update_network(value)
            elif kind == 'sample error':
                sampling = False
                last = ' Previous readings are stale.' if last_sample else ''
                network_status.set(f'Could not refresh adapter statistics.{last} See the next automatic refresh.')
            elif kind == 'progress':
                totals, size = value
                percent = min(100, 100 * sum(totals.values()) / size) if size else None
                progress.show(percent)
                progress_text.set(f'{percent:.0f}%' if percent is not None else 'Receiving')
                status.set(describe(totals).replace('  |  ', '\n'))
            elif kind == 'done':
                filename, elapsed, totals = value
                progress.show(100)
                progress_text.set('Saved')
                details = f'{elapsed:.1f}s  |  {describe(totals)}'
                breakdown = describe(totals).replace('  |  ', '\n')
                status.set(f'Saved in {elapsed:.1f}s\n\n{breakdown}')
                if record('Download', filename, 'Saved', details):
                    load_history()
                button.state(['!disabled'])
            else:
                filename, error = value
                progress.show(0)
                progress_text.set('Failed')
                status.set(f'Download failed. {error}')
                if record('Download', filename, 'Failed', 'See the Download tab for the error.'):
                    load_history()
                button.state(['!disabled'])
        root.after(100, poll)

    actions = ttk.Frame(form)
    actions.grid(sticky='w', pady=(18, 0))
    button = ttk.Button(actions, text='Download…', command=start, style='Primary.TButton')
    button.pack(side='left')
    ttk.Button(actions, text='Refresh adapters', command=refresh).pack(side='left', padx=(8, 0))
    url.bind('<Return>', lambda _: button.invoke())
    adapters.bind('<<ListboxSelect>>', selection_changed)

    applied_mode = None

    def update_theme():
        nonlocal applied_mode
        mode = appearance.resolve(theme.get())
        if mode != applied_mode:
            applied_mode = mode
            palette = appearance.apply(root, mode)
            adapters.configure(background=palette['field'], foreground=palette['text'],
                               highlightbackground=palette['line'], highlightcolor=palette['accent'],
                               selectbackground=palette['selected'], selectforeground=palette['text'])
            for view in (live, events):
                view.tag_configure('stripe', background=palette['stripe'])

    def select_theme(_):
        update_theme()
        try:
            appearance.save_preference(theme.get())
            theme_error.grid_remove()
        except OSError:
            theme_note.set('Theme could not be saved.')
            theme_error.grid(row=2, column=1, sticky='e')

    def follow_system():
        update_theme()
        root.after(2000, follow_system)

    animation = None

    def reveal_tab(_):
        nonlocal animation
        if animation:
            root.after_cancel(animation)
        for pane in (panel, network, activity):
            pane.configure(padding=24)
        selected = tabs.index('current')
        for index, item in enumerate(navigation):
            item.state(['selected' if index == selected else '!selected'])
        if not appearance.motion_enabled():
            return
        pane = root.nametowidget(tabs.select())

        def step(offset):
            nonlocal animation
            pane.configure(padding=(24 + offset, 24, 24 - offset, 24))
            animation = root.after(16, step, offset - 1) if offset else None

        step(7)

    theme_select.bind('<<ComboboxSelected>>', select_theme)
    tabs.bind('<<NotebookTabChanged>>', reveal_tab)
    follow_system()
    root.protocol('WM_DELETE_WINDOW', lambda: root.destroy() if not button.instate(['disabled']) else None)
    monitor()
    poll()
    root.mainloop()


if __name__ == '__main__':
    main()
