import contextlib
import io
from pathlib import Path
import tempfile
import unittest
import unittest.mock
from unittest.mock import patch
import uuid
import winreg

import cli
import installer


def delete_tree(path):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_ALL_ACCESS) as key:
            while True:
                try:
                    delete_tree(path + '\\' + winreg.EnumKey(key, 0))
                except OSError:
                    break
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
    except FileNotFoundError:
        pass


class InstallerTests(unittest.TestCase):
    def setUp(self):
        folder = Path(self.enterContext(tempfile.TemporaryDirectory()))
        root = f'Software\\FetchVoltTest\\{uuid.uuid4().hex}'
        self.addCleanup(delete_tree, 'Software\\FetchVoltTest')
        self.layout = installer.Layout(local=folder / 'local', programs=folder / 'programs', broadcast=False,
                                       uninstall_key=root + '\\Uninstall', environment_key=root + '\\Environment',
                                       run_key=root + '\\Run')
        self.source = folder / 'download' / 'FetchVolt.exe'
        self.source.parent.mkdir()
        self.source.write_bytes(b'MZ new build')
        self.shortcut = self.enterContext(patch.object(installer, 'create_shortcut'))
        self.browser = self.enterContext(patch('browser_setup.remove_registration'))
        self.enterContext(patch.object(installer, 'running_copies', return_value=[]))

    def install(self, layout=None, **options):
        return installer.install(layout or self.layout, self.source, accept_license=True, **options)

    def value(self, key, name):
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as handle:
            return winreg.QueryValueEx(handle, name)[0]

    def set_path(self, text, kind=winreg.REG_EXPAND_SZ):
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, self.layout.environment_key, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, 'Path', 0, kind, text)

    def path_parts(self):
        return installer._path_entries(self.layout)[0]

    # install ------------------------------------------------------------------------------------------------
    def test_install_copies_executable_and_registers_it(self):
        self.assertEqual(self.install(), self.layout.install)
        self.assertEqual(self.layout.exe.read_bytes(), b'MZ new build')
        self.assertTrue(self.layout.launcher.read_bytes().startswith(installer.LAUNCHER_HEADER.encode()))
        self.assertIn(b'\r\n', self.layout.launcher.read_bytes())
        uninstall = self.layout.uninstall_key
        self.assertEqual(self.value(uninstall, 'DisplayName'), 'FetchVolt')
        self.assertEqual(self.value(uninstall, 'DisplayVersion'), installer.VERSION)
        self.assertEqual(self.value(uninstall, 'UninstallString'), f'"{self.layout.exe}" --uninstall')
        self.assertEqual(self.value(uninstall, 'CliPath'), str(self.layout.install))
        self.assertEqual(self.path_parts(), [str(self.layout.install)])
        self.shortcut.assert_called_once_with(self.layout)
        self.assertEqual([p.name for p in self.layout.install.iterdir() if p.name.startswith('.NetBooster-')], [])

    def test_install_requires_license_acceptance_and_changes_nothing_without_it(self):
        with self.assertRaisesRegex(installer.InstallerError, 'Accept the license'):
            installer.install(self.layout, self.source)
        self.assertFalse(self.layout.install.exists())
        with self.assertRaises(FileNotFoundError):
            self.value(self.layout.uninstall_key, 'DisplayName')

    def test_install_records_license_acceptance(self):
        self.install()
        recorded = self.value(self.layout.uninstall_key, 'LicenseAccepted')
        self.assertTrue(recorded.startswith('PolyForm Noncommercial 1.0.0; FetchVolt ' + installer.VERSION))

    def test_install_copies_license_files_next_to_the_exe(self):
        self.install()
        self.assertTrue((self.layout.install / 'LICENSE').is_file())

    def test_install_preserves_existing_path_and_registry_kind(self):
        self.set_path(r'C:\Tools;%USERPROFILE%\bin')
        self.install()
        self.assertEqual(self.path_parts(), [r'C:\Tools', r'%USERPROFILE%\bin', str(self.layout.install)])
        self.assertEqual(installer._path_entries(self.layout)[1], winreg.REG_EXPAND_SZ)

    def test_reinstall_replaces_executable_without_duplicating_path(self):
        self.install()
        self.source.write_bytes(b'MZ newer build')
        self.install()
        self.assertEqual(self.layout.exe.read_bytes(), b'MZ newer build')
        self.assertEqual(self.path_parts().count(str(self.layout.install)), 1)

    def test_options_can_skip_shortcut_and_path(self):
        self.set_path(r'C:\Tools')
        self.install(shortcut=False, add_path=False)
        self.shortcut.assert_not_called()
        self.assertFalse(self.layout.programs.exists())
        self.assertEqual(self.path_parts(), [r'C:\Tools'])
        self.assertTrue(self.layout.exe.exists())

    def test_install_refuses_while_installed_copy_runs_and_changes_nothing(self):
        with patch.object(installer, 'running_copies', return_value=[1234]), \
                self.assertRaisesRegex(installer.InstallerError, 'Close the installed copy'):
            self.install()
        self.assertFalse(self.layout.exe.exists())
        with self.assertRaises(FileNotFoundError):
            self.value(self.layout.uninstall_key, 'DisplayName')

    def test_install_refuses_to_copy_the_installed_executable_onto_itself(self):
        self.install()
        with self.assertRaisesRegex(installer.InstallerError, 'already is the installed one'):
            installer.install(self.layout, self.layout.exe, accept_license=True)
        self.assertEqual(self.layout.exe.read_bytes(), b'MZ new build')

    def test_install_from_source_checkout_is_refused(self):
        with patch('runtime_paths.is_packaged', return_value=False), self.assertRaisesRegex(installer.InstallerError, 'release'):
            installer.install(self.layout, accept_license=True)

    # custom folder ------------------------------------------------------------------------------------------
    def test_custom_folder_is_recorded_and_used_by_uninstall(self):
        custom = self.layout.install.parent / 'MyFetchVolt'
        chosen = self.layout.at(custom)
        self.install(chosen)
        self.assertTrue((custom / 'Net Booster.exe').exists())
        self.assertEqual(self.value(self.layout.uninstall_key, 'InstallLocation'), str(custom))
        self.assertEqual(self.path_parts(), [str(custom)])
        self.assertFalse(chosen.is_default)
        self.assertTrue(self.layout.is_default)
        # The registry entry's command runs from the installed exe; uninstall must find the recorded folder.
        installer.uninstall(self.layout)
        self.assertFalse(custom.exists())
        self.assertEqual(self.path_parts(), [])

    def test_launcher_does_not_hardcode_the_default_folder(self):
        self.assertNotIn('Programs', installer.LAUNCHER)
        self.assertIn('FV_DIR', installer.LAUNCHER)

    def test_validate_directory_accepts_new_empty_and_own_folders(self):
        base = self.layout.install.parent
        base.mkdir(parents=True, exist_ok=True)
        self.assertEqual(installer.validate_directory(str(base / 'New')), base / 'New')
        deep = base / 'not' / 'created' / 'yet'
        self.assertEqual(installer.validate_directory(str(deep)), deep)
        (base / 'Empty').mkdir()
        self.assertEqual(installer.validate_directory(f'"{base / "Empty"}"'), base / 'Empty')
        self.install()
        self.assertEqual(installer.validate_directory(str(self.layout.install)), self.layout.install)

    def test_validate_directory_rejects_unsafe_choices_with_clear_messages(self):
        base = self.layout.install.parent
        base.mkdir(parents=True, exist_ok=True)
        (base / 'Busy').mkdir()
        (base / 'Busy' / 'photos.zip').write_bytes(b'x')
        (base / 'file.txt').write_text('x')
        missing_drive = next(f'{letter}:' + chr(92) for letter in 'ZYXWVUTSRQPONM' if not Path(f'{letter}:' + chr(92)).exists())
        cases = {'': 'Choose an install folder', 'relative\\dir': 'local drive', '\\\\server\\share\\x': 'local drive',
                 'C:\\': 'not a whole drive', str(base / 'Busy'): 'other files', str(base / 'file.txt'): 'is a file',
                 missing_drive + 'x' + chr(92) + 'y': 'not available'}
        for text, message in cases.items():
            with self.subTest(text), self.assertRaisesRegex(installer.InstallerError, message):
                installer.validate_directory(text)
        self.assertTrue((base / 'Busy' / 'photos.zip').exists())

    # uninstall ----------------------------------------------------------------------------------------------
    def test_uninstall_removes_everything_it_installed(self):
        self.set_path(r'C:\Tools')
        self.install()
        self.layout.shortcut.write_text('lnk')
        self.assertFalse(installer.uninstall(self.layout))
        self.assertFalse(self.layout.install.exists())
        self.assertFalse(self.layout.shortcut.exists())
        self.assertEqual(self.path_parts(), [r'C:\Tools'])
        with self.assertRaises(FileNotFoundError):
            self.value(self.layout.uninstall_key, 'DisplayName')
        self.browser.assert_called_once_with()

    def test_uninstall_keeps_foreign_files_and_launchers_it_did_not_write(self):
        self.install()
        foreign = self.layout.install / 'notes.txt'
        foreign.write_text('mine')
        self.layout.launcher.write_text('@echo custom launcher')
        installer.uninstall(self.layout)
        self.assertTrue(foreign.exists())
        self.assertTrue(self.layout.launcher.exists())
        self.assertFalse(self.layout.exe.exists())

    def test_uninstall_keeps_history_unless_asked(self):
        self.install()
        self.layout.data.mkdir(parents=True)
        history = self.layout.data / 'history.sqlite3'
        history.write_text('rows')
        installer.uninstall(self.layout)
        self.assertTrue(history.exists())
        self.install()
        with patch('psutil.process_iter', return_value=[]):
            installer.uninstall(self.layout, remove_history=True)
        self.assertFalse(history.exists())
        self.assertFalse(self.layout.data.exists())

    def test_uninstall_refuses_while_running(self):
        self.install()
        with patch.object(installer, 'running_copies', return_value=[99]), \
                self.assertRaisesRegex(installer.InstallerError, 'Close FetchVolt'):
            installer.uninstall(self.layout)
        self.assertTrue(self.layout.exe.exists())
        self.assertEqual(self.value(self.layout.uninstall_key, 'DisplayName'), 'FetchVolt')

    def test_uninstall_refuses_during_a_pending_update(self):
        self.install()
        (self.layout.install / '.update-result.json').write_text('{"state":"pending","pid":4242}')
        with patch('psutil.pid_exists', return_value=True), self.assertRaisesRegex(installer.InstallerError, 'verified update'):
            installer.uninstall(self.layout)
        self.assertTrue(self.layout.exe.exists())

    def test_uninstall_removes_only_matching_startup_entry(self):
        self.install()
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, self.layout.run_key, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, 'PortFlock', 0, winreg.REG_SZ, f'"{self.layout.exe}" --startup')
        installer.uninstall(self.layout)
        with self.assertRaises(FileNotFoundError):
            self.value(self.layout.run_key, 'PortFlock')
        self.install()
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, self.layout.run_key, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, 'PortFlock', 0, winreg.REG_SZ, r'"D:\other\app.exe" --startup')
        installer.uninstall(self.layout)
        self.assertEqual(self.value(self.layout.run_key, 'PortFlock'), r'"D:\other\app.exe" --startup')

    def test_uninstall_from_the_installed_exe_defers_its_own_deletion(self):
        self.install()
        with patch('subprocess.Popen') as popen:
            own = installer.uninstall(self.layout, current_exe=self.layout.exe)
        self.assertTrue(own)
        self.assertTrue(self.layout.exe.exists())
        command = popen.call_args.args[0][-1]
        self.assertIn(str(self.layout.exe), command)
        self.assertIn('del /f /q', command)

    def test_uninstall_deletes_completed_update_staging_only(self):
        self.install()
        done = self.layout.install / '.fetchvolt-update-done'
        failed = self.layout.install / '.fetchvolt-update-failed'
        for folder in (done, failed):
            folder.mkdir()
            (folder / 'FetchVolt.exe').write_bytes(b'x')
        (done / 'complete.marker').write_text('FetchVolt update completed\n')
        installer.uninstall(self.layout)
        self.assertFalse(done.exists())
        self.assertTrue(failed.exists())

    def test_uninstall_when_nothing_is_installed_is_a_clean_noop(self):
        self.assertFalse(installer.uninstall(self.layout))

    def test_path_removal_ignores_lookalike_entries(self):
        lookalike = str(self.layout.install) + 'X'
        self.set_path(f'{lookalike};{self.layout.install}')
        installer.remove_from_path(self.layout)
        self.assertEqual(self.path_parts(), [lookalike])


