# FetchVolt terminal updates

## Release publishing

Keep version.py, native file/product metadata, desktop startup logging, extension version and Package-Release.py version consistent. Build and verify the actual executable and native protocol modes. Require a clean Defender scan. Package with scripts/Package-Release.py; this refreshes installer payload hashes and creates update-payload.json alongside the setup ZIP and checksums. Never overwrite a published artifact/version.

Run scripts/Sign-Update.ps1 -ManifestPath releases/update-payload.json -OutputPath website/update.json. The publisher key is outside Git at %LOCALAPPDATA%/FetchVolt/publisher/update-key.dpapi and is encrypted with Windows current-user DPAPI. Only app/update_key.py (the public verification key) is shipped. Back up the protected publisher key securely; losing it prevents signing updates for existing clients. Do not initialize a replacement for an already deployed trust key. Forks need their own release identity, trust key and update URL.

Publish verified, immutable release assets first; compare uploaded digests, then publish website/release.json and the signed website/update.json. Only reviewed static files go to the site repository. The signed envelope covers the archive URL, version, archive hash/size and exact per-file hashes/sizes. The app never accepts a mirror URL, unsigned metadata or an older installed version.

## Installation and runtime

The per-user installer creates fetchvolt.cmd inside the existing Net Booster installation and adds exactly that directory to the user PATH. New terminal processes see the command. The uninstaller removes the managed launcher and its own PATH entry while preserving unrelated entries. It refuses to run during an active verified update, removes validated completed staging directories, and retains failed staging for recovery review. Installation paths and browser identities retain upgrade compatibility.

Updates require the GUI to be closed and PowerShell 7 available as pwsh.exe on PATH. A signed update is downloaded to a new, validated .fetchvolt-update-* staging directory under the managed install. No user download file is executed by this mechanism. Only publisher-authenticated application files are eligible for replacement. All extracted payloads are hashed, marked and scanned before the local, bundled worker is invoked. No downloaded installer script is executed. The worker is application code embedded in the current installation and respects execution policy.

The worker waits for the old CLI process and outer onefile executable to exit, locks the app lifecycle file, rechecks the publisher signature and file hashes, checks versions, and moves files with rollback copies retained until the commit point. Windows Installed Apps version is refreshed when registry access permits. The CLI launcher polls .update-result.json for completion. It never kills the GUI or active downloads.

Successful staging folders are removed by the next update after path/link checks. Up to three failed staging directories may remain for diagnosis; further attempts stop for review rather than consuming unbounded disk space. If the worker fails or times out, check .update-result.json and verify the installed version before retrying. A verified setup bundle can repair the installation without deleting user data.

## Verification scope

Tests use independent ephemeral RSA keys; they do not require or export the production private key. Signed metadata tampering, untrusted keys, schema limits, ZIP traversal/duplicates/links, scan failures, downgrade prevention, headless dispatch and real Windows file replacement/rollback run in isolated fixtures. Hardware/download failure matrices remain simulations, not exhaustive security proof.
