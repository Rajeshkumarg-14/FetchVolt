"""Crash recovery records for verified byte-range transfers."""
from contextlib import contextmanager
import hashlib
import msvcrt
import json
import os
from pathlib import Path
import re
import stat
import tempfile

MAX_RECORD_BYTES = 8 * 1024 * 1024


def directory():
    folder = Path(os.environ['LOCALAPPDATA']) / 'Net Booster' / 'transfers'
    folder.mkdir(parents=True, exist_ok=True)
    return folder.resolve(strict=True)


def record_path(identifier):
    if not isinstance(identifier, str) or not re.fullmatch(r'[a-f0-9]{32}', identifier):
        raise ValueError('Invalid recovery identifier.')
    return directory() / (identifier + '.json')


class Checkpoint:
    def __init__(self, identifier, data):
        self.identifier = identifier
        self.data = data

    @property
    def path(self):
        return record_path(self.identifier)

    @property
    def partial(self):
        return Path(self.data['partial'])

    def save(self):
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.path.parent,
                                             prefix='.checkpoint-', delete=False) as out:
                temporary = Path(out.name)
                json.dump(self.data, out, separators=(',', ':'))
                out.flush()
                os.fsync(out.fileno())
            temporary.replace(self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def completed(self, offset, digest):
        self.data['chunks'][str(offset)] = digest
        self.save()

    def verified(self):
        size, chunk = self.data['size'], self.data['chunk']
        valid = {}
        with self.partial.open('rb') as file:
            for offset, expected in self.data['chunks'].items():
                start = int(offset)
                file.seek(start)
                remaining = min(chunk, size - start)
                digest = hashlib.sha256()
                while remaining:
                    block = file.read(min(65536, remaining))
                    if not block:
                        break
                    digest.update(block)
                    remaining -= len(block)
                if remaining == 0 and digest.hexdigest() == expected:
                    valid[offset] = expected
        self.data['chunks'] = valid
        self.save()
        return {int(offset) for offset in valid}

    def remove(self):
        self.path.unlink(missing_ok=True)


def load(identifier):
    path = record_path(identifier)
    if not path.exists():
        return None
    if path.stat().st_size > MAX_RECORD_BYTES:
        raise ValueError('Recovery record is too large.')
    data = json.loads(path.read_text(encoding='utf-8'))
    target = Path(data['target'])
    partial = Path(data['partial'])
    if (not target.is_absolute() or not partial.is_absolute() or partial.parent != target.parent
            or not re.fullmatch(r'\.net-booster-[a-zA-Z0-9_-]+\.part', partial.name)):
        raise ValueError('Recovery path is invalid.')
    info = partial.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        raise ValueError('Recovery staging file is invalid.')
    size, chunk = data['size'], data['chunk']
    if type(size) is not int or not 0 < size <= 128 * 1024 ** 3:
        raise ValueError('Recovery size is invalid.')
    if type(chunk) is not int or not 16 <= chunk <= 8 * 1024 ** 2:
        raise ValueError('Recovery chunk size is invalid.')
    if not isinstance(data['etag'], str) or len(data['etag']) > 2048:
        raise ValueError('Recovery file identifier is invalid.')
    expected = data.get('sha256')
    if expected is not None and (not isinstance(expected, str) or not re.fullmatch(r'[a-f0-9]{64}', expected)):
        raise ValueError('Recovery checksum is invalid.')
    chunks = data['chunks']
    if not isinstance(chunks, dict) or len(chunks) > 65536:
        raise ValueError('Recovery ranges are invalid.')
    for offset, digest in chunks.items():
        if (not re.fullmatch(r'[0-9]{1,15}', offset) or int(offset) % chunk or int(offset) >= size
                or not isinstance(digest, str) or not re.fullmatch(r'[a-f0-9]{64}', digest)):
            raise ValueError('Recovery range is invalid.')
    if not isinstance(data['url'], str) or len(data['url']) > 16384:
        raise ValueError('Recovery URL is invalid.')
    return Checkpoint(identifier, data)


def create(identifier, url, target, partial, size, etag, chunk, expected_sha256=None, *, restricted=False):
    record = Checkpoint(identifier, {
        'url': url, 'target': str(Path(target).resolve()), 'partial': str(partial.resolve()),
        'size': size, 'etag': etag, 'chunk': chunk, 'chunks': {}, 'sha256': expected_sha256,
        'restricted': restricted,
    })
    record.save()
    return record


def pending():
    results = []
    for path in sorted(directory().glob('*.json'), key=lambda item: item.name)[:50]:
        try:
            record = load(path.stem)
            if record is not None:
                results.append(record)
        except (OSError, ValueError, TypeError, KeyError):
            continue
    return results


@contextmanager
def claim(identifier):
    path = record_path(identifier).with_suffix('.lock')
    file = path.open('a+b')
    try:
        if not path.stat().st_size:
            file.write(b'0')
            file.flush()
        file.seek(0)
        try:
            msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise OSError('This staged download is already open in another app session.') from None
        try:
            yield
        finally:
            file.seek(0)
            msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
    finally:
        file.close()
        try:
            path.unlink()
        except OSError:
            pass
