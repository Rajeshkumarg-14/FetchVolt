import assert from 'node:assert/strict';
import test from 'node:test';
import { formatRate, formatStorage } from '../../ui/metrics.mjs';

test('rates distinguish decimal bits, decimal bytes, and binary bytes', () => {
  assert.equal(formatRate(1_000_000, 'mbps'), '8.00 Mbps');
  assert.equal(formatRate(1_000_000, 'mbs'), '1.00 MB/s');
  assert.equal(formatRate(1_048_576, 'mibs'), '1.00 MiB/s');
  assert.equal(formatRate(1_000, 'kbps'), '8.00 kbps');
  assert.equal(formatRate(1_000, 'auto'), '8.00 kbps');
  assert.equal(formatRate(125_000_000, 'auto'), '1.00 Gbps');
  assert.equal(formatRate(null, 'mbps'), '—');
  assert.equal(formatRate(-1, 'mbps'), '—');
});

test('drive usage uses binary storage units', () => {
  assert.equal(formatStorage(1024 ** 3), '1.0 GiB');
  assert.equal(formatStorage(1024 ** 4), '1.00 TiB');
});
