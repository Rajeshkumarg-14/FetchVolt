# /// script
# requires-python = ">=3.14"
# dependencies = ["mcp==2.3.0", "psutil==7.2.2"]
# ///
"""Local stdio MCP server for the FetchVolt download engine."""
import argparse
from collections import deque
import os
from pathlib import Path
import re
import stat
import threading
from uuid import uuid4

from diagnostics import LOGGER, configure, failure
from net_booster import MAX_CONNECTIONS, download, validate_url
from network_monitor import snapshot
from windows_security import ScanError

ACTIVE_LIMIT = 2
COMPLETED_LIMIT = 20


def destination_under(root, relative):
    if not isinstance(relative, str) or len(relative) > 1024:
        raise ValueError('Enter a relative destination within the configured folder.')
    parts = re.split(r'[/\\]', relative)
    if any(not part or part in ('.', '..') or ':' in part or os.path.isreserved(part) for part in parts):
        raise ValueError('Use a relative Windows path without traversal or reserved names.')
    parent = root
    for part in parts[:-1]:
        parent = parent / part
        try:
            info = parent.lstat()
        except FileNotFoundError:
            raise ValueError('The destination subfolder must already exist.') from None
        if not stat.S_ISDIR(info.st_mode) or info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError('The destination subfolder must be a regular directory.')
    target = parent / parts[-1]
    try:
        target.lstat()
    except FileNotFoundError:
        return target
    raise FileExistsError('The destination already exists. Choose a different filename.')


def available_connections():
    _, rows = snapshot()
    return [
        {'id': row['index'], 'name': row['name'], 'link_rate': row['link']}
        for row in rows if row['status'] == 'Up' and row['gateway']
    ]


class DownloadService:
    def __init__(self, root):
        self.root = Path(root).resolve(strict=True)
        if not self.root.is_dir() or not re.fullmatch(r'[A-Za-z]:', self.root.drive):
            raise ValueError('The MCP root must be an existing local Windows directory.')
        self.lock = threading.Lock()
        self.jobs = {}
        self.completed = deque()
        self.targets = set()

    def start(self, url, destination, adapter_ids, sha256=None):
        validate_url(url)
        if not 1 <= len(adapter_ids) <= MAX_CONNECTIONS or any(type(index) is not int for index in adapter_ids):
            raise ValueError(f'Choose one to {MAX_CONNECTIONS} distinct adapter IDs.')
        if len(set(adapter_ids)) != len(adapter_ids):
            raise ValueError('Adapter IDs must be distinct.')
        if sha256 is not None:
            if not re.fullmatch(r'[A-Fa-f0-9]{64}', sha256):
                raise ValueError('SHA-256 must contain exactly 64 hexadecimal characters.')
            sha256 = sha256.lower()
        target = destination_under(self.root, destination)
        available = {row['id']: row['name'] for row in available_connections()}
        if any(index not in available for index in adapter_ids):
            raise ValueError('A selected adapter is unavailable. List connections again.')
        links = {available[index]: index for index in adapter_ids}
        identifier = uuid4().hex
        key = os.path.normcase(str(target))
        with self.lock:
            if len(self.targets) >= ACTIVE_LIMIT:
                raise ValueError('Two downloads are active. Wait for a slot.')
            if key in self.targets:
                raise ValueError('A download is already using this destination.')
            self.targets.add(key)
            self.jobs[identifier] = {
                'id': identifier, 'state': 'running', 'bytes': dict.fromkeys(links, 0), 'expected': None,
            }
        worker = threading.Thread(
            target=self._run, name='mcp-download-' + identifier[:8], daemon=True,
            args=(identifier, key, url, target, links, sha256),
        )
        try:
            worker.start()
        except RuntimeError:
            with self.lock:
                self.targets.discard(key)
                del self.jobs[identifier]
            raise RuntimeError('Could not start the download worker.') from None
        LOGGER.info('mcp-transfer-started transfer=%s adapters=%s', identifier, len(links))
        return self.status(identifier)

    def _run(self, identifier, key, url, target, links, sha256):
        def report(totals, expected):
            with self.lock:
                self.jobs[identifier].update(bytes=dict.fromkeys(links, 0) | totals, expected=expected)

        try:
            elapsed, totals = download(
                url, target, links, report, public_only=True, overwrite=False, expected_sha256=sha256,
            )
            outcome = dict(state='saved', path=str(target), bytes=totals, seconds=round(elapsed, 2))
            LOGGER.info('mcp-transfer-saved transfer=%s bytes=%s seconds=%.2f', identifier, sum(totals.values()), elapsed)
        except Exception as error:
            failure('mcp-transfer-failed', error, identifier)
            message = 'Download failed. Check the local FetchVolt diagnostic log.'
            if isinstance(error, ScanError):
                message = 'Windows Defender blocked the file or could not verify it.'
            elif isinstance(error, FileExistsError):
                message = 'The destination already exists. It was preserved.'
            elif isinstance(error, TimeoutError):
                message = 'The transfer timed out.'
            outcome = dict(state='failed', error=message)
        with self.lock:
            self.jobs[identifier].update(outcome)
            self.targets.discard(key)
            self.completed.append(identifier)
            while len(self.completed) > COMPLETED_LIMIT:
                del self.jobs[self.completed.popleft()]

    def status(self, identifier):
        with self.lock:
            if identifier not in self.jobs:
                raise ValueError('Unknown download ID for this server session.')
            return self.jobs[identifier].copy()


def create_server(service):
    from mcp.server.mcpserver import MCPServer
    from mcp.types import ToolAnnotations

    server = MCPServer('FetchVolt', instructions=(
        'Use list_connections to find adapter IDs. Start a public HTTPS download to a relative path '
        'inside the configured folder, then poll download_status. A saved result includes the full path. '
        'Keep this MCP server session open while downloads run.'
    ))

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    def list_connections() -> list[dict]:
        """List active Windows adapters with an IPv4 gateway."""
        return available_connections()

    @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True))
    def start_download(url: str, destination: str, adapter_ids: list[int], sha256: str | None = None) -> dict:
        """Start a public HTTPS download. Destination is relative to the configured root. Existing files are preserved."""
        return service.start(url, destination, adapter_ids, sha256)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    def download_status(id: str) -> dict:
        """Check state and bytes per adapter. Only a saved result has a path ready to use."""
        return service.status(id)

    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description='Run FetchVolt MCP over stdin/stdout.')
    parser.add_argument('--root', type=Path, required=True, help='Existing folder for MCP downloads')
    args = parser.parse_args(argv)
    service = DownloadService(args.root)
    try:
        configure()
    except OSError:
        pass
    create_server(service).run(transport='stdio')


if __name__ == '__main__':
    main()
