const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { webcrypto } = require('node:crypto');
const context = vm.createContext({ URL, crypto: webcrypto });
vm.runInContext(fs.readFileSync(__dirname + '/../../extension/policy.js', 'utf8'), context);
const policy = context.PortFlockPolicy;
const safe = { id: 1, url: 'https://example.com/file.zip', state: 'in_progress', danger: 'safe', incognito: false };
test('public files only with an explicit safe browser classification', () => {
  assert.equal(policy.eligible(safe), true);
  for (const change of [{ incognito: true }, { byExtensionId: 'another-extension' }, { danger: 'uncommon' },
    { danger: 'accepted' }, { danger: undefined }, { state: 'complete' }, { url: 'http://example.com/a' },
    { url: 'blob:https://example.com/a' }, { url: 'https://127.0.0.1/a' }, { url: 'https://printer.local/a' },
    { url: 'https://user:pass@example.com/a' }, { url: 'https://example.com/a#fragment' }]) {
    assert.equal(policy.eligible({ ...safe, ...change }), false, JSON.stringify(change));
  }
});
test('random IDs have fixed shape and no collisions in a sample', () => {
  const ids = new Set(Array.from({ length: 1000 }, () => policy.requestId()));
  assert.equal(ids.size, 1000);
  for (const id of ids) assert.match(id, /^[a-f0-9]{32}$/);
});
test('temporary browser UUID is replaced by the URL basename', () => {
  assert.equal(policy.filenameHint({ ...safe, filename: 'cd3cd3cd-6447-45cd-9e2d-687a52019d70' }), 'file.zip');
  assert.equal(policy.filenameHint({ ...safe, filename: 'C:\\Downloads\\My File.zip' }), 'My File.zip');
  assert.equal(policy.filenameHint({ ...safe, filename: '', finalUrl: 'https://cdn.example.com/cd3cd3cd-6447-45cd-9e2d-687a52019d70' }), 'file.zip');
});
