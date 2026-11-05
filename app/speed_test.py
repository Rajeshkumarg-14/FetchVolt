"""Opt-in, single-adapter, bounded HTTPS receive-throughput sampling.

Not an Ookla/Cloudflare benchmark implementation. No payload is written to disk.
"""
import socket
import threading
import time
from datetime import datetime
from statistics import median

from diagnostics import failure
from net_booster import request, READ_BUFFER

SAMPLE_BYTES = 10_000_000
ENDPOINT = 'https://speed.cloudflare.com/__down?bytes='


class SpeedTest:
    def __init__(self):
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._lease = None
        self._thread = None
        self._view = {'state': 'idle', 'bytes': 0, 'limit': SAMPLE_BYTES, 'rate': None}
        self._history = []

    def snapshot(self):
        with self._lock:
            return {**self._view, 'history': [dict(row) for row in self._history]}

    def start(self, adapter, name):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return 'A speed test is already running.'
            self._stop = threading.Event()
            self._view = {'state': 'running', 'phase': 'Measuring HTTPS response time',
                          'adapter': adapter, 'name': name, 'bytes': 0, 'limit': SAMPLE_BYTES, 'rate': None}
            self._thread = threading.Thread(target=self._run, args=(adapter,), name='speed-test', daemon=True)
            self._thread.start()
        return None

    def cancel(self):
        self._stop.set()
        with self._lock:
            lease = self._lease
        if lease:
            try:
                lease.socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        return None

    def _set(self, **values):
        with self._lock:
            self._view.update(values)

    def _open(self, adapter, size):
        if self._stop.is_set():
            raise InterruptedError()
        lease, response = request(ENDPOINT + str(size), adapter, {'Cache-Control': 'no-store'},
                                  public_only=True, timeout=5, header_timeout=5,
                                  response_timeout=12, redirect_limit=1)
        with self._lock:
            self._lease = lease
        try:
            if self._stop.is_set():
                raise InterruptedError()
            if response.status != 200 or response.getheader('Content-Encoding', 'identity') != 'identity':
                raise ValueError('Unexpected test response')
            length = response.getheader('Content-Length')
            if length is not None and int(length) != size:
                raise ValueError('Unexpected test size')
            return lease, response
        except BaseException:
            response.close()
            lease.close()
            with self._lock:
                self._lease = None
            raise

    def _release(self, lease, response):
        try:
            response.close()
        finally:
            lease.close()
            with self._lock:
                self._lease = None

    def _run(self, adapter):
        try:
            timings = []
            for _ in range(3):
                started = time.monotonic()
                lease, response = self._open(adapter, 0)
                try:
                    timings.append((time.monotonic() - started) * 1000)
                finally:
                    self._release(lease, response)
            self._set(latency=median(timings), jitter=sum(abs(b-a) for a,b in zip(timings,timings[1:])) / 2,
                      phase='Measuring receive throughput')
            lease, response = self._open(adapter, SAMPLE_BYTES)
            received = 0
            started = time.monotonic()
            try:
                while received < SAMPLE_BYTES:
                    if self._stop.is_set():
                        raise InterruptedError()
                    block = response.read(min(READ_BUFFER, SAMPLE_BYTES-received))
                    lease.check()
                    if not block:
                        raise OSError('Incomplete test payload')
                    received += len(block)
                    elapsed = time.monotonic() - started
                    self._set(bytes=received, rate=received/max(elapsed, .001))
                elapsed = time.monotonic() - started
            finally:
                self._release(lease, response)
            if self._stop.is_set():
                raise InterruptedError()
            self._set(state='complete', phase='Sample complete', seconds=elapsed,
                      shortSample=elapsed < 1, finished=datetime.now().astimezone().isoformat(timespec='seconds'))
            with self._lock:
                self._history.insert(0, dict(self._view))
                del self._history[5:]
        except Exception as error:
            if self._stop.is_set():
                self._set(state='cancelled', phase='Test cancelled', rate=None)
            else:
                failure('speed-test-failed', error)
                self._set(state='failed', phase='Test unavailable. Check the connection and try again.', rate=None)
