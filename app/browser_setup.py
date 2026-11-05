"""Opt-in browser host registration. Never modifies browser profiles or policy."""
import html
import json
import os
from pathlib import Path
import sys
import winreg
from runtime_paths import is_packaged, executable, resource_root

from browser_bridge import HOST, FIREFOX_ID, EXTENSION_FILES, data_directory, extension_id, plain_directory

REGISTRY_KEYS = (
    rf'Software\Google\Chrome\NativeMessagingHosts\{HOST}',
    rf'Software\Microsoft\Edge\NativeMessagingHosts\{HOST}',
    rf'Software\Mozilla\NativeMessagingHosts\{HOST}',
)


def detected_browsers():
    names = {'msedge.exe': 'Microsoft Edge', 'chrome.exe': 'Google Chrome', 'firefox.exe': 'Mozilla Firefox',
             'brave.exe': 'Brave', 'vivaldi.exe': 'Vivaldi', 'opera.exe': 'Opera'}
    found = []
    for executable, name in names.items():
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
                try:
                    with winreg.OpenKey(hive, rf'Software\Microsoft\Windows\CurrentVersion\App Paths\{executable}',
                                        0, winreg.KEY_READ | view) as key:
                        path = winreg.QueryValueEx(key, '')[0]
                    if Path(path.strip('"')).is_file() and name not in found:
                        found.append(name)
                except OSError:
                    pass
    return found


def setup(open_guide=True):
    if not is_packaged():
        raise ValueError('Browser setup requires the installed Windows executable.')
    source = resource_root() / 'extension'
    target = data_directory()
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, r'Software\PortFlock\BrowserIntegration', 0, winreg.KEY_WRITE) as key:
        winreg.SetValueEx(key, 'DataRoot', 0, winreg.REG_SZ, str(target))
    chromium = plain_directory(target / 'chromium')
    firefox = plain_directory(target / 'firefox')
    manifest = json.loads((source / 'manifest.json').read_text('utf-8'))
    for folder in (chromium, firefox):
        for name in (*EXTENSION_FILES, 'icon.png'):
            (folder / name).write_bytes((source / name).read_bytes())
    (chromium / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    manifest.pop('key')
    manifest['background'] = {'scripts': ['policy.js', 'background.js']}
    manifest['browser_specific_settings'] = {'gecko': {'id': FIREFOX_ID, 'strict_min_version': '140.0',
                                                     'data_collection_permissions': {'required': ['none']}}}
    (firefox / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    base = {'name': HOST, 'description': 'FetchVolt browser download bridge', 'path': str(executable()), 'type': 'stdio'}
    chrome_host = target / 'chromium-host.json'
    firefox_host = target / 'firefox-host.json'
    chrome_host.write_text(json.dumps(base | {'allowed_origins': ['chrome-extension://' + extension_id() + '/']}), encoding='utf-8')
    firefox_host.write_text(json.dumps(base | {'allowed_extensions': [FIREFOX_ID]}), encoding='utf-8')
    for registry, path in zip(REGISTRY_KEYS, (chrome_host, chrome_host, firefox_host)):
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, registry, 0, winreg.KEY_WRITE) as key:
            winreg.SetValueEx(key, '', 0, winreg.REG_SZ, str(path))
    browsers = ', '.join(detected_browsers()) or 'No supported browser detected in Windows App Paths'
    guide = target / 'setup.html'
    guide.write_text('''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'">
<title>FetchVolt browser setup</title><style>:root{font:16px/1.7 'Segoe UI',sans-serif;color-scheme:dark;background:#080808;color:#edf3ff}body{max-width:760px;padding:45px 24px;margin:auto}h1{font-size:38px;line-height:1.1}code{overflow-wrap:anywhere;color:#afd0ff}li{margin:14px 0}a{color:#afd0ff}</style>
<h1>Connect your browser.</h1><p>Detected: ''' + html.escape(browsers) + '''.</p>
<p>The local bridge is registered for this Windows user. No browser extension has been installed or enabled automatically.</p>
<h2>Edge and Chrome</h2><ol><li>Open <code>edge://extensions</code> or <code>chrome://extensions</code>.</li>
<li>Turn on Developer mode. Choose <strong>Load unpacked</strong> and select this folder:<br><code>''' + html.escape(str(chromium)) + '''</code></li>
<li>Pin FetchVolt Browser Link. Open it and choose <strong>Check app connection</strong>.</li>
<li>Read its limitations, then enable <strong>Send downloads to FetchVolt</strong>.</li></ol>
<p>Other Chromium browsers may support the same unpacked folder and Chrome native host registry. Compatibility depends on their policies; they are not all individually tested.</p>
<h2>Firefox — development preview</h2><p>Firefox release installation needs Mozilla signing. Until publication, use <code>about:debugging#/runtime/this-firefox</code>, Load Temporary Add-on, and select <code>''' + html.escape(str(firefox / 'manifest.json')) + '''</code>. Temporary add-ons disappear when Firefox restarts. Automatic handoff remains conservative when a browser supplies no safe-download classification.</p>
<h2>What gets transferred?</h2><p>Public direct HTTPS URLs only, with no cookies, browser authentication, headers, POST body or private-session access. Switch handoff off for login-protected or POST downloads. Blob, HTTP and local network downloads stay in the browser. Supported files are saved in your Windows Downloads\\FetchVolt folder with a unique suffix; existing files are never replaced.</p>
<p>FetchVolt records the request durably before the extension cancels the browser transfer. If native messaging fails, it tries to resume the browser transfer. Check browser Downloads if a transfer remains paused. An accepted app download can still fail because of network, server or security checks; use the app's recovery controls or turn the extension off and retry in the browser.</p>
<p>No local HTTP listener, no telemetry, and no extra MCP endpoint. The app already provides its separate, folder-scoped MCP server.</p>
<p>Remove Browser Link in the browser's Extensions page. Uninstalling FetchVolt removes native host registration; browser extensions must be removed through the browser.</p>
<footer>Copyright © 2026 Rajesh Kumar G · <a href="https://rajeshkumarg.com">rajeshkumarg.com</a></footer></html>''', encoding='utf-8')
    if open_guide:
        os.startfile(guide)
    return {'folder': str(chromium), 'guide': str(guide), 'browsers': detected_browsers()}


def remove_registration():
    """Remove only registrations pointing to our current user's known manifests."""
    target = data_directory()
    for registry, name in zip(REGISTRY_KEYS, ('chromium-host.json', 'chromium-host.json', 'firefox-host.json')):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, registry) as key:
                current = winreg.QueryValueEx(key, '')[0]
            if os.path.normcase(current) == os.path.normcase(str(target / name)):
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, registry)
        except FileNotFoundError:
            pass
    for folder in (target / 'chromium', target / 'firefox'):
        if folder.is_dir():
            plain_directory(folder)
            for name in (*EXTENSION_FILES, 'icon.png', 'manifest.json'):
                (folder / name).unlink(missing_ok=True)
            if not any(folder.iterdir()):
                folder.rmdir()
    for name in ('setup.html', 'chromium-host.json', 'firefox-host.json'):
        (target / name).unlink(missing_ok=True)
    # Inbox/recovery information is user data and is deliberately preserved.
