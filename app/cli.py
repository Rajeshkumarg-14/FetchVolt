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
    if sys.stdout is None:
        sys.stdout = io.TextIOWrapper(native_stream('wb'), encoding='utf-8', write_through=True)
    if sys.stderr is None:
        sys.stderr = sys.stdout


def main(argv=None):
    terminal_streams()
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
