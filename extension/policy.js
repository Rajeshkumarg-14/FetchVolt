/* Pure policy helpers, also exercised by Node's test runner. */
(function (root) {
  function eligible(item) {
    if (!item || !Number.isInteger(item.id) || item.incognito || item.byExtensionId ||
        item.state !== 'in_progress' || item.danger !== 'safe') return false;
    try {
      const url = new URL(item.finalUrl || item.url);
      const host = url.hostname.toLowerCase().replace(/\.$/, '');
      if (url.protocol !== 'https:' || url.username || url.password || url.hash || url.port ||
          url.href.length > 16384 || !host.includes('.') ||
          /(^|\.)(localhost|local|internal)$/.test(host) || host.includes(':') ||
          /^\d+(\.\d+){3}$/.test(host)) return false;
      return true;
    } catch { return false; }
  }
  function requestId() {
    return Array.from(crypto.getRandomValues(new Uint8Array(16)), n => n.toString(16).padStart(2, '0')).join('');
  }
  function filenameHint(item) {
    const name = (item.filename || '').split(/[\\/]/).pop();
    // Automation and some browsers use a temporary UUID before choosing the
    // final name. Preserve the URL filename instead of exposing that UUID.
    if (name && !/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(name)) return name.slice(-512);
    for (const value of [item.url, item.finalUrl]) {
      try {
        const candidate = decodeURIComponent(new URL(value).pathname.split('/').pop() || '');
        if (candidate.includes('.') && !/^[a-f0-9-]{32,36}$/i.test(candidate)) return candidate.slice(-512);
      } catch { /* Try the next URL, then a neutral filename. */ }
    }
    return 'download.bin';
  }
  root.PortFlockPolicy = Object.freeze({ eligible, requestId, filenameHint });
})(globalThis);
