"""Local WebView2 host for the React desktop interface."""
import sys
import browser_bridge
from runtime_paths import is_packaged, executable, resource_root

if __name__ == '__main__' and browser_bridge.native_invocation(sys.argv[1:]):
    raise SystemExit(browser_bridge.host(sys.argv[1:]))
if __name__ == '__main__' and '--mcp-server' in sys.argv:
    import io
    sys.stdin = io.TextIOWrapper(browser_bridge.native_stream('rb'), encoding='utf-8')
    sys.stdout = io.TextIOWrapper(browser_bridge.native_stream('wb'), encoding='utf-8', write_through=True)
    from mcp_portflock import main as mcp_main
    mcp_main([value for value in sys.argv[1:] if value != '--mcp-server'])
    raise SystemExit(0)
if __name__ == '__main__' and '--browser-setup' in sys.argv:
    from browser_setup import setup
    setup()
    raise SystemExit(0)
if __name__ == '__main__' and '--browser-remove' in sys.argv:
    from browser_setup import remove_registration
    remove_registration()
    raise SystemExit(0)

if __name__ == '__main__' and sys.argv[1:] and sys.argv[1:] != ['--startup']:
    from cli import main as cli_main
    raise SystemExit(cli_main(sys.argv[1:]))

from datetime import datetime
from pathlib import Path
import os
import sqlite3
import sys
import threading
import time
from uuid import uuid4
import recovery as recovery_store
from urllib.parse import unquote

import webview

import appearance
import windows_startup
from speed_test import SpeedTest
from version import VERSION
from diagnostics import LOGGER, configure, failure
from net_booster import MAX_CONNECTIONS, DownloadCancelled, DownloadStopped, LiveLinks, download, validate_url
from network_monitor import History, changes, mbps, snapshot, storage_snapshot, traffic_snapshot


PRIORITIES = {'high': 0, 'normal': 1, 'low': 2}


