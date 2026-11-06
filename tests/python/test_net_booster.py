import io
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import net_booster as app
from network_monitor import History, changes, mbps


class Response(io.BytesIO):
    def __init__(self, status, body, **headers):
        super().__init__(body)
        self.status = status
        self.headers = headers

    def getheader(self, name, default=None):
        return self.headers.get(name, default)


class DownloadTests(unittest.TestCase):
    payload = bytes(range(256)) * 16
    links = {'Wi-Fi': 13, 'Bluetooth': 21}

    def setUp(self):
        folder = self.enterContext(tempfile.TemporaryDirectory())
        self.target = Path(folder) / 'test.bin'
        self.enterContext(patch.object(app, 'CHUNK', 512))
        self.enterContext(patch.object(app, 'scan_file'))
        self.reports = []

    def fetch(self, request, links=None):
        with patch.object(app, 'request', side_effect=request):
            return app.download(
                'https://example.com/test.bin', self.target, links or self.links,
                lambda *progress: self.reports.append(progress),
            )

    def full(self):
        return io.BytesIO(), Response(200, self.payload, **{'Content-Length': str(len(self.payload))})

    def ranged(self, headers):
        if 'Range' not in headers:
            return self.full()
        first, last = map(int, headers['Range'][6:].split('-'))
        return io.BytesIO(), Response(206, self.payload[first:last + 1], **{
            'Content-Range': f'bytes {first}-{last}/{len(self.payload)}', 'ETag': '"stable"',
        })

    def test_rejects_plain_http_and_embedded_credentials(self):
        for url in ('http://example.com/file', 'https://user@example.com/file'):
            with self.subTest(url=url), self.assertRaisesRegex(ValueError, 'HTTPS URL'):
                app.request(url, 13, {})

    def test_single_adapter(self):
        _, totals = self.fetch(lambda *_: self.full(), {'Wi-Fi': 13})
        self.assertEqual(totals, {'Wi-Fi': len(self.payload)})
        self.assertIn(b'ZoneId=3', Path(f'{self.target}:Zone.Identifier').read_bytes())
        self.assertEqual(self.target.read_bytes(), self.payload)

    def test_both_adapters_fetch_and_reassemble(self):
        both = threading.Barrier(2)
        seen = set()
        lock = threading.Lock()

        def request(url, adapter, headers):
            if 'If-Range' in headers:
                self.assertEqual(headers['If-Range'], '"stable"')
                with lock:
                    first_chunk = adapter not in seen
                    seen.add(adapter)
                if first_chunk:
                    both.wait(timeout=3)
            return self.ranged(headers)

        _, totals = self.fetch(request)
        self.assertTrue(all(totals.values()))
        self.assertEqual(sum(totals.values()), len(self.payload))
        self.assertEqual(self.reports[-1], (totals, len(self.payload)))
        self.assertEqual(self.target.read_bytes(), self.payload)

    @patch.object(app, 'STREAMS_PER_LINK', 1)
    def test_four_adapters_contribute_to_one_file(self):
        links = {'Wi-Fi': 13, 'LAN': 17, 'Bluetooth': 21, 'USB': 25}
        first = set()
        lock = threading.Lock()
        ready = threading.Barrier(4)

        def request(url, adapter, headers):
            if 'If-Range' in headers:
                with lock:
                    new = adapter not in first
                    first.add(adapter)
                if new:
                    ready.wait(3)
            return self.ranged(headers)

        _, totals = self.fetch(request, links)
        self.assertTrue(all(totals.values()))
        self.assertEqual(set(totals), set(links))
        self.assertEqual(self.target.read_bytes(), self.payload)

    @patch.object(app, 'STREAMS_PER_LINK', 1)
    def test_multiple_failed_adapters_leave_intact_file(self):
        links = {'Wi-Fi': 13, 'LAN': 17, 'Bluetooth': 21, 'USB': 25}
        ready = threading.Barrier(4)
        attempts = set()
        lock = threading.Lock()

        def request(url, adapter, headers):
            if 'If-Range' in headers:
                with lock:
                    new = adapter not in attempts
                    attempts.add(adapter)
                if new:
                    ready.wait(3)
                if adapter != 25:
                    raise ConnectionError('Adapter disconnected')
            return self.ranged(headers)

        _, totals = self.fetch(request, links)
        self.assertEqual(totals, dict.fromkeys(links, 0) | {'USB': len(self.payload)})
        self.assertEqual(self.target.read_bytes(), self.payload)

    def test_one_adapter_streams_ranges_in_parallel_and_file_is_intact(self):
        active = peak = 0
        lock = threading.Lock()

        def request(url, adapter, headers):
            nonlocal active, peak
            if 'If-Range' in headers:
                with lock:
                    active += 1
                    peak = max(peak, active)
                threading.Event().wait(.03)
                with lock:
                    active -= 1
            return self.ranged(headers)

        _, totals = self.fetch(request, {'USB': 25})
        self.assertEqual(peak, app.STREAMS_PER_LINK)
        self.assertEqual(totals, {'USB': len(self.payload)})
        self.assertEqual(self.target.read_bytes(), self.payload)

    def test_every_stream_stays_bound_to_its_own_adapter(self):
        links = {'Wi-Fi': 13, 'USB': 25}
        seen = set()

        def request(url, adapter, headers):
            seen.add(adapter)
            return self.ranged(headers)

        self.fetch(request, links)
        self.assertLessEqual(seen, set(links.values()))
        self.assertEqual(self.target.read_bytes(), self.payload)

    def test_failed_stream_retries_on_surviving_adapter_with_intact_file(self):
        links = {'Wi-Fi': 13, 'USB': 25}

        def request(url, adapter, headers):
            if 'If-Range' in headers and adapter == 13:
                raise ConnectionError('Adapter disconnected')
            return self.ranged(headers)

        _, totals = self.fetch(request, links)
        self.assertEqual(totals.get('Wi-Fi', 0), 0)
        self.assertEqual(totals['USB'], len(self.payload))
        self.assertEqual(self.target.read_bytes(), self.payload)

    def test_lone_adapter_falls_back_to_one_stream_when_server_ignores_range(self):
        _, totals = self.fetch(lambda url, adapter, headers: self.full(), {'USB': 25})
        self.assertEqual(totals, {'USB': len(self.payload)})
        self.assertEqual(self.target.read_bytes(), self.payload)

    def test_single_stream_setting_still_works(self):
        with patch.object(app, 'STREAMS_PER_LINK', 1):
            _, totals = self.fetch(lambda url, adapter, headers: self.ranged(headers))
        self.assertEqual(sum(totals.values()), len(self.payload))
        self.assertEqual(self.target.read_bytes(), self.payload)

    def test_all_adapter_failures_preserve_existing_destination(self):
        self.target.write_bytes(b'original')
        links = {'Wi-Fi': 13, 'LAN': 17, 'Bluetooth': 21, 'USB': 25}

        def request(url, adapter, headers):
            if 'If-Range' in headers:
                raise ConnectionError('Adapter disconnected')
            return self.ranged(headers)

        with self.assertRaisesRegex(OSError, 'No selected adapter'):
            self.fetch(request, links)
        self.assertEqual(self.target.read_bytes(), b'original')
        self.assertEqual(list(self.target.parent.iterdir()), [self.target])

    def test_server_ignores_ranges(self):
        _, totals = self.fetch(lambda *_: self.full())
        self.assertEqual(totals['Bluetooth'], 0)
        self.assertEqual(self.target.read_bytes(), self.payload)

    def test_weak_validator_falls_back_to_full_get(self):
        requests = []

        def request(url, adapter, headers):
            requests.append((adapter, headers))
            connection, response = self.ranged(headers)
            response.headers['ETag'] = 'W/"weak"'
            return connection, response

        self.fetch(request)
        self.assertEqual(requests, [(13, {'Range': 'bytes=0-0'}), (13, {})])
        self.assertEqual(self.target.read_bytes(), self.payload)

    def test_empty_file_range_falls_back_to_full_get(self):
        def request(url, adapter, headers):
            if headers:
                return io.BytesIO(), Response(416, b'', **{'Content-Range': 'bytes */0'})
            return io.BytesIO(), Response(200, b'', **{'Content-Length': '0'})

        self.fetch(request)
        self.assertEqual(self.target.read_bytes(), b'')

    def test_failed_primary_probe_switches_to_secondary(self):
        def request(url, adapter, headers):
            if adapter == 13:
                raise TimeoutError('Wi-Fi unavailable')
            return self.full()

        _, totals = self.fetch(request)
        self.assertEqual(totals, {'Wi-Fi': 0, 'Bluetooth': len(self.payload)})
        self.assertEqual(self.target.read_bytes(), self.payload)

    def test_failed_secondary_chunk_is_retried_on_primary(self):
        tried_secondary = threading.Event()

        def request(url, adapter, headers):
            if 'If-Range' in headers:
                if adapter == 21:
                    tried_secondary.set()
                    raise ConnectionError('Bluetooth disconnected')
                self.assertTrue(tried_secondary.wait(3))
            return self.ranged(headers)

        _, totals = self.fetch(request)
        self.assertEqual(totals, {'Wi-Fi': len(self.payload), 'Bluetooth': 0})
        self.assertEqual(self.target.read_bytes(), self.payload)

    def test_changed_file_preserves_existing_destination(self):
        self.target.write_bytes(b'original')

        def request(url, adapter, headers):
            return self.full() if 'If-Range' in headers else self.ranged(headers)

        with self.assertRaisesRegex(ValueError, 'file changed'):
            self.fetch(request)
        self.assertEqual(self.target.read_bytes(), b'original')
        self.assertEqual(list(self.target.parent.iterdir()), [self.target])

    def test_incomplete_download_is_not_published(self):
        response = Response(200, b'truncated', **{'Content-Length': '100'})
        with self.assertRaisesRegex(OSError, 'full file'):
            self.fetch(lambda *_: (io.BytesIO(), response))
        self.assertEqual(list(self.target.parent.iterdir()), [])


