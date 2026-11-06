"""Terminal commands. Dispatches before GUI imports; native protocols stay separate."""
import argparse
import ctypes
import io
import json
import sys
from version import VERSION


def terminal_streams():
    if sys.stdout is not None and sys.stderr is not None:
        return
    ctypes.windll.kernel32.AttachConsole(0xffffffff)
    from browser_bridge import native_stream
    try:
        if sys.stdout is None:
            sys.stdout = io.TextIOWrapper(native_stream('wb'), encoding='utf-8', write_through=True)
    except OSError:
        pass  # No console (for example Settings > Apps > Uninstall): say() shows a message box instead.
    if sys.stderr is None:
        sys.stderr = sys.stdout


def say(message, error=False):
    """Print to the terminal, or show a message box when the exe was started without one."""
    stream = sys.stderr if error else sys.stdout
    if stream is not None:
        print(message, file=stream)
    else:
        ctypes.windll.user32.MessageBoxW(None, message, 'FetchVolt', 0x10 if error else 0x40)


def manage(argv):
    """--install opens the setup wizard (or installs silently); --uninstall removes the installed copy."""
    import installer
    parser = argparse.ArgumentParser(prog='fetchvolt')
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--install', action='store_true', help='Install this FetchVolt.exe for the current user (opens the setup wizard).')
    action.add_argument('--uninstall', action='store_true', help='Remove the installed FetchVolt for the current user.')
    parser.add_argument('--silent', action='store_true', help='With --install, skip the wizard (requires --accept-license).')
    parser.add_argument('--accept-license', action='store_true', help='With --silent, confirm you accept the LICENSE terms.')
    parser.add_argument('--dir', help='With --install, the install folder (default: the Programs folder in your local app data).')
    parser.add_argument('--no-shortcut', action='store_true', help='With --silent, do not create a Start menu shortcut.')
    parser.add_argument('--no-path', action='store_true', help='With --silent, do not add fetchvolt to PATH.')
    parser.add_argument('--remove-history', action='store_true', help='With --uninstall, also delete speed history.')
    args = parser.parse_args(argv)
    if args.remove_history and not args.uninstall:
        parser.error('--remove-history requires --uninstall')
    if args.uninstall and (args.silent or args.accept_license or args.dir or args.no_shortcut or args.no_path):
        parser.error('--silent, --accept-license, --dir, --no-shortcut and --no-path require --install')
    if (args.accept_license or args.no_shortcut or args.no_path) and not args.silent:
        parser.error('--accept-license, --no-shortcut and --no-path require --silent')
    if args.silent and not args.accept_license:
        parser.error('--silent requires --accept-license to confirm you accept the LICENSE terms')
    try:
        if args.install:
            layout = installer.Layout()
            if args.dir:
                layout = layout.at(installer.validate_directory(args.dir))
            if not args.silent:
                import install_wizard
                return install_wizard.run(layout)
            where = installer.install(layout, accept_license=True, shortcut=not args.no_shortcut, add_path=not args.no_path)
            say(f'FetchVolt installed in {where}. Open a new terminal to use fetchvolt --help.')
        else:
            from runtime_paths import executable
            installer.uninstall(remove_history=args.remove_history, current_exe=executable())
            say('FetchVolt was removed for this user.')
        return 0
    except installer.InstallerError as error:
        say('FetchVolt: ' + str(error), error=True)
        return 1
    except OSError as error:
        from diagnostics import failure
        failure('installer-failed', error)
        say('FetchVolt: Windows refused the change. Check permissions and the local diagnostic log.', error=True)
        return 1


def main(argv=None):
    terminal_streams()
    if argv and argv[0] in ('--install', '--uninstall'):
        return manage(argv)
    parser = argparse.ArgumentParser(prog='fetchvolt', description='FetchVolt desktop and verified updates.')
    parser.add_argument('--version', action='version', version='FetchVolt ' + VERSION)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('connections', help='List connected adapter IDs and names.')
    update = commands.add_parser('update', help='Check for or install a publisher-verified update.')
    update.add_argument('--check', action='store_true', help='Check only; do not download or install.')
    update.add_argument('--json', action='store_true', help='Emit machine-readable status.')
    args = parser.parse_args(argv)
    if args.command == 'update' and args.json and not args.check:
        parser.error('--json requires --check')
    from diagnostics import configure
    try:
        configure()
    except OSError:
        pass
    try:
        if args.command == 'connections':
            from network_monitor import snapshot
            _, rows = snapshot()
            print(json.dumps([{'id': row['index'], 'name': row['name'], 'link': row['link']}
                              for row in rows if row['status'] == 'Up' and row['gateway']], ensure_ascii=True))
            return 0
        from updater import check, prepare, version
        manifest, raw = check()
        available = version(manifest['version']) > version(VERSION)
        result = {'current': VERSION, 'latest': manifest['version'], 'available': available}
        if args.check or not available:
            print(json.dumps(result) if args.json else f"FetchVolt {VERSION}; latest verified release {manifest['version']}. " + ('Update available.' if available else 'Already up to date.'))
            return 0
        print('Downloading the publisher-verified update; checking hashes and Microsoft Defender.', flush=True)
        prepare(manifest, raw)
        print('Verified update queued. The terminal launcher will report the installation result.', flush=True)
        return 42
    except Exception as error:
        from diagnostics import failure
        failure('cli-command-failed', error)
        # Only our controlled ValueError messages are shown; raw network/OS errors stay private.
        from updater import UpdateError
        message = str(error) if isinstance(error, UpdateError) else 'The command failed. Check connectivity, Windows security and the local diagnostic log.'
        print('FetchVolt: ' + message, file=sys.stderr)
        return 1
