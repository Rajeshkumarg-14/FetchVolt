from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock, patch

import windows_startup as startup


class StartupTests(TestCase):
    def test_source_mode_never_creates_a_startup_entry(self):
        with patch.object(startup.sys, 'frozen', False, create=True), patch.object(startup.winreg, 'CreateKey') as create:
            self.assertEqual(startup.preferences(), {'enabled': False, 'supported': False})
            with self.assertRaises(ValueError):
                startup.set_enabled(True)
            create.assert_not_called()

    def test_startup_quotes_executable_and_uses_minimized_switch(self):
        with patch.object(startup.sys, 'frozen', True, create=True), patch.object(startup.sys, 'executable', 'C:/Program Files/FetchVolt/FetchVolt.exe'):
            command = startup.command()
            self.assertTrue(command.startswith('"'))
            self.assertTrue(command.endswith('" --startup'))
            with patch.object(startup.winreg, 'CreateKey'), patch.object(startup.winreg, 'SetValueEx') as write, patch.object(startup, 'preferences', return_value={'enabled': True, 'supported': True}):
                startup.set_enabled(True)
                self.assertEqual(write.call_args.args[-1], command)

    def test_disable_only_removes_our_matching_entry(self):
        with patch.object(startup, 'command', return_value='"C:/app.exe" --startup'), patch.object(startup.winreg, 'OpenKey'), patch.object(startup.winreg, 'QueryValueEx', return_value=('another command', 1)), patch.object(startup.winreg, 'DeleteValue') as delete:
            startup.set_enabled(False)
            delete.assert_not_called()

    def test_invalid_startup_values_are_rejected(self):
        for value in (None, 'yes', 1, [], {}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                startup.set_enabled(value)