class Desktop:
    def __init__(self, restore=True):
        self._speed_test = SpeedTest()
        self._lock = threading.Lock()
        self._refresh = threading.Event()
        self._rows = []
        self._storage = []
        self._storage_updated = ''
        self._updated = ''
        self._traffic_stamp = None
        self._traffic_error = ''
        self._network_error = ''
        self._condition = threading.Condition(self._lock)
        self._jobs = {}
        self._next_id = 1
        self._choosing = False
        self._turbo_id = None
        self._shutdown_requested = False
        self._allow_close = False
        self._threads = []
        self._browser_inbox = None
        self._browser_restored = False
        self._history_revision = 0
        try:
            self._history = History()
        except (OSError, sqlite3.Error) as error:
            failure('history-open-failed', error)
            self._history = None

        if restore:
            self._restore_downloads()

    def _on_closing(self):
        self._speed_test.cancel()
        if self._allow_close or not self._busy():
            return True
        def prompt():
            try:
                self._window.evaluate_js("window.dispatchEvent(new Event('portflock-close-request'))")
            except Exception as error:
                failure('close-prompt-failed', error)
        threading.Thread(target=prompt, name='close-prompt', daemon=True).start()
        return False

    def close_app(self, action):
        self._speed_test.cancel()
        if action not in ('save', 'cancel'):
            return 'Choose whether to save progress or cancel downloads.'
        with self._condition:
            if self._shutdown_requested:
                return None
            self._shutdown_requested = True
            self._refresh.set()
            for job in self._jobs.values():
                if job['view']['state'] == 'running':
                    job['selection'].cancel(preserve=action == 'save')
            discard = [job.get('recovery_id') for job in self._jobs.values()
                       if action == 'cancel' and job['view']['state'] != 'running' and job.get('recovery_id')]
            self._condition.notify_all()
        def finish():
            if action == 'cancel' and self._browser_inbox:
                try:
                    for token, _, _ in self._browser_inbox.pending(restore=True):
                        self._browser_inbox.mark(token, 'cancelled')
                except (OSError, sqlite3.Error) as error:
                    failure('browser-close-cancel-failed', error)
            for identifier in discard:
                try:
                    with recovery_store.claim(identifier):
                        record = recovery_store.load(identifier)
                        if record:
                            record.partial.unlink(missing_ok=True)
                            record.remove()
                except (OSError, ValueError, TypeError, KeyError) as error:
                    failure('close-discard-failed', error)
            deadline = time.monotonic() + 20
            for thread in self._threads:
                thread.join(max(0, deadline - time.monotonic()))
            LOGGER.info('window-closing save_progress=%s', action == 'save')
            self._allow_close = True
            self._window.destroy()
        threading.Thread(target=finish, name='graceful-close', daemon=True).start()
        return None

    def _restore_downloads(self):
        try:
            records = recovery_store.pending()
        except OSError as error:
            failure('recovery-list-failed', error)
            return
        for record in records:
            data = record.data
            identifier = self._next_id
            self._next_id += 1
            recovered = sum(min(data['chunk'], data['size'] - int(offset)) for offset in data['chunks'])
            self._jobs[identifier] = {
                'recovery_id': record.identifier, 'activity': {},
                'restricted': data.get('restricted') is True,
                'view': {'id': identifier, 'state': 'recoverable', 'priority': 'normal',
                         'filename': Path(data['target']).name,
                         'totals': {'Recovered': recovered}, 'size': data['size']},
            }
        if records:
            LOGGER.info('recovery-downloads-found count=%s', len(records))

    def resume_download(self, identifier, ids):
        if (type(identifier) is not int or not isinstance(ids, list)
                or not 1 <= len(ids) <= MAX_CONNECTIONS
                or any(type(index) is not int for index in ids) or len(set(ids)) != len(ids)):
            return 'Select one to seven available connections.'
        with self._condition:
            job = self._jobs.get(identifier)
            if not job or job['view']['state'] not in ('recoverable', 'failed'):
                return 'This download cannot be recovered.'
            try:
                record = recovery_store.load(job.get('recovery_id'))
            except (OSError, ValueError, TypeError, KeyError):
                return 'The saved progress is unavailable or invalid.'
            if record is None:
                return 'No saved ranges are available for this download.'
            available = {row['index']: row['name'] for row in self._rows if row['status'] == 'Up' and row['gateway']}
            if any(index not in available for index in ids):
                return 'A selected connection is unavailable.'
            target = record.data['target']
            key = os.path.normcase(str(Path(target).resolve()))
            if any(other['view']['state'] in ('queued', 'running') and other.get('key') == key
                   for other in self._jobs.values()):
                return 'Another download is already writing to this destination.'
            links = {available[index]: index for index in ids}
            job.update(url=record.data['url'], target=target, key=key, links=links, selection=LiveLinks(links))
            job['view'].update(state='queued', error=None)
            self._condition.notify()
        LOGGER.info('transfer-recovery-queued transfer=%s', identifier)
        return None

    def _rebalance(self):
        running = [job for job in self._jobs.values() if job['view']['state'] == 'running']
        if self._turbo_id is not None:
            allowed = {self._turbo_id}
        else:
            ordered = sorted(running, key=lambda job: (
                job['selection'].status()['held'], job['view']['id']))
            allowed = {job['view']['id'] for job in ordered[:2]}
        for job in running:
            job['selection'].hold(job['view']['id'] not in allowed)

    def set_turbo(self, identifier, enabled):
        if type(identifier) is not int or type(enabled) is not bool:
            return 'Invalid Turbo selection.'
        with self._condition:
            job = self._jobs.get(identifier)
            if not job or job['view']['state'] not in ('queued', 'running'):
                return 'Turbo is available for waiting or active downloads.'
            if enabled:
                if self._turbo_id not in (None, identifier):
                    return 'Turn off Turbo on the other file first.'
                mode = job['selection'].snapshot()[0]
                if mode in ('single', 'scanning'):
                    return 'This file is not accepting additional connections.'
                if job['selection'].status()['paused']:
                    return 'Resume this download before enabling Turbo.'
                others = [other for other in self._jobs.values()
                          if other is not job and other['view']['state'] == 'running']
                if any(other['selection'].snapshot()[0] not in ('range', 'scanning') for other in others):
                    return 'Wait for the other file to finish checking, or cancel its single-stream transfer.'
                links = {row['name']: row['index'] for row in self._rows
                         if row['status'] == 'Up' and row['gateway']}
                if not links:
                    return 'Connect an internet adapter before enabling Turbo.'
                if len(links) > MAX_CONNECTIONS:
                    return 'Turbo supports up to seven available connections.'
                self._turbo_id = identifier
                if job['view']['state'] == 'queued':
                    job['links'] = links
                    job['selection'] = LiveLinks(links)
                    job['view']['totals'] = dict.fromkeys(links, 0)
                elif mode == 'range':
                    job['selection'].update(links)
            elif self._turbo_id == identifier:
                self._turbo_id = None
            self._rebalance()
            self._condition.notify_all()
        LOGGER.info('transfer-turbo transfer=%s enabled=%s', identifier, enabled)
        return None

    def startup_preferences(self):
        return windows_startup.preferences()

    def set_startup(self, enabled):
        result = windows_startup.set_enabled(enabled)
        LOGGER.info('windows-startup enabled=%s', enabled)
        return result

    def mcp_configuration(self):
        if is_packaged():
            return dict(command=str(executable()), args=['--mcp-server'], available=True,
                        bundled=True, defaultRoot=str(Path.home() / 'Downloads'))
        script = Path(__file__).parent / 'mcp_portflock.py'
        return dict(command='uv', scriptPath=str(script.resolve()), available=script.is_file(),
                    args=['run', '--script', '--python', '3.14', str(script.resolve())],
                    defaultRoot=str(Path.home() / 'Downloads'))

    def prepare_mcp(self):
        return self.mcp_configuration()

    def _record(self, *event):
        if self._history:
            try:
                self._history.add(*event)
                with self._lock:
                    self._history_revision += 1
            except sqlite3.Error as error:
                failure('history-write-failed', error)

    def _monitor(self):
        previous = {}
        timestamp = 0
        states = {}
        unavailable = False
        storage_due = 0
        while not self._shutdown_requested:
            try:
                now, rows = snapshot()
                current = {row['name']: (row['status'], row['ip']) for row in rows}
                for event in changes(states, current):
                    self._record('Connection', *event)
                for row in rows:
                    prior = previous.get(row['index'], {})
                    for counter in ('rx', 'tx'):
                        row[counter + 'Rate'] = (
                            mbps(prior.get(counter), row[counter], now - timestamp)
                            if row['status'] == prior.get('status') == 'Up' else None
                        )
                previous = {row['index']: row for row in rows}
                states, timestamp = current, now
                if unavailable:
                    LOGGER.info('adapter-monitor-recovered adapter_count=%s', len(rows))
                    unavailable = False
                with self._lock:
                    existing = {row['name']: row for row in self._rows}
                    for row in rows:
                        current = existing.get(row['name'], {})
                        for key in ('rxRate', 'txRate'):
                            row[key] = current.get(key)
                        for key in ('rx', 'tx'):
                            row[key] = current.get(key, row[key])
                    self._rows = rows
                    self._network_error = ''
                    if self._turbo_id is not None:
                        turbo = self._jobs.get(self._turbo_id)
                        links = {row['name']: row['index'] for row in rows
                                 if row['status'] == 'Up' and row['gateway']}
                        if turbo and links and len(links) <= MAX_CONNECTIONS:
                            turbo['selection'].update(links)
            except Exception as error:
                if not unavailable:
                    failure('adapter-monitor-failed', error)
                    unavailable = True
                with self._lock:
                    self._network_error = 'Windows adapter readings are unavailable. Retrying shortly.'
            if time.monotonic() >= storage_due:
                try:
                    drives = storage_snapshot()
                    with self._lock:
                        self._storage = drives
                        self._storage_updated = datetime.now().strftime('%H:%M:%S')
                except (OSError, ValueError) as error:
                    failure('storage-monitor-failed', error)
                storage_due = time.monotonic() + 12
            self._refresh.wait(3.5)
            self._refresh.clear()

    def _traffic_monitor(self):
        previous = {}
        timestamp = 0
        while not self._shutdown_requested:
            try:
                now, counters = traffic_snapshot()
                with self._lock:
                    rows = []
                    for row in self._rows:
                        current = counters.get(row['name'], {})
                        prior = previous.get(row['name'], {})
                        updated = row.copy()
                        for counter in ('rx', 'tx'):
                            updated[counter + 'Rate'] = (
                                mbps(prior.get(counter), current.get(counter), now - timestamp)
                                if row['status'] == 'Up' else None)
                            updated[counter] = current.get(counter)
                        rows.append(updated)
                    self._rows = rows
                    self._traffic_stamp = now
                    self._updated = datetime.now().strftime('%H:%M:%S')
                    self._traffic_error = ''
                previous, timestamp = counters, now
            except OSError as error:
                if not self._traffic_error:
                    failure('traffic-counter-failed', error)
                self._traffic_error = 'Live traffic counters are unavailable.'
            # A stop event lets shutdown release the native monitor promptly.
            for _ in range(10):
                if self._shutdown_requested:
                    return
                time.sleep(.1)

    def state(self):
        theme = appearance.resolve('System').lower()
        reduced_motion = not appearance.motion_enabled()
        startup = windows_startup.preferences()
        with self._lock:
            now = time.monotonic()
            jobs = []
            for job in self._jobs.values():
                view = job['view']
                active = [name for name, stamp in job['activity'].items()
                          if view['state'] == 'running' and now - stamp < 3]
                held_waiting = view['state'] == 'queued' and self._turbo_id not in (None, view['id'])
                routing = dict(turbo=self._turbo_id == view['id'], held=held_waiting)
                if held_waiting:
                    routing['state'] = 'held'
                if 'selection' in job:
                    mode, _, selected = job['selection'].snapshot()
                    control = job['selection'].status()
                    is_held = control['held'] or held_waiting
                    state = ('cancelling' if control['cancelled'] else 'paused' if control['paused']
                             else 'held' if is_held else 'reconnecting' if control['retrying'] else view['state'])
                    routing.update(routing=mode, selectedAdapters=list(selected), state=state, held=is_held)
                jobs.append(dict(view, active=active, rate=view.get('rate', 0) if active else 0, **routing))
            age = now - self._traffic_stamp if self._traffic_stamp is not None else None
            rows = self._rows
            if age is None or age > 3:
                rows = [dict(row, rxRate=None, txRate=None) for row in rows]
            return {
                'rows': rows, 'updated': self._updated, 'trafficAge': age,
                'storage': self._storage, 'storageUpdated': self._storage_updated,
                'networkError': self._traffic_error or self._network_error, 'jobs': jobs, 'choosing': self._choosing,
                'maxConnections': MAX_CONNECTIONS, 'turboId': self._turbo_id, 'startup': startup,
                'systemTheme': theme, 'reducedMotion': reduced_motion,
                'historyRevision': self._history_revision, 'speedTest': self._speed_test.snapshot(),
            }

    def start_speed_test(self, adapter):
        with self._lock:
            if self._shutdown_requested:
                return 'The app is closing.'
            row = next((row for row in self._rows if type(adapter) is int and row['index'] == adapter
                        and row.get('gateway') and row.get('status') == 'Up'), None)
            if not row:
                return 'Choose a connected adapter with an IPv4 gateway.'
            if any(job['view']['state'] == 'running' for job in self._jobs.values()):
                return 'Pause active downloads before testing for a clearer measurement.'
            return self._speed_test.start(adapter, row['name'])

    def cancel_speed_test(self):
        return self._speed_test.cancel()

    def preferences(self):
        return {'theme': appearance.preference().lower(), 'displayName': appearance.display_name(), **appearance.transfer_preferences()}

    def set_display_name(self, value):
        return appearance.save_display_name(value)

    def set_theme(self, theme):
        if theme not in ('system', 'light', 'dark'):
            raise ValueError('Invalid appearance.')
        appearance.save_preference(theme.title())

    def set_transfer_preference(self, name, value):
        appearance.save_transfer_preference(name, value)

    def refresh(self):
        self._refresh.set()

    def setup_browser_extension(self):
        from browser_setup import setup
        return setup()

    def _browser_monitor(self):
        try:
            self._browser_inbox = browser_bridge.Inbox()
        except (OSError, ValueError, sqlite3.Error) as error:
            failure('browser-inbox-unavailable', error)
            return
        while not self._shutdown_requested:
            try:
                self._accept_browser_requests()
            except (OSError, ValueError, sqlite3.Error) as error:
                failure('browser-inbox-read-failed', error)
            for _ in range(10):
                if self._shutdown_requested:
                    return
                time.sleep(.1)

    def _accept_browser_requests(self):
        inbox = self._browser_inbox
        with self._condition:
            links = {row['name']: row['index'] for row in self._rows if row['status'] == 'Up' and row['gateway']}
            links = dict(list(links.items())[:MAX_CONNECTIONS])
            if not links or self._shutdown_requested:
                return
            for token, url, filename in inbox.pending(restore=not self._browser_restored):
                existing = next((job for job in self._jobs.values() if job.get('recovery_id') == token), None)
                if existing:
                    existing['browser_id'] = token
                    existing['restricted'] = True
                    inbox.mark(token, 'queued')
                    continue
                if sum(job['view']['state'] in ('queued', 'running') for job in self._jobs.values()) >= 50:
                    return
                browser_bridge.validate_public_url(url)
                import winreg
                try:
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders') as key:
                        downloads = os.path.expandvars(winreg.QueryValueEx(key, '{374DE290-123F-4565-9164-39C4925E467B}')[0])
                except OSError:
                    downloads = str(Path.home() / 'Downloads')
                folder = browser_bridge.plain_directory(Path(downloads) / 'FetchVolt')
                # Reconstruct the basename from the trusted request ID, never an inbox path.
                if (filename != Path(filename).name or token[:12] not in filename or
                        any(ord(c) < 32 or c in '<>:"/\\|?*' for c in filename) or os.path.isreserved(filename)):
                    inbox.mark(token, 'failed')
                    continue
                target = folder / filename
                if target.exists():
                    inbox.mark(token, 'failed')
                    continue
                identifier = self._next_id
                self._next_id += 1
                self._jobs[identifier] = {
                    'url': url, 'target': str(target), 'key': os.path.normcase(str(target.resolve())),
                    'links': links.copy(), 'activity': {}, 'selection': LiveLinks(links),
                    'recovery_id': token, 'browser_id': token, 'restricted': True,
                    'view': {'id': identifier, 'state': 'queued', 'priority': 'normal',
                             'filename': filename, 'totals': dict.fromkeys(links, 0), 'size': None},
                }
                inbox.mark(token, 'queued')
                LOGGER.info('browser-transfer-queued transfer=%s adapters=%s', identifier, len(links))
                self._condition.notify_all()
            self._browser_restored = True

    def history(self):
        if self._history is None:
            raise RuntimeError('Local history is unavailable.')
        return self._history.recent()

    def _busy(self):
        with self._lock:
            return self._choosing or any(job['view']['state'] in ('queued', 'running')
                                         for job in self._jobs.values())

    def start(self, url, ids, priority):
        if not isinstance(priority, str) or priority not in PRIORITIES:
            return 'Choose a valid priority.'
        if not isinstance(url, str) or not isinstance(ids, list) or not 1 <= len(ids) <= MAX_CONNECTIONS:
            return f'Select one to {MAX_CONNECTIONS} connections and enter a direct HTTPS link.'
        if any(type(index) is not int for index in ids) or len(set(ids)) != len(ids):
            return f'Select one to {MAX_CONNECTIONS} distinct connections.'
        try:
            parts = validate_url(url)
        except ValueError:
            return 'Enter a direct HTTPS file URL without embedded credentials.'
        with self._lock:
            if self._choosing:
                return 'Finish choosing the current save location first.'
            if sum(job['view']['state'] in ('queued', 'running') for job in self._jobs.values()) >= 50:
                return 'The transfer queue is full.'
            available = {row['index']: row['name'] for row in self._rows if row['status'] == 'Up' and row['gateway']}
            if any(index not in available for index in ids):
                return 'A selected connection is unavailable. Refresh and select it again.'
            links = {available[index]: index for index in ids}
            self._choosing = True
        try:
            filename = Path(unquote(parts.path)).name or 'download.bin'
            filename = ''.join(char for char in filename if ord(char) >= 32 and char not in '<>:"/\\|?*')
            target = self._window.create_file_dialog(webview.FileDialog.SAVE, save_filename=filename or 'download.bin')
            if not target:
                return None
            if isinstance(target, (list, tuple)):
                target = target[0]
            key = os.path.normcase(str(Path(target).resolve()))
            with self._condition:
                if any(job['view']['state'] in ('queued', 'running') and job['key'] == key
                       for job in self._jobs.values()):
                    return 'Another transfer is already using that save location.'
                identifier = self._next_id
                self._next_id += 1
                self._jobs[identifier] = {
                    'url': url, 'target': target, 'key': key, 'links': links, 'activity': {},
                    'selection': LiveLinks(links), 'recovery_id': uuid4().hex,
                    'view': {'id': identifier, 'state': 'queued', 'priority': priority,
                             'filename': Path(target).name, 'totals': dict.fromkeys(links, 0), 'size': None},
                }
                LOGGER.info('transfer-queued transfer=%s adapters=%s priority=%s', identifier, len(links), priority)
                self._condition.notify()
                return identifier
        except (OSError, RuntimeError) as error:
            failure('save-location-failed', error)
            return 'Could not open the save location.'
        finally:
            with self._lock:
                self._choosing = False

    def control_download(self, identifier, action):
        if type(identifier) is not int or action not in ('pause', 'resume', 'cancel'):
            return 'Invalid transfer control.'
        with self._lock:
            job = self._jobs.get(identifier)
            if not job or job['view']['state'] != 'running':
                return 'This download is no longer running.'
            selection = job['selection']
            if action == 'pause' and self._turbo_id == identifier:
                return 'Turn off Turbo before pausing this download.'
            if action == 'pause' and not selection.pause():
                return 'Pausing requires a server with byte ranges and a stable file identifier.'
            if action == 'resume':
                selection.resume()
            if action == 'cancel':
                if selection.snapshot()[0] == 'scanning':
                    return 'Windows is scanning this file. Wait for the scan to finish.'
                selection.cancel()
        LOGGER.info('transfer-control transfer=%s action=%s', identifier, action)
        return None

    def apply_connections(self, identifier, ids):
        if (type(identifier) is not int or not isinstance(ids, list)
                or not 1 <= len(ids) <= MAX_CONNECTIONS or any(type(i) is not int for i in ids)
                or len(set(ids)) != len(ids)):
            return 'Select one to seven distinct connections.'
        with self._lock:
            job = self._jobs.get(identifier)
            if not job or job['view']['state'] != 'running':
                return 'This download is no longer running.'
            available = {row['index']: row['name'] for row in self._rows if row['status'] == 'Up' and row['gateway']}
            if any(index not in available for index in ids):
                return 'A selected connection is unavailable. Refresh and try again.'
            if self._turbo_id == identifier:
                return 'Turbo manages all available connections. Turn it off to choose adapters.'
            if not job['selection'].update({available[index]: index for index in ids}):
                return 'This download is not accepting connection changes.'
        LOGGER.info('transfer-connections-updated transfer=%s adapters=%s', identifier, len(ids))
        return None

    def change_priority(self, identifier, priority):
        if type(identifier) is not int or not isinstance(priority, str) or priority not in PRIORITIES:
            return False
        with self._condition:
            job = self._jobs.get(identifier)
            if job is None or job['view']['state'] != 'queued':
                return False
            job['view']['priority'] = priority
        LOGGER.info('transfer-priority transfer=%s priority=%s', identifier, priority)
        return True

    def cancel_waiting(self, identifier):
        if type(identifier) is not int:
            return False
        with self._condition:
            job = self._jobs.get(identifier)
            if job is None or job['view']['state'] not in ('queued', 'recoverable', 'failed'):
                return False
            if job['view']['state'] != 'queued' and job.get('recovery_id'):
                try:
                    with recovery_store.claim(job['recovery_id']):
                        record = recovery_store.load(job['recovery_id'])
                        if record:
                            record.partial.unlink(missing_ok=True)
                            record.remove()
                except (OSError, ValueError, TypeError, KeyError):
                    return False
            del self._jobs[identifier]
            if job.get('browser_id') and self._browser_inbox:
                self._browser_inbox.mark(job['browser_id'], 'cancelled')
            if self._turbo_id == identifier:
                self._turbo_id = None
                self._rebalance()
                self._condition.notify_all()
        LOGGER.info('transfer-removed transfer=%s', identifier)
        return True

    def _next_job(self):
        if self._shutdown_requested:
            return None
        if self._turbo_id is not None:
            job = self._jobs.get(self._turbo_id)
            return job if job and job['view']['state'] == 'queued' else None
        if sum(job['view']['state'] == 'running' for job in self._jobs.values()) >= 2:
            return None
        waiting = [job for job in self._jobs.values() if job['view']['state'] == 'queued']
        if waiting:
            return min(waiting, key=lambda job: (PRIORITIES[job['view']['priority']], job['view']['id']))
        return None

    def _worker(self):
        while True:
            with self._condition:
                while (job := self._next_job()) is None:
                    if self._shutdown_requested:
                        return
                    self._condition.wait()
                job['view']['state'] = 'running'
                self._rebalance()
            self._run(job)
            with self._condition:
                if self._turbo_id == job['view']['id']:
                    self._turbo_id = None
                self._rebalance()
                self._condition.notify_all()
                for field in ('url', 'target', 'key', 'links', 'selection'):
                    del job[field]
                job['activity'].clear()
                finished = [identifier for identifier, entry in self._jobs.items()
                            if entry['view']['state'] in ('saved', 'failed', 'cancelled')]
                for identifier in finished[:-30]:
                    del self._jobs[identifier]

    def _run(self, job):
        view = job['view']
        links = job['links']
        sample_time = time.monotonic()
        sample_bytes = 0

        def report(totals, size):
            nonlocal sample_time, sample_bytes
            now = time.monotonic()
            received = sum(totals.values())
            with self._lock:
                for name, count in totals.items():
                    if count > view['totals'].get(name, 0):
                        job['activity'][name] = now
                if now - sample_time >= .5 and received >= sample_bytes:
                    view['rate'] = (received - sample_bytes) / (now - sample_time)
                    sample_time, sample_bytes = now, received
                view.update(totals=dict.fromkeys(links, 0) | totals, size=size)

        filename = view['filename']
        identifier = view['id']
        LOGGER.info('transfer-started transfer=%s adapters=%s', identifier, len(links))
        try:
            options = {'public_only': True, 'overwrite': False} if job.get('restricted') else {}
            elapsed, totals = download(job['url'], job['target'], links, report, live_links=job['selection'], recovery_id=job.get('recovery_id'), **options)
            detail = '  |  '.join(f'{name}: {count / 1048576:.2f} MiB' for name, count in totals.items())
            self._record('Download', filename, 'Saved', f'{elapsed:.1f}s  |  {detail}')
            with self._lock:
                view.update(state='saved', elapsed=elapsed, totals=totals)
            LOGGER.info('transfer-saved transfer=%s bytes=%s seconds=%.2f', identifier, sum(totals.values()), elapsed)
        except DownloadStopped:
            with self._lock:
                view.update(state='recoverable', rate=0)
            LOGGER.info('transfer-progress-kept transfer=%s', identifier)
        except DownloadCancelled:
            self._record('Download', filename, 'Cancelled', 'Cancelled by the user.')
            with self._lock:
                view.update(state='cancelled', rate=0)
            LOGGER.info('transfer-cancelled transfer=%s', identifier)
        except Exception as error:
            failure('transfer-failed', error, identifier)
            self._record('Download', filename, 'Failed', 'See the Download view for the error.')
            with self._lock:
                view.update(state='failed', error=str(error)[:512])
        finally:
            if job.get('browser_id') and self._browser_inbox and view['state'] in ('saved', 'failed', 'cancelled'):
                try:
                    self._browser_inbox.mark(job['browser_id'], view['state'])
                except (OSError, sqlite3.Error) as error:
                    failure('browser-inbox-update-failed', error, identifier)


