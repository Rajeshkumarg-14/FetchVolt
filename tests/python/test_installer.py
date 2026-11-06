import contextlib
import io
from pathlib import Path
import tempfile
import unittest
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
        self.running = installer.running_copies

    def value(self, key, name):
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as handle:
            return winreg.QueryValueEx(handle, name)[0]

    def set_path(self, text, kind=winreg.REG_EXPAND_SZ):
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, self.layout.environment_key, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, 'Path', 0, kind, text)

    def path_parts(self):
        return installer._path_entries(self.layout)[0]

    def test_install_copies_executable_and_registers_it(self):
        install = installer.install(self.layout, self.source)
        self.assertEqual(install, self.layout.install)
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

    def test_install_preserves_existing_path_and_registry_kind(self):
        self.set_path(r'C:\Tools;%USERPROFILE%\bin')
        installer.install(self.layout, self.source)
        self.assertEqual(self.path_parts(), [r'C:\Tools', r'%USERPROFILE%\bin', str(self.layout.install)])
        self.assertEqual(installer._path_entries(self.layout)[1], winreg.REG_EXPAND_SZ)

    def test_reinstall_replaces_executable_without_duplicating_path(self):
        installer.install(self.layout, self.source)
        self.source.write_bytes(b'MZ newer build')
        installer.install(self.layout, self.source)
        self.assertEqual(self.layout.exe.read_bytes(), b'MZ newer build')
        self.assertEqual(self.path_parts().count(str(self.layout.install)), 1)

    def test_install_refuses_while_installed_copy_runs_and_changes_nothing(self):
        with patch.object(installer, 'running_copies', return_value=[1234]), self.assertRaisesRegex(installer.InstallerError, 'Close the installed copy'):
            installer.install(self.layout, self.source)
        self.assertFalse(self.layout.exe.exists())
        with self.assertRaises(FileNotFoundError):
            self.value(self.layout.uninstall_key, 'DisplayName')

    def test_install_refuses_to_copy_the_installed_executable_onto_itself(self):
        installer.install(self.layout, self.source)
        with self.assertRaisesRegex(installer.InstallerError, 'already is the installed one'):
            installer.install(self.layout, self.layout.exe)
        self.assertEqual(self.layout.exe.read_bytes(), b'MZ new build')

    def test_install_from_source_checkout_is_refused(self):
        with patch('runtime_paths.is_packaged', return_value=False), self.assertRaisesRegex(installer.InstallerError, 'release'):
            installer.install(self.layout)

    def test_uninstall_removes_everything_it_installed(self):
        self.set_path(r'C:\Tools')
        installer.install(self.layout, self.source)
        self.layout.shortcut.write_text('lnk')
        self.assertFalse(installer.uninstall(self.layout))
        self.assertFalse(self.layout.install.exists())
        self.assertFalse(self.layout.shortcut.exists())
        self.assertEqual(self.path_parts(), [r'C:\Tools'])
        with self.assertRaises(FileNotFoundError):
            self.value(self.layout.uninstall_key, 'DisplayName')
        self.browser.assert_called_once_with()

    def test_uninstall_keeps_foreign_files_and_launchers_it_did_not_write(self):
        installer.install(self.layout, self.source)
        foreign = self.layout.install / 'notes.txt'
        foreign.write_text('mine')
        self.layout.launcher.write_text('@echo custom launcher')
        installer.uninstall(self.layout)
        self.assertTrue(foreign.exists())
        self.assertTrue(self.layout.launcher.exists())
        self.assertFalse(self.layout.exe.exists())

    def test_uninstall_keeps_history_unless_asked(self):
        installer.install(self.layout, self.source)
        self.layout.data.mkdir(parents=True)
        history = self.layout.data / 'history.sqlite3'
        history.write_text('rows')
        installer.uninstall(self.layout)
        self.assertTrue(history.exists())
        installer.install(self.layout, self.source)
        with patch('psutil.process_iter', return_value=[]):
            installer.uninstall(self.layout, remove_history=True)
        self.assertFalse(history.exists())
        self.assertFalse(self.layout.data.exists())

    def test_uninstall_refuses_while_running(self):
        installer.install(self.layout, self.source)
        with patch.object(installer, 'running_copies', return_value=[99]), self.assertRaisesRegex(installer.InstallerError, 'Close FetchVolt'):
            installer.uninstall(self.layout)
        self.assertTrue(self.layout.exe.exists())
        self.assertEqual(self.value(self.layout.uninstall_key, 'DisplayName'), 'FetchVolt')

    def test_uninstall_refuses_during_a_pending_update(self):
        installer.install(self.layout, self.source)
        (self.layout.install / '.update-result.json').write_text('{"state":"pending","pid":4242}')
        with patch('psutil.pid_exists', return_value=True), self.assertRaisesRegex(installer.InstallerError, 'verified update'):
            installer.uninstall(self.layout)
        self.assertTrue(self.layout.exe.exists())

    def test_uninstall_removes_only_matching_startup_entry(self):
        installer.install(self.layout, self.source)
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, self.layout.run_key, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, 'PortFlock', 0, winreg.REG_SZ, f'"{self.layout.exe}" --startup')
        installer.uninstall(self.layout)
        with self.assertRaises(FileNotFoundError):
            self.value(self.layout.run_key, 'PortFlock')
        installer.install(self.layout, self.source)
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, self.layout.run_key, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, 'PortFlock', 0, winreg.REG_SZ, r'"D:\other\app.exe" --startup')
        installer.uninstall(self.layout)
        self.assertEqual(self.value(self.layout.run_key, 'PortFlock'), r'"D:\other\app.exe" --startup')

    def test_uninstall_from_the_installed_exe_defers_its_own_deletion(self):
        installer.install(self.layout, self.source)
        with patch('subprocess.Popen') as popen:
            own = installer.uninstall(self.layout, current_exe=self.layout.exe)
        self.assertTrue(own)
        self.assertTrue(self.layout.exe.exists())
        command = popen.call_args.args[0][-1]
        self.assertIn(str(self.layout.exe), command)
        self.assertIn('del /f /q', command)

    def test_uninstall_deletes_completed_update_staging_only(self):
        installer.install(self.layout, self.source)
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

    def test_install_flag_reports_location(self):
        with patch.object(installer, 'install', return_value=Path(r'C:\x\Net Booster')):
            code, out, _ = self.run_cli('--install')
        self.assertEqual((code, 'installed in C:\\x\\Net Booster' in out), (0, True))

    def test_installer_errors_become_exit_1_with_safe_message(self):
        with patch.object(installer, 'install', side_effect=installer.InstallerError('Close the installed copy of FetchVolt before updating it.')):
            code, out, err = self.run_cli('--install')
        self.assertEqual(code, 1)
        self.assertEqual(out, '')
        self.assertEqual(err, 'FetchVolt: Close the installed copy of FetchVolt before updating it.\n')

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

    def test_remove_history_requires_uninstall(self):
        code, _, err = self.run_cli('--install', '--remove-history')
        self.assertEqual(code, 2)
        self.assertIn('--remove-history requires --uninstall', err)

    def test_install_and_uninstall_are_mutually_exclusive(self):
        self.assertEqual(self.run_cli('--install', '--uninstall')[0], 2)


if __name__ == '__main__':
    unittest.main()