class MonitorTests(unittest.TestCase):
    def test_counter_rates_handle_first_sample_idle_and_reset(self):
        self.assertEqual(mbps(0, 250000, 2), 1)
        self.assertEqual(mbps(250000, 250000, 2), 0)
        for previous, current, seconds in [(None, 20, 1), (20, None, 1), (20, 0, 1), (0, 20, 0)]:
            with self.subTest(previous=previous, current=current, seconds=seconds):
                self.assertIsNone(mbps(previous, current, seconds))

    def test_history_detects_only_observed_changes(self):
        previous = {'Wi-Fi': ('Up', '10.0.0.1'), 'Bluetooth': ('Up', '10.0.1.1')}
        current = {'Wi-Fi': ('Up', '10.0.0.1'), 'Ethernet': ('Disconnected', '')}
        self.assertEqual(list(changes(previous, current)), [
            ('Ethernet', 'Disconnected', 'No IPv4 address'),
            ('Bluetooth', 'Unavailable', 'Adapter disappeared'),
        ])
        self.assertEqual(list(changes(current, current)), [])
        self.assertEqual(list(changes({'Wi-Fi': ('Up', '10.0.0.1')}, {'Wi-Fi': ('Up', '10.0.0.2')})),
                         [('Wi-Fi', 'Up', '10.0.0.2')])

    def test_history_persists_across_reopen(self):
        with tempfile.TemporaryDirectory() as folder:
            database = Path(folder) / 'local' / 'history.sqlite3'
            history = History(database)
            history.add('Connection', 'Wi-Fi', 'Up', '10.0.0.1')
            history.add('Download', 'sample.zip', 'Saved', '2.0s')
            records = History(database).recent()
            self.assertEqual(records[0][1:], ('Download', 'sample.zip', 'Saved', '2.0s'))
            self.assertEqual(records[1][1:], ('Connection', 'Wi-Fi', 'Up', '10.0.0.1'))


if __name__ == '__main__':
    unittest.main()
