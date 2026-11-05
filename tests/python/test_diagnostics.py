import logging
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import diagnostics


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.folder = Path(self.enterContext(tempfile.TemporaryDirectory()))
        old_level = diagnostics.LOGGER.level
        self.addCleanup(diagnostics.LOGGER.setLevel, old_level)
        previous = list(diagnostics.LOGGER.handlers)

        def close_new_handlers():
            for handler in diagnostics.LOGGER.handlers[:]:
                if handler not in previous:
                    diagnostics.LOGGER.removeHandler(handler)
                    handler.close()

        self.addCleanup(close_new_handlers)

    def test_failure_logs_omit_untrusted_exception_text(self):
        path = diagnostics.configure(self.folder)
        try:
            raise OSError(13, 'secret URL token and filename')
        except OSError as error:
            diagnostics.failure('transfer-failed', error, 9)
        content = path.read_text(encoding='utf-8')
        self.assertIn('transfer-failed transfer=9', content)
        self.assertIn('code=13', content)
        self.assertIn('test_diagnostics.py:', content)
        self.assertNotIn('secret', content)

    def test_logs_rotate_and_old_sessions_are_pruned(self):
        for day in range(1, 10):
            (self.folder / f'portflock-200001{day:02}-000000-000000-1.log').touch()
        (self.folder / 'unrelated.log').touch()
        with patch.multiple(diagnostics, LOG_BYTES=256, RETAINED_FILES=4):
            path = diagnostics.configure(self.folder)
            self.assertEqual(len(list(self.folder.glob('portflock-*.log*'))), 4)
            for _ in range(40):
                diagnostics.LOGGER.log(logging.INFO, 'transfer-progress %s', 'x' * 65)
        session = list(self.folder.glob(path.name + '*'))
        self.assertEqual(len(session), diagnostics.SESSION_FILES)
        self.assertTrue(all(log.stat().st_size < 256 for log in session))
        self.assertTrue((self.folder / 'unrelated.log').is_file())