class ManageCommandTests(unittest.TestCase):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), patch.object(cli, 'terminal_streams'):
            try:
                code = cli.main(list(argv))
            except SystemExit as exit:
                code = exit.code
        return code, out.getvalue(), err.getvalue()

    def test_silent_install_requires_explicit_license_acceptance(self):
        with patch.object(installer, 'install') as install:
            code, _, err = self.run_cli('--install', '--silent')
        self.assertEqual(code, 2)
        self.assertIn('--silent requires --accept-license', err)
        install.assert_not_called()

    def test_silent_install_reports_location_and_passes_options(self):
        with patch.object(installer, 'install', return_value=Path(r'C:\x\Net Booster')) as install:
            code, out, _ = self.run_cli('--install', '--silent', '--accept-license', '--no-shortcut', '--no-path')
        self.assertEqual(code, 0)
        self.assertIn(r'installed in C:\x\Net Booster', out)
        self.assertEqual(install.call_args.kwargs, dict(accept_license=True, shortcut=False, add_path=False))

    def test_install_without_silent_opens_the_wizard(self):
        wizard = unittest.mock.MagicMock()
        wizard.run.return_value = 0
        with patch.dict('sys.modules', {'install_wizard': wizard}), patch.object(installer, 'install') as install:
            code, _, _ = self.run_cli('--install')
        self.assertEqual(code, 0)
        wizard.run.assert_called_once()
        install.assert_not_called()

    def test_dir_is_validated_and_used(self):
        with patch.object(installer, 'validate_directory', return_value=Path(r'C:\Apps\FV')) as validate, \
                patch.object(installer, 'install', return_value=Path(r'C:\Apps\FV')) as install:
            code, _, _ = self.run_cli('--install', '--silent', '--accept-license', '--dir', r'C:\Apps\FV')
        validate.assert_called_once_with(r'C:\Apps\FV')
        self.assertEqual(code, 0)
        self.assertEqual(str(install.call_args.args[0].install), r'C:\Apps\FV')

    def test_unsafe_dir_exits_1_with_the_message(self):
        code, _, err = self.run_cli('--install', '--silent', '--accept-license', '--dir', 'C:\\')
        self.assertEqual(code, 1)
        self.assertIn('not a whole drive', err)

    def test_installer_errors_become_exit_1_with_safe_message(self):
        message = 'Close the installed copy of FetchVolt before updating it.'
        with patch.object(installer, 'install', side_effect=installer.InstallerError(message)):
            code, out, err = self.run_cli('--install', '--silent', '--accept-license')
        self.assertEqual(code, 1)
        self.assertEqual(out, '')
        self.assertEqual(err, 'FetchVolt: ' + message + '\n')

    def test_os_errors_do_not_leak_raw_details(self):
        with patch.object(installer, 'uninstall', side_effect=PermissionError(5, r'Access denied: C:\Users\secret\file')), \
                patch('diagnostics.failure'):
            code, _, err = self.run_cli('--uninstall')
        self.assertEqual(code, 1)
        self.assertNotIn('secret', err)

    def test_uninstall_flag_passes_remove_history(self):
        with patch.object(installer, 'uninstall') as uninstall:
            code, out, _ = self.run_cli('--uninstall', '--remove-history')
        self.assertEqual(code, 0)
        self.assertTrue(uninstall.call_args.kwargs['remove_history'])
        self.assertIn('removed', out)

    def test_flag_combinations_are_rejected(self):
        cases = [(('--install', '--remove-history'), '--remove-history requires --uninstall'),
                 (('--install', '--accept-license'), 'require --silent'),
                 (('--install', '--no-path'), 'require --silent'),
                 (('--uninstall', '--silent'), 'require --install'),
                 (('--uninstall', '--dir', 'C:\\x'), 'require --install'),
                 (('--install', '--uninstall'), 'not allowed with')]
        for argv, message in cases:
            with self.subTest(argv):
                code, _, err = self.run_cli(*argv)
                self.assertEqual(code, 2)
                self.assertIn(message, err)


if __name__ == '__main__':
    unittest.main()
