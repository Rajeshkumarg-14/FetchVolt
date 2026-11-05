from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import mcp_portflock as mcp
import net_booster as engine


class McpTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.service = mcp.DownloadService(self.root)
        self.enterContext(patch.object(mcp, 'available_connections', return_value=[
            {'id': 1, 'name': 'Wi-Fi', 'link_rate': '1 Gbps'},
        ]))

    def test_rejects_escape_and_windows_special_paths(self):
        for target in ('../escape.iso', 'C:\\escape.iso', '\\server\\x', 'a:stream', 'NUL.txt', 'folder//x', 'bad.'):
            with self.subTest(target=target), self.assertRaises(ValueError):
                mcp.destination_under(self.root, target)

    def test_existing_file_is_preserved(self):
        path = self.root / 'image.iso'
        path.write_bytes(b'old')
        with self.assertRaises(FileExistsError):
            self.service.start('https://example.test/file', 'image.iso', [1])
        self.assertEqual(path.read_bytes(), b'old')

    def test_public_address_policy_blocks_private_and_special_hosts(self):
        for address in ('127.0.0.1', '10.1.2.3', '169.254.169.254', '192.168.1.1', '224.0.0.1', '100.64.0.1'):
            with self.subTest(address=address):
                self.assertFalse(engine.is_public_address(address))
        self.assertTrue(engine.is_public_address('8.8.8.8'))

    def test_checksum_and_atomic_no_overwrite(self):
        partial = self.root / 'download.part'
        target = self.root / 'image.iso'
        partial.write_bytes(b'new')
        target.write_bytes(b'old')
        with patch.object(engine, 'scan_file') as scan:
            with self.assertRaisesRegex(ValueError, 'SHA-256'):
                engine.publish(partial, target, overwrite=False, expected_sha256='0' * 64)
            scan.assert_not_called()
            with self.assertRaises(FileExistsError):
                engine.publish(partial, target, overwrite=False)
        self.assertEqual(target.read_bytes(), b'old')
        self.assertEqual(partial.read_bytes(), b'new')

    def test_start_uses_restricted_downloader_and_reports_saved_path(self):
        entered = threading.Event()
        release = threading.Event()

        def download(url, target, links, report, **options):
            self.assertEqual(options, dict(public_only=True, overwrite=False, expected_sha256='a' * 64))
            report({'Wi-Fi': 12}, 12)
            entered.set()
            if not release.wait(3):
                raise TimeoutError()
            return .2, {'Wi-Fi': 12}

        with patch.object(mcp, 'download', side_effect=download):
            job = self.service.start('https://example.test/file', 'image.iso', [1], 'A' * 64)
            try:
                self.assertTrue(entered.wait(3))
                self.assertEqual(self.service.status(job['id'])['bytes'], {'Wi-Fi': 12})
                with self.assertRaisesRegex(ValueError, 'already using'):
                    self.service.start('https://example.test/file', 'IMAGE.iso', [1])
            finally:
                release.set()
            for thread in threading.enumerate():
                if thread.name == 'mcp-download-' + job['id'][:8]:
                    thread.join(3)
            self.assertEqual(self.service.status(job['id'])['path'], str(self.root / 'image.iso'))
