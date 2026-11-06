from pathlib import Path
import tempfile
import time
import tkinter
import unittest
from unittest.mock import patch
import uuid
import winreg

import install_wizard
import installer
from tests.python.test_installer import delete_tree


class WizardTests(unittest.TestCase):
    def setUp(self):
        folder = Path(self.enterContext(tempfile.TemporaryDirectory()))
        root = f'Software\\FetchVoltTest\\{uuid.uuid4().hex}'
        self.addCleanup(delete_tree, 'Software\\FetchVoltTest')
        self.layout = installer.Layout(local=folder / 'local', programs=folder / 'programs', broadcast=False,
                                       uninstall_key=root + '\\Uninstall', environment_key=root + '\\Environment',
                                       run_key=root + '\\Run')
        self.folder = folder
        self.source = folder / 'download' / 'FetchVolt.exe'
        self.source.parent.mkdir()
        self.source.write_bytes(b'MZ build')
        self.shortcut = self.enterContext(patch.object(installer, 'create_shortcut'))
        self.enterContext(patch.object(installer, 'running_copies', return_value=[]))
        self.wizard = install_wizard.Wizard(self.layout, self.source, headless=True)
        self.addCleanup(self.close)

    def close(self):
        try:
            self.wizard.root.destroy()
        except tkinter.TclError:
            pass

    def pump(self, until, seconds=10):
        end = time.monotonic() + seconds
        while not until():
            self.wizard.root.update()
            if time.monotonic() > end:
                self.fail('The wizard did not reach the expected state.')
            time.sleep(0.01)

    def enabled(self, button):
        return 'disabled' not in button.state()

    def to_folder_page(self):
        self.wizard.next()
        self.wizard.accepted.set(True)
        self.wizard.next()
        self.assertEqual(self.wizard.page, 'folder')

    # pages and buttons --------------------------------------------------------------------------------------
    def test_starts_on_welcome_with_only_next_and_cancel(self):
        wizard = self.wizard
        self.assertEqual(wizard.page, 'welcome')
        self.assertFalse(self.enabled(wizard.back_button))
        self.assertTrue(self.enabled(wizard.next_button))
        self.assertTrue(self.enabled(wizard.cancel_button))

    def test_license_page_shows_the_license_and_blocks_next_until_accepted(self):
        wizard = self.wizard
        wizard.next()
        self.assertEqual(wizard.page, 'license')
        self.assertIn('PolyForm', wizard.license_box.get('1.0', 'end'))
        self.assertEqual(wizard.license_box.cget('state'), 'disabled')
        self.assertFalse(self.enabled(wizard.next_button))
        wizard.accepted.set(True)
        self.assertTrue(self.enabled(wizard.next_button))
        wizard.accepted.set(False)
        self.assertFalse(self.enabled(wizard.next_button))

    def test_next_cannot_skip_the_license_even_if_called_directly(self):
        wizard = self.wizard
        wizard.next()
        wizard.next()
        self.assertEqual(wizard.page, 'license')
        self.assertIn('Accept the license', wizard.message.get())

    def test_back_returns_between_license_and_folder_pages(self):
        self.to_folder_page()
        self.wizard.back()
        self.assertEqual(self.wizard.page, 'license')
        self.wizard.back()
        self.assertEqual(self.wizard.page, 'welcome')

    def test_folder_page_labels_install_button_and_explains_custom_folder_limit(self):
        self.to_folder_page()
        wizard = self.wizard
        self.assertEqual(wizard.next_button.cget('text'), 'Install')
        self.assertIn('in-app updates keep working', wizard.folder_note.cget('text'))
        wizard.folder.set(str(self.folder / 'Custom'))
        self.assertIn('in-app updates', wizard.folder_note.cget('text'))
        self.assertIn('not available', wizard.folder_note.cget('text'))
        wizard.folder.set(str(self.layout.install))
        self.assertIn('keep working', wizard.folder_note.cget('text'))

    # validation ---------------------------------------------------------------------------------------------
    def test_unsafe_folder_shows_the_reason_and_stays_on_the_page(self):
        self.to_folder_page()
        busy = self.folder / 'Busy'
        busy.mkdir()
        (busy / 'important.docx').write_bytes(b'x')
        self.wizard.folder.set(str(busy))
        self.wizard.next()
        self.assertEqual(self.wizard.page, 'folder')
        self.assertIn('other files', self.wizard.message.get())
        self.assertTrue((busy / 'important.docx').exists())
        self.assertFalse((busy / 'Net Booster.exe').exists())

    def test_running_installed_copy_blocks_install(self):
        self.to_folder_page()
        with patch.object(installer, 'running_copies', return_value=[7]):
            self.wizard.next()
        self.assertEqual(self.wizard.page, 'folder')
        self.assertIn('Close the installed copy', self.wizard.message.get())

    # install ------------------------------------------------------------------------------------------------
    def test_full_install_to_a_custom_folder_registers_everything(self):
        self.to_folder_page()
        wizard = self.wizard
        custom = self.folder / 'My Apps' / 'FetchVolt'
        (self.folder / 'My Apps').mkdir()
        wizard.folder.set(str(custom))
        wizard.next()
        self.assertEqual(wizard.page, 'installing')
        self.assertFalse(self.enabled(wizard.next_button))
        self.assertFalse(self.enabled(wizard.cancel_button))
        self.pump(lambda: wizard.page == 'finish')
        self.assertEqual(wizard.installed_to, custom)
        self.assertEqual((custom / 'Net Booster.exe').read_bytes(), b'MZ build')
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.layout.uninstall_key) as key:
            self.assertEqual(winreg.QueryValueEx(key, 'InstallLocation')[0], str(custom))
            self.assertIn('PolyForm', winreg.QueryValueEx(key, 'LicenseAccepted')[0])
        self.shortcut.assert_called_once()
        self.assertEqual(wizard.next_button.cget('text'), 'Close')
        self.assertIn('not available', wizard.finish_text.cget('text'))

    def test_unchecked_options_are_honoured(self):
        self.to_folder_page()
        wizard = self.wizard
        wizard.shortcut.set(False)
        wizard.add_path.set(False)
        wizard.next()
        self.pump(lambda: wizard.page == 'finish')
        self.shortcut.assert_not_called()
        self.assertEqual(installer._path_entries(self.layout)[0], [])

    def test_install_failure_returns_to_the_folder_page_with_a_plain_message(self):
        self.to_folder_page()
        wizard = self.wizard
        with patch.object(installer, 'install', side_effect=PermissionError(5, r'denied C:\Users\secret')):
            wizard.next()
            self.pump(lambda: wizard.page == 'folder')
        self.assertIn('Windows refused the change', wizard.message.get())
        self.assertNotIn('secret', wizard.message.get())
        self.assertIsNone(wizard.installed_to)
        self.assertTrue(self.enabled(wizard.next_button))

    def test_unexpected_failure_does_not_leak_details(self):
        self.to_folder_page()
        with patch.object(installer, 'install', side_effect=RuntimeError('internal path C:\\secret')):
            self.wizard.next()
            self.pump(lambda: self.wizard.page == 'folder')
        self.assertNotIn('secret', self.wizard.message.get())
        self.assertIn('installation failed', self.wizard.message.get())

    # finishing and cancelling -------------------------------------------------------------------------------
    def finish_install(self):
        self.to_folder_page()
        self.wizard.next()
        self.pump(lambda: self.wizard.page == 'finish')

    def test_finish_launches_the_installed_app_when_checked(self):
        self.finish_install()
        with patch('subprocess.Popen') as popen:
            self.wizard.next()
        self.assertEqual(popen.call_args.args[0], [str(self.layout.exe)])
        with self.assertRaises(tkinter.TclError):
            self.wizard.root.winfo_exists()

    def test_finish_does_not_launch_when_unchecked(self):
        self.finish_install()
        self.wizard.launch.set(False)
        with patch('subprocess.Popen') as popen:
            self.wizard.next()
        popen.assert_not_called()

    def test_cancel_closes_without_installing(self):
        self.to_folder_page()
        self.wizard.cancel()
        with self.assertRaises(tkinter.TclError):
            self.wizard.root.winfo_exists()
        self.assertIsNone(self.wizard.installed_to)
        self.assertFalse(self.layout.install.exists())
        self.assertFalse(self.layout.exe.exists())

    def test_run_returns_1_when_cancelled_and_0_after_install(self):
        with patch.object(install_wizard, 'Wizard') as factory:
            factory.return_value.installed_to = None
            self.assertEqual(install_wizard.run(self.layout), 1)
            factory.return_value.installed_to = Path('C:/x')
            self.assertEqual(install_wizard.run(self.layout), 0)


if __name__ == '__main__':
    unittest.main()
