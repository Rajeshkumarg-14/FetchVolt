const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { webcrypto } = require('node:crypto');

function harness({ enabled = true, rejectNative = false, danger = 'safe', markers = {} } = {}) {
  const events = [];
  const storage = { enabled, ...markers };
  const item = { id: 7, url: 'https://example.com/file.zip', filename: 'file.zip', danger, state: 'in_progress', paused: false };
  let created;
  const chrome = {
    runtime: { onInstalled: { addListener() {} }, sendNativeMessage(host, message, callback) {
      events.push('native:' + message.op);
      if (rejectNative) {
        chrome.runtime.lastError = { message: 'Host unavailable' }; callback(); delete chrome.runtime.lastError;
      } else callback(message.op === 'status' ? { ok: true, state: 'queued' } : { ok: true, accepted: true, id: message.requestId });
    } },
    storage: { local: {
      get(key, callback) { callback(key === null ? { ...storage } : { [key]: storage[key] }); },
      set(value, callback) { Object.assign(storage, value); callback(); },
      remove(key, callback) { delete storage[key]; callback(); },
    } },
    downloads: {
      onCreated: { addListener(callback) { created = callback; } },
      pause(id, callback) { events.push('pause:' + id); item.paused = true; callback(); },
      resume(id, callback) { events.push('resume:' + id); item.paused = false; callback(); },
      cancel(id, callback) { events.push('cancel:' + id); item.state = 'interrupted'; callback(); },
      search(query, callback) { callback(query.id === item.id ? [{ ...item }] : []); },
    },
  };
  const context = vm.createContext({ chrome, URL, crypto: webcrypto });
  vm.runInContext(fs.readFileSync(__dirname + '/../../extension/policy.js', 'utf8'), context);
  vm.runInContext(fs.readFileSync(__dirname + '/../../extension/background.js', 'utf8'), context);
  return { events, storage, item, start: () => created({ ...item }) };
}
const settle = () => new Promise(resolve => setTimeout(resolve, 35));
test('browser cancellation follows durable native acceptance', async () => {
  const h = harness(); await settle(); h.start(); await settle();
  assert.deepEqual(h.events, ['pause:7', 'native:download', 'cancel:7']);
  assert.match(h.storage.lastTransfer, /^[a-f0-9]{32}$/);
  assert.equal(Object.keys(h.storage).some(key => key.startsWith('handoff-')), false);
});
test('native failure restores the paused browser transfer', async () => {
  const h = harness({ rejectNative: true }); await settle(); h.start(); await settle();
  assert.deepEqual(h.events, ['pause:7', 'native:download', 'resume:7']);
  assert.equal(h.item.paused, false);
  assert.match(h.storage.lastResult, /stays in your browser/);
});
test('disabled or browser-flagged downloads are untouched', async () => {
  for (const options of [{ enabled: false }, { danger: 'uncommon' }, { danger: 'accepted' }]) {
    const h = harness(options); await settle(); h.start(); await settle(); assert.deepEqual(h.events, []);
  }
});
test('worker restart recovers only its own interrupted pause', async () => {
  const h = harness({ markers: { 'handoff-7': { downloadId: 7, requestId: 'a'.repeat(32) } } });
  h.item.paused = true;
  await settle();
  assert.deepEqual(h.events, ['native:status', 'cancel:7']);
  assert.equal(h.storage['handoff-7'], undefined);
});