def main():
    api = Desktop()
    html = (resource_root() / 'ui' / 'dist' / 'index.html').read_text(encoding='utf-8')
    window = webview.create_window('FetchVolt', html=html, js_api=api,
                                   width=1160, height=800, min_size=(360, 450), background_color='#000000', minimized='--startup' in sys.argv)
    api._window = window
    window.events.closing += api._on_closing
    for target, name in ((api._monitor, 'adapter-monitor'), (api._traffic_monitor, 'traffic-monitor'), (api._browser_monitor, 'browser-inbox')):
        monitor = threading.Thread(target=target, name=name, daemon=True)
        api._threads.append(monitor)
        monitor.start()
    for index in range(3):
        thread = threading.Thread(target=api._worker, name=f'download-{index + 1}', daemon=True)
        api._threads.append(thread)
        thread.start()
    webview.start(gui='edgechromium')


if __name__ == '__main__':
    try:
        configure()
    except OSError:
        # A read-only or unavailable profile should not prevent the app opening.
        pass
    LOGGER.info('session-started version=%s', VERSION)
    try:
        with browser_bridge.app_instance() as acquired:
            if acquired:
                main()
    except Exception as error:
        failure('startup-failed', error)
        raise
    finally:
        LOGGER.info('session-stopped')
        for handler in LOGGER.handlers[:]:
            LOGGER.removeHandler(handler)
            handler.close()
