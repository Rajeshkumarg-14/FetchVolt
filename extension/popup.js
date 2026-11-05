const api = globalThis.browser || chrome;
function call(object, method, ...args) {
  if (globalThis.browser) return object[method](...args);
  return new Promise((resolve, reject) => object[method](...args, value => {
    const error = chrome.runtime.lastError;
    if (error) reject(new Error(error.message)); else resolve(value);
  }));
}
const toggle = document.getElementById('enabled');
const status = document.getElementById('status');
call(api.storage.local, 'get', ['enabled', 'lastResult', 'lastTransfer']).then(async value => {
  toggle.checked = value.enabled === true;
  status.textContent = value.lastResult || 'Automatic handoff is off by default.';
  if (value.lastTransfer) {
    try {
      const response = await call(api.runtime, 'sendNativeMessage', 'com.rajeshkumarg.portflock', { op: 'status', id: value.lastTransfer });
      if (response.ok) status.textContent = 'Last app transfer: ' + response.state + '. Check FetchVolt for details.';
    } catch { /* Keep the local last-result message if the app is unavailable. */ }
  }
}).catch(() => { status.textContent = 'Extension settings are unavailable.'; });
toggle.addEventListener('change', async () => {
  try {
    await call(api.storage.local, 'set', { enabled: toggle.checked });
    status.textContent = toggle.checked ? 'Automatic public HTTPS handoff enabled.' : 'Downloads stay in your browser.';
  } catch { toggle.checked = false; status.textContent = 'Could not save this setting.'; }
});
document.getElementById('check').addEventListener('click', async () => {
  try {
    const result = await call(api.runtime, 'sendNativeMessage', 'com.rajeshkumarg.portflock', { op: 'ping' });
    status.textContent = result?.ok ? 'Connected to FetchVolt ' + result.version : 'App connection rejected.';
  } catch { status.textContent = 'Install FetchVolt and run browser setup first. Keep handoff off until connected.'; }
});
