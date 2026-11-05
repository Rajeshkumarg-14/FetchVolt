/* No page scripts, cookies, headers, network fetches, or remote code. */
if (typeof importScripts === 'function') importScripts('policy.js');
const api = globalThis.browser || chrome;
const HOST = 'com.rajeshkumarg.portflock';
const inFlight = new Set();

function call(object, name, ...args) {
  if (globalThis.browser) return object[name](...args);
  return new Promise((resolve, reject) => object[name](...args, result => {
    const error = chrome.runtime.lastError;
    if (error) reject(new Error(error.message)); else resolve(result);
  }));
}
async function remember(message, id = null) {
  await call(api.storage.local, 'set', { lastResult: message, lastTransfer: id });
}
async function handoff(item) {
  if (!PortFlockPolicy.eligible(item) || inFlight.has(item.id) || inFlight.size >= 4) return;
  inFlight.add(item.id);
  let paused = false;
  let accepted = false;
  const marker = 'handoff-' + item.id;
  const requestId = PortFlockPolicy.requestId();
  try {
    const { enabled = false } = await call(api.storage.local, 'get', 'enabled');
    if (!enabled) return;
    await call(api.storage.local, 'set', { [marker]: { downloadId: item.id, requestId } });
    await call(api.downloads, 'pause', item.id);
    paused = true;
    // Re-read the danger state after pausing: never accept a browser warning.
    const [current] = await call(api.downloads, 'search', { id: item.id });
    if (!PortFlockPolicy.eligible(current)) return;
    const response = await call(api.runtime, 'sendNativeMessage', HOST, {
      op: 'download', requestId,
      url: current.finalUrl || current.url,
      filename: PortFlockPolicy.filenameHint(current)
    });
    if (!response || response.ok !== true || response.accepted !== true || !/^[a-f0-9]{32}$/.test(response.id)) {
      throw new Error('The desktop did not accept the transfer.');
    }
    // Only cancel once the native app has durably recorded ownership.
    accepted = true;
    await call(api.downloads, 'cancel', item.id);
    await remember('Sent to FetchVolt. Open the app to monitor progress.', response.id);
  } catch {
    await remember(accepted ? 'FetchVolt accepted the file, but browser cancellation failed. Check both queues.' :
      'Handoff failed. The download stays in your browser.');
  } finally {
    if (paused && !accepted) {
      try { await call(api.downloads, 'resume', item.id); }
      catch { await remember('Browser resume failed. Open browser Downloads to resume manually.'); }
    }
    inFlight.delete(item.id);
    try { await call(api.storage.local, 'remove', marker); } catch { /* Recover next time. */ }
  }
}
api.downloads.onCreated.addListener(item => { void handoff(item); });
// Recover only downloads marked by this extension, never unrelated user pauses.
async function recoverPauses() {
  const values = await call(api.storage.local, 'get', null);
  for (const [key, value] of Object.entries(values)) {
    if (!/^handoff-\d+$/.test(key) || !Number.isInteger(value?.downloadId)) continue;
    try {
      const [item] = await call(api.downloads, 'search', { id: value.downloadId });
      if (item?.state === 'in_progress' && item.paused) {
        const result = await call(api.runtime, 'sendNativeMessage', HOST, { op: 'status', id: value.requestId });
        if (result?.ok && ['pending', 'queued', 'saved'].includes(result.state)) {
          await call(api.downloads, 'cancel', item.id);
        } else {
          await call(api.downloads, 'resume', item.id);
        }
      }
      await call(api.storage.local, 'remove', key);
    } catch {
      // Preserve the marker so a later worker startup can retry safely.
      await remember('An interrupted handoff needs attention. Check browser Downloads and FetchVolt.');
    }
  }
}
void recoverPauses().catch(() => {});
api.runtime.onInstalled.addListener(() => {
  void call(api.storage.local, 'get', 'enabled').then(value => {
    if (typeof value.enabled !== 'boolean') return call(api.storage.local, 'set', { enabled: false });
  });
});
