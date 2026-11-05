# Browser Link

Browser Link is an opt-in extension for public direct HTTPS downloads. The production Chromium manifest requests only `downloads`, `nativeMessaging` and `storage`. There are no content scripts, host permissions, cookies, page DOM access, externally-connectable endpoints, remote scripts, or local HTTP listener.

The app installer offers setup. Settings can open the same guide later. Setup discovers browser registrations through Windows App Paths, exports the extension, and registers exact per-user native host identities. The browser still requires the user to load/approve the extension. Edge and Chrome share a Chromium build. Other Chromium browsers depend on native-host compatibility. Firefox is a temporary development preview pending signing; automatic handoff remains conservative when the browser supplies no explicit safe classification.

## Handoff and recovery

1. Automatic handoff starts off. Once enabled, the extension considers only active public HTTPS downloads explicitly classified safe by the browser. It skips private sessions, browser-flagged downloads and downloads started by other extensions.
2. It records a temporary marker and pauses the browser transfer. A second check verifies the current danger state.
3. The allowlisted native host validates one bounded framed request, records it durably in the per-user SQLite inbox and launches/wakes the app. No paths, command text, headers, cookies or adapter IDs are accepted from the browser.
4. Only after durable native acceptance does the extension cancel the browser transfer. A native failure triggers browser resume. Interrupted workers use their own markers to reconcile pauses on restart.
5. The app queues the request using available internet adapters, up to seven, in Windows Downloads\FetchVolt with a unique filename suffix. Engine requests check actual public connection endpoints after every redirect, validate TLS, stream bounded buffers, preserve existing files, apply Mark of the Web and require a clean Defender scan before publication.

Acceptance is not a completed download. The app may still report a server, network, storage or scan failure. Open FetchVolt to inspect it. Login-protected links, POST requests, blobs, private URLs and browser-session-dependent files are outside the supported handoff flow; turn the extension off and use the browser for them. Cookies and browser authentication are not copied.

The browser can receive initial bytes before its download event is handled. The extension cannot retroactively prevent them, and no scanner can guarantee that every threat is detected. The original browser entry stays cancelled after an accepted handoff; retry in the browser with handoff disabled when app-side recovery is unavailable.

## Limits and trust boundaries

- Native host allows only the stable Chromium extension ID derived from the committed public key and the exact Firefox add-on ID. Keep the manifest key stable; store publication may require a deliberate ID migration.
- Input messages are limited to 24 KiB with a 20-second host lifetime. The inbox has at most 50 pending/queued requests, and the desktop limits concurrent work.
- URLs and filename hints are untrusted. Local/private addresses, credentials, fragments and custom ports are rejected. Filenames cannot choose directories or alternate streams. All SQL uses bound values.
- Full URLs can contain secrets. Pending/recovery records stay local and must not be committed. Terminal URLs are cleared; terminal inbox records are bounded. Canonical data-root registration keeps packaged apps and browsers consistent across filesystem redirection.
- The same Windows user can inspect their own files and registry. Origin checks, private source hosting and native compilation do not protect against a fully compromised local account.
- Uninstallation removes matching native host registration and known extension export files. It preserves user download/recovery data and does not modify browser profiles. Remove the extension through each browser.

The app's existing folder-scoped MCP server is separate. Browser Link exposes no AI endpoint and grants no AI permission.

## Verified preview checks

Source tests cover malformed frames, request shape, URL/path restrictions, queue capacity, duplicate IDs, pause recovery and failed handoff. A real Edge download of the official Python 3.14.0 source archive was transferred to the app, Defender-scanned and published with a SHA-256 matching the publisher's Sigstore metadata. This does not establish every browser/version/network combination. Native-compiled release validation is recorded with the release.
