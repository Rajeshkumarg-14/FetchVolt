"""Exercise the transfer engine across every nonempty subset of seven adapters."""
import io
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import net_booster as app
from tests.python.test_net_booster import Response
from windows_security import ScanError

ADAPTERS = ('Wi-Fi', 'Ethernet', 'Bluetooth', 'USB 1', 'USB 2', 'USB 3', 'USB 4')
BODY = bytes(range(128))
OUTCOMES = {
    'clean': None,
    'range_ignored': None,
    'weak_validator': None,
    'primary_timeout': TimeoutError,
    'all_ranges_stall': OSError,
    'short_response': OSError,
    'bad_framing': ValueError,
    'wrong_encoding': ValueError,
    'scanner_blocks': ScanError,
    'scanner_timeout': ScanError,
}


class TransferMatrix(unittest.TestCase):
    def exercise(self, mask, scenario, failure):
        links = {name: i + 1 for i, name in enumerate(ADAPTERS) if mask & (1 << i)}
        primary = next(iter(links.values()))
        if scenario == 'primary_timeout' and len(links) > 1:
            failure = None
        touched = set()
        def request(url, adapter, headers):
            touched.add(adapter)
            range_header = headers.get('Range')
            if scenario == 'primary_timeout' and adapter == primary:
                raise TimeoutError('Simulated adapter timeout.')
            if scenario == 'all_ranges_stall' and ('If-Range' in headers or not range_header):
                raise TimeoutError('Simulated server stall.')

            if not range_header or scenario == 'range_ignored':
                response = Response(200, BODY, **{'Content-Length': str(len(BODY))})
            else:
                low, high = map(int, range_header.removeprefix('bytes=').split('-'))
                response = Response(206, BODY[low:high + 1], **{
                    'Content-Range': f'bytes {low}-{high}/{len(BODY)}',
                    'Content-Length': str(high - low + 1),
                    'ETag': 'W/"old"' if scenario == 'weak_validator' else '"stable"',
                })
            if 'If-Range' in headers or response.status == 200:
                if scenario == 'short_response':
                    response.truncate(len(response.getvalue()) - 1)
                if scenario == 'bad_framing':
                    response.headers['Transfer-Encoding'] = 'chunked'
                if scenario == 'wrong_encoding':
                    response.headers['Content-Encoding'] = 'gzip'
            return io.BytesIO(), response

        scan_error = {
            'scanner_blocks': ScanError('Simulated detection.'),
            'scanner_timeout': ScanError('Simulated scanner timeout.'),
        }.get(scenario)
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'file.bin'
            target.write_bytes(b'previous file')
            with (
                patch.object(app, 'request', side_effect=request),
                patch.object(app, 'CHUNK', 16),
                patch.object(app, 'scan_file', side_effect=scan_error) as scan,
            ):
                if failure:
                    with self.assertRaises(failure):
                        app.download('https://example.test/file.bin', target, links, lambda *_: None)
                    self.assertEqual(target.read_bytes(), b'previous file')
                    self.assertEqual(scan.call_count, int(scan_error is not None))
                else:
                    _, totals = app.download('https://example.test/file.bin', target, links, lambda *_: None)
                    self.assertEqual(target.read_bytes(), BODY)
                    self.assertEqual(sum(totals.values()), len(BODY))
                    self.assertEqual(set(totals), set(links))
                    scan.assert_called_once()
                self.assertLessEqual(touched, set(links.values()))
            self.assertEqual(list(target.parent.iterdir()), [target])

    @patch.object(app, 'STREAMS_PER_LINK', 1)
    def test_seven_adapters_each_receive_bytes(self):
        links = {name: i + 1 for i, name in enumerate(ADAPTERS)}
        first = set()
        lock = threading.Lock()
        ready = threading.Barrier(len(links))

        def request(url, adapter, headers):
            low, high = map(int, headers['Range'].removeprefix('bytes=').split('-'))
            if 'If-Range' in headers:
                with lock:
                    new = adapter not in first
                    first.add(adapter)
                if new:
                    ready.wait(timeout=4)
            return io.BytesIO(), Response(206, BODY[low:high + 1], **{
                'Content-Range': f'bytes {low}-{high}/{len(BODY)}', 'ETag': '"stable"',
            })

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(app, 'request', side_effect=request),
            patch.object(app, 'CHUNK', 16),
            patch.object(app, 'scan_file'),
        ):
            path = Path(directory) / 'file.bin'
            _, totals = app.download('https://example.test/file', path, links, lambda *_: None)
            self.assertTrue(all(totals.values()), totals)
            self.assertEqual(path.read_bytes(), BODY)


def make_test(mask, scenario, failure):
    def test(self):
        self.exercise(mask, scenario, failure)
    return test


for mask in range(1, 1 << len(ADAPTERS)):
    for scenario, failure in OUTCOMES.items():
        setattr(TransferMatrix, f'test_{mask:03d}_{scenario}', make_test(mask, scenario, failure))
