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

## Deterministic boundary matrix

`tests/python/test_update_matrix.py` adds 649 separately discoverable cases:

| Area | Cases | Coverage |
| --- | ---: | --- |
| Valid versions | 125 | All triples from 0, 1, 9, 255 and 65535; checks exact parsed components |
| Invalid versions | 96 | 32 malformed or out-of-range components in each of three positions |
| Payload metadata | 288 | Every one of nine files against 10 invalid sizes, 14 invalid hashes and eight invalid entry shapes |
| Successful bounded reads | 80 | Five payload sizes, four fragmentation sizes, memory/file output and present/absent Content-Length |
| Interrupted or oversized reads | 60 | Five sizes and four fragment sizes against overflow, truncation and read timeout |

Stream tests check exact returned bytes, transport deadlines/public-endpoint options, response and lease cleanup, and caller ownership of output streams. They use in-memory transport fixtures, not live adapters. Schema cases mock signature verification to isolate the signed-content validator. Actual RSA verification, ZIP validation and Windows worker apply/rollback remain covered by the separate focused updater tests. Neither matrix counts nor passing tests establish that the app cannot fail or has no security flaws.

Run the added cases alone from the repository root:

```powershell
uv run --no-project --python 3.14 --with pywebview==6.2.1 --with psutil==7.2.2 --with mcp==2.3.0 python -m unittest tests.python.test_update_matrix -q
```
