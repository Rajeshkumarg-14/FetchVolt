"""Windows adapter telemetry and local history."""
from contextlib import closing
import ctypes
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import sqlite3
import string
import subprocess
import time

import psutil


def snapshot():
    command = """
    $ErrorActionPreference = 'Stop'
    [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
    $config = @{}
    Get-NetIPConfiguration | ForEach-Object { $config[[int]$_.InterfaceIndex] = $_ }
    $stats = @{}
    Get-NetAdapterStatistics -ErrorAction SilentlyContinue | ForEach-Object { $stats[$_.Name] = $_ }
    $rows = @(Get-NetAdapter | ForEach-Object {
        $ip = $config[[int]$_.ifIndex]
        $counter = $stats[$_.Name]
        [PSCustomObject]@{
            name = $_.Name
            kind = $(if ($_.InterfaceDescription -match 'Remote NDIS|Apple Mobile Device Ethernet|USB.*Tether') { 'USB tethering' } else { '' })
            index = $_.ifIndex
            status = [string]$_.Status
            link = $_.LinkSpeed
            ip = ($ip.IPv4Address.IPAddress -join ', ')
            gateway = [bool]$ip.IPv4DefaultGateway
            rx = $counter.ReceivedBytes
            tx = $counter.SentBytes
        }
    })
    ConvertTo-Json -InputObject $rows -Compress
    """
    powershell = Path(os.environ['SystemRoot']) / 'System32' / 'WindowsPowerShell' / 'v1.0' / 'powershell.exe'
    output = subprocess.check_output(
        [str(powershell), '-NoProfile', '-NonInteractive', '-Command', command],
        creationflags=subprocess.CREATE_NO_WINDOW, encoding='utf-8', timeout=15,
    )
    return time.monotonic(), json.loads(output)


def traffic_snapshot():
    counters = psutil.net_io_counters(pernic=True, nowrap=False)
    return time.monotonic(), {
        name: {'rx': values.bytes_recv, 'tx': values.bytes_sent}
        for name, values in counters.items()
    }


def storage_snapshot():
    """Read local fixed drives without walking folders or probing network shares."""
    kernel = ctypes.windll.kernel32
    mask = kernel.GetLogicalDrives()
    drives = []
    for index, letter in enumerate(string.ascii_uppercase):
        root = letter + ':\\'
        if not mask & (1 << index) or kernel.GetDriveTypeW(root) != 3:
            continue
        try:
            usage = shutil.disk_usage(root)
        except OSError:
            continue
        if usage.total:
            drives.append({'drive': letter + ':', 'total': usage.total, 'free': usage.free})
    return drives


def mbps(previous, current, seconds):
    if previous is None or current is None or current < previous or seconds <= 0:
        return None
    return (current - previous) * 8 / seconds / 1_000_000


class History:
    def __init__(self, path=None):
        self.path = Path(path) if path else Path(os.environ['LOCALAPPDATA']) / 'Net Booster' / 'history.sqlite3'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('''CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY, recorded TEXT, category TEXT,
                subject TEXT, outcome TEXT, details TEXT
            )''')

    def add(self, category, subject, outcome, details):
        recorded = datetime.now().astimezone().isoformat(timespec='seconds')
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                'INSERT INTO events (recorded, category, subject, outcome, details) VALUES (?, ?, ?, ?, ?)',
                (recorded, category, subject, outcome, details),
            )

    def recent(self):
        with closing(sqlite3.connect(self.path)) as db:
            return db.execute(
                'SELECT recorded, category, subject, outcome, details FROM events ORDER BY id DESC LIMIT 500'
            ).fetchall()


def changes(previous, current):
    for name, state in current.items():
        if previous.get(name) != state:
            yield name, state[0], state[1] or 'No IPv4 address'
    for name in previous.keys() - current.keys():
        yield name, 'Unavailable', 'Adapter disappeared'
