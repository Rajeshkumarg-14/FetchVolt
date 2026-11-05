import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import Mock, patch

import browser_bridge as bridge
import browser_setup


class ProtocolTests(unittest.TestCase):
    def test_setup_emits_exact_origins_without_changing_browser_profiles(self):
        with tempfile.TemporaryDirectory() as directory, patch('browser_setup.data_directory', return_value=Path(directory)), \
                patch('browser_setup.detected_browsers', return_value=['Microsoft Edge']), \
                patch('browser_setup.winreg.CreateKeyEx') as create, patch('browser_setup.winreg.SetValueEx') as put, \
                patch('browser_setup.sys.frozen', True, create=True), \
                patch('browser_setup.resource_root', return_value=Path(__file__).resolve().parents[2]), \
                patch('browser_bridge.resource_root', return_value=Path(__file__).resolve().parents[2]):
            result = browser_setup.setup(open_guide=False)
            host = json.loads((Path(directory) / 'chromium-host.json').read_text('utf-8'))
            self.assertEqual(host['allowed_origins'], ['chrome-extension://' + bridge.extension_id() + '/'])
            self.assertNotIn('*', str(host))
            firefox = json.loads((Path(directory) / 'firefox' / 'manifest.json').read_text('utf-8'))
            self.assertEqual(firefox['browser_specific_settings']['gecko']['id'], bridge.FIREFOX_ID)
            manifest = json.loads((Path(directory) / 'chromium' / 'manifest.json').read_text('utf-8'))
            self.assertEqual(set(manifest['permissions']), {'downloads', 'nativeMessaging', 'storage'})
            self.assertNotIn('host_permissions', manifest)
            self.assertNotIn('content_scripts', manifest)
            self.assertEqual(create.call_count, 4)
            self.assertTrue(Path(result['guide']).is_file())

    def test_round_trip_and_bounds(self):
        stream = io.BytesIO()
        bridge.write_message(stream, {'op': 'ping'})
        stream.seek(0)
        self.assertEqual(bridge.read_message(stream), {'op': 'ping'})
        for data in (b'', b'\x01', struct.pack('<I', 0), struct.pack('<I', bridge.MAX_MESSAGE + 1),
                     struct.pack('<I', 50) + b'{}', struct.pack('<I', 1) + b'\xff'):
            with self.subTest(data=data[:4]), self.assertRaises(ValueError):
                bridge.read_message(io.BytesIO(data))

    def test_only_exact_extension_origin(self):
        origin = 'chrome-extension://' + bridge.extension_id() + '/'
        self.assertTrue(bridge.allowed_caller([origin]))
        for args in ([], ['https://example.com'], [origin + 'evil'], ['chrome-extension://' + 'a' * 32 + '/']):
            self.assertFalse(bridge.allowed_caller(args))

    def test_no_host_io_for_disallowed_caller(self):
        with patch.object(bridge, 'native_stream') as stream:
            self.assertEqual(bridge.host(['https://example.com']), 1)
            stream.assert_not_called()

    def test_rejects_nonpublic_urls_and_credentials(self):
        for url in ('http://example.com/a', 'https://127.0.0.1/a', 'https://10.0.0.1/a',
                    'https://[::1]/a', 'https://localhost/a', 'https://printer.local/a',
                    'https://u:p@example.com/a', 'https://example.com:8443/a',
                    'https://example.com/a#x', 'https://example.com/\na', None, 'x' * 17000):
            with self.subTest(url=str(url)[:50]), self.assertRaises(ValueError):
                bridge.validate_public_url(url)
        self.assertEqual(bridge.validate_public_url('https://example.com/a?token=x'), 'https://example.com/a?token=x')

    def test_filename_cannot_select_directory_or_reserved_stream(self):
        for name in ('../../outside.exe', r'C:\Windows\outside.exe', 'a.txt:payload', 'CON', '', '..'):
            result = bridge.safe_filename(name, 'a' * 32)
            self.assertEqual(Path(result).name, result)
            self.assertNotIn(':', result)
            self.assertIn('a' * 12, result)


class InboxTests(unittest.TestCase):
    def setUp(self):
        self.folder = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.inbox = bridge.Inbox(self.folder)

    def request(self, number=1):
        return {'op': 'download', 'requestId': f'{number:032x}', 'url': 'https://example.com/a.zip', 'filename': 'a.zip'}

    def test_acceptance_survives_new_instance_and_is_idempotent(self):
        request = self.request()
        self.assertEqual(self.inbox.submit(request), request['requestId'])
        other = bridge.Inbox(self.folder)
        self.assertEqual(other.submit(request), request['requestId'])
        self.assertEqual(len(other.pending()), 1)
        changed = request | {'url': 'https://example.com/other'}
        with self.assertRaises(ValueError):
            other.submit(changed)

    def test_pending_and_claimed_restore_without_terminal_replay(self):
        token = self.inbox.submit(self.request())
        self.inbox.mark(token, 'queued')
        self.assertEqual(self.inbox.pending(), [])
        self.assertEqual(len(self.inbox.pending(restore=True)), 1)
        self.inbox.mark(token, 'saved')
        self.assertEqual(self.inbox.pending(restore=True), [])
        with self.inbox.connect() as db:
            self.assertEqual(db.execute('SELECT url FROM requests').fetchone()[0], '')

    def test_queue_cap_and_unknown_fields(self):
        for n in range(bridge.MAX_PENDING):
            self.inbox.submit(self.request(n))
        with self.assertRaises(ValueError):
            self.inbox.submit(self.request(100))
        for extra in ('path', 'headers', 'cookies', 'command', 'adapter_ids'):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                self.inbox.submit(self.request(100) | {extra: 'untrusted'})

    def test_withdrawn_request_is_never_replayed(self):
        token = self.inbox.submit(self.request())
        self.inbox.mark(token, 'withdrawn')
        self.assertEqual(self.inbox.pending(restore=True), [])
        with self.assertRaises(ValueError):
            self.inbox.submit(self.request())

    def test_desktop_accepts_all_available_links_and_enforces_restrictions(self):
        from desktop import Desktop
        with patch('desktop.History'):
            api = Desktop(restore=False)
        token = self.inbox.submit(self.request())
        api._browser_inbox = self.inbox
        api._rows = [{'name': 'Wi-Fi', 'index': 13, 'status': 'Up', 'gateway': True},
                     {'name': 'USB', 'index': 49, 'status': 'Up', 'gateway': True}]
        with patch('browser_bridge.plain_directory', return_value=self.folder):
            api._accept_browser_requests()
        job = next(iter(api._jobs.values()))
        self.assertEqual(job['links'], {'Wi-Fi': 13, 'USB': 49})
        self.assertTrue(job['restricted'])
        self.assertEqual(job['recovery_id'], token)
        api._accept_browser_requests()
        self.assertEqual(len(api._jobs), 1)
        self.assertTrue(api.cancel_waiting(job['view']['id']))
        self.assertEqual(self.inbox.status(token), 'cancelled')


if __name__ == '__main__':
    unittest.main()
