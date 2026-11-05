"""649 deterministic updater boundary cases; no network or production key access.

Generated methods are separately discoverable. Authentication is mocked only in
schema tests; test_updater exercises actual Windows RSA verification separately.
"""
import base64
import io
import itertools
import json
import unittest
from unittest.mock import Mock, patch

import updater
from tests.python.test_updater import manifest_for


class UpdateBoundaryMatrix(unittest.TestCase):
    pass


def register(name, case):
    case.__name__ = 'test_' + name
    setattr(UpdateBoundaryMatrix, case.__name__, case)


def valid_version_case(parts):
    def case(self):
        self.assertEqual(updater.version('.'.join(map(str, parts))), parts)
    return case


for parts in itertools.product((0, 1, 9, 255, 65535), repeat=3):
    register('version_valid_' + '_'.join(map(str, parts)), valid_version_case(parts))


BAD_COMPONENTS = (
    '65536', '99999', '100000', '01', '00', '00001', '-1', '+1',
    '1.0', '1e2', 'NaN', 'inf', '', ' ', '\t', '\n',
    '1 ', ' 1', '1\n', '1\t', '0x1', '1_0', '1,0', 'v1',
    '1-rc', '1+meta', '/', '\\', '%31', '１', '١', 'True',
)


def invalid_version_case(position, component):
    def case(self):
        parts = ['2', '6', '0']
        parts[position] = component
        with self.assertRaises(updater.UpdateError):
            updater.version('.'.join(parts))
    return case


for position, (number, component) in itertools.product(range(3), enumerate(BAD_COMPONENTS)):
    register(f'version_invalid_{position}_{number:02}', invalid_version_case(position, component))


BAD_SIZES = (0, -1, updater.MAX_ZIP + 1, True, False, None, '1', 1.5, [], {})
BAD_HASHES = ('', 'a', 'a' * 63, 'a' * 65, 'A' * 64, 'g' * 64,
              'a' * 63 + '\n', 'a' * 63 + ' ', None, True, 1, [], {}, 'ａ' * 64)
BAD_ENTRIES = (None, [], True, 'entry', 1, {}, {'sha256': 'a' * 64}, {'bytes': 1})


def manifest_case(filename, field, value):
    def case(self):
        manifest = manifest_for()
        if field is None:
            manifest['files'][filename] = value
        else:
            manifest['files'][filename][field] = value
        payload = json.dumps(manifest).encode()
        signature = b'x' * 384
        raw = json.dumps({'algorithm': 'rsa-pkcs1v15-sha256',
                          'payload': base64.b64encode(payload).decode(),
                          'signature': base64.b64encode(signature).decode()}).encode()
        # This isolates authenticated-schema validation, not RSA correctness.
        with patch.object(updater, 'verify_signature') as verify:
            with self.assertRaises(updater.UpdateError):
                updater.parse_manifest(raw)
            verify.assert_called_once_with(payload, signature)
    return case


for index, filename in enumerate(sorted(updater.FILES)):
    for number, value in enumerate(BAD_SIZES):
        register(f'file_{index}_size_{number:02}', manifest_case(filename, 'bytes', value))
    for number, value in enumerate(BAD_HASHES):
        register(f'file_{index}_hash_{number:02}', manifest_case(filename, 'sha256', value))
    for number, value in enumerate(BAD_ENTRIES):
        register(f'file_{index}_entry_{number:02}', manifest_case(filename, None, value))


class FakeLease:
    def __init__(self):
        self.checks = 0
        self.close = Mock()

    def check(self):
        self.checks += 1


class FakeResponse:
    """Honours read(n), with controllable network fragmentation and timeout."""
    status = 200

    def __init__(self, body, chunk, declared=None, timeout=False):
        self.body = io.BytesIO(body)
        self.chunk = chunk
        self.declared = declared
        self.timeout = timeout
        self.reads = 0
        self.closed = 0

    def getheader(self, name, default=None):
        return self.declared if name == 'Content-Length' else default

    def read(self, count):
        self.reads += 1
        if self.timeout and self.reads > 1:
            raise TimeoutError('simulated read deadline')
        return self.body.read(min(count, self.chunk))

    def close(self):
        self.closed += 1
        self.body.close()


def fetch_case(size, chunk, file_output=False, length_header=False, failure=None):
    def case(self):
        body = bytes(index % 251 for index in range(size))
        response = FakeResponse(body, chunk, str(size) if length_header else None,
                                timeout=failure == 'timeout')
        lease = FakeLease()
        target = io.BytesIO() if file_output else None
        limit = size - 1 if failure == 'oversize' else size
        expected = size + 1 if failure == 'truncated' else size
        if failure == 'oversize':
            expected = None
        with patch('net_booster.request', return_value=(lease, response)) as request:
            if failure:
                error = TimeoutError if failure == 'timeout' else updater.UpdateError
                with self.assertRaises(error):
                    updater.fetch('https://example.com/update', limit, target, expected)
            else:
                result = updater.fetch('https://example.com/update', limit, target, expected)
                self.assertEqual(target.getvalue() if target is not None else result, body)
                if target is not None:
                    self.assertEqual(result, b'')
            request.assert_called_once_with('https://example.com/update', 0, {},
                                            public_only=True, timeout=10, header_timeout=15,
                                            response_timeout=90, redirect_limit=5)
        self.assertEqual(response.closed, 1)
        self.assertTrue(response.body.closed)
        lease.close.assert_called_once_with()
        self.assertGreaterEqual(lease.checks, 1)
        if target is not None:
            self.assertFalse(target.closed, 'Caller owns the output stream')
            target.close()
    return case


for size, chunk in itertools.product((1, 7, 64, 1024, 65537), (1, 3, 64, 65536)):
    for output, header in itertools.product((False, True), repeat=2):
        register(f'fetch_ok_{size}_{chunk}_{int(output)}_{int(header)}',
                 fetch_case(size, chunk, output, header))
    for failure in ('oversize', 'truncated', 'timeout'):
        register(f'fetch_{failure}_{size}_{chunk}', fetch_case(size, chunk, failure=failure))


if __name__ == '__main__':
    unittest.main()
