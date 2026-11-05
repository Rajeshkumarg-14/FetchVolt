import io
from pathlib import Path
import socket
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import net_booster as app
from tests.python.test_net_booster import Response
from windows_security import ScanError, scan_file


class SecurityTests(unittest.TestCase):
    def test_defender_result_is_fail_closed(self):
        path = Path('C:/test/payload.part')
        with patch('windows_security.subprocess.run') as run:
            run.return_value.returncode = 0
            scan_file(path)
            self.assertIn('-DisableRemediation', run.call_args.args[0])
            self.assertEqual(run.call_args.kwargs['timeout'], 300)
            self.assertEqual(run.call_args.kwargs['stdout'], subprocess.DEVNULL)
            for code in [1, 2, 3, 0x80070005, -1]:
                with self.subTest(code=code):
                    run.return_value.returncode = code
                    with self.assertRaises(ScanError):
                        scan_file(path)
            for error in [FileNotFoundError(), PermissionError(), subprocess.TimeoutExpired('Defender', 300)]:
                with self.subTest(error=type(error).__name__):
                    run.side_effect = error
                    with self.assertRaises(ScanError):
                        scan_file(path)

    def test_absolute_deadline_interrupts_stalled_socket(self):
        receiver, sender = socket.socketpair()
        with receiver, sender:
            receiver.settimeout(.2)
            connection = SimpleNamespace(sock=receiver, close=receiver.close)
            lease = app.ResponseLease(connection, 'https://example.test')
            try:
                lease.arm(.03)
                try:
                    self.assertEqual(receiver.recv(1), b'')
                except TimeoutError:
                    # Winsock may keep a pending select blocked until its idle timeout.
                    pass
                with self.assertRaises(TimeoutError):
                    lease.check()
            finally:
                lease.close()

    def test_download_uses_bounded_stream_reads(self):
        body = bytes(app.READ_BUFFER * 5)
        reply = Response(200, body, **{'Content-Length': str(len(body))})
        reply.read1 = Mock(wraps=reply.read1)
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(app, 'request', return_value=(io.BytesIO(), reply)),
            patch.object(app, 'scan_file'),
        ):
            path = Path(folder) / 'file.bin'
            app.download('https://example.test/file', path, {'Wi-Fi': 1}, lambda *_: None)
            self.assertEqual(path.read_bytes(), body)
            self.assertGreater(reply.read1.call_count, 4)
            self.assertTrue(all(call.args == (app.READ_BUFFER,) for call in reply.read1.call_args_list))

    def test_range_workers_use_bounded_reads_and_preserve_file_content(self):
        body = b'abcde' * (app.READ_BUFFER // 2)
        requests = []

        def request(url, adapter, headers):
            low, high = map(int, headers['Range'][6:].split('-'))
            reply = Response(206, body[low:high + 1], **{
                'Content-Range': f'bytes {low}-{high}/{len(body)}', 'ETag': '"stable"',
            })
            reply.read1 = Mock(wraps=reply.read1)
            requests.append(reply)
            return io.BytesIO(), reply

        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(app, 'request', side_effect=request),
            patch.object(app, 'CHUNK', app.READ_BUFFER * 2),
            patch.object(app, 'scan_file'),
        ):
            path = Path(folder) / 'file.bin'
            app.download('https://example.test/file', path, {'Wi-Fi': 1, 'Ethernet': 2}, lambda *_: None)
            self.assertEqual(path.read_bytes(), body)
        self.assertGreater(sum(reply.read1.call_count for reply in requests), 2)
        self.assertTrue(all(0 < call.args[0] <= app.READ_BUFFER
                            for reply in requests for call in reply.read1.call_args_list))

    def test_scan_removal_or_modification_cannot_replace_destination(self):
        for alter in [lambda path: path.unlink(), lambda path: path.write_bytes(b'changed')]:
            with self.subTest(alter=alter), tempfile.TemporaryDirectory() as folder:
                directory = Path(folder)
                partial, destination = directory / 'download.part', directory / 'file.bin'
                partial.write_bytes(b'new')
                destination.write_bytes(b'old')
                with patch.object(app, 'scan_file', side_effect=alter), self.assertRaises(ScanError):
                    app.publish(partial, destination)
                self.assertEqual(destination.read_bytes(), b'old')

    def test_oversized_or_low_disk_download_is_blocked_before_scan(self):
        for size, free, error in [(app.MAX_FILE_SIZE + 1, app.MAX_FILE_SIZE + 100, ValueError), (10, 4, OSError)]:
            with (
                self.subTest(size=size, free=free),
                tempfile.TemporaryDirectory() as folder,
                patch.object(app.shutil, 'disk_usage', return_value=SimpleNamespace(free=free)),
                patch.object(app, 'request', return_value=(
                    io.BytesIO(), Response(200, b'', **{'Content-Length': str(size)})
                )),
                patch.object(app, 'scan_file') as scan,
                self.assertRaises(error),
            ):
                app.download('https://example.test/file', Path(folder) / 'file.bin', {'Wi-Fi': 1}, lambda *_: None)
            scan.assert_not_called()
