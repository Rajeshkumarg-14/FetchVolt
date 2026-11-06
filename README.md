# FetchVolt

<img src="branding/fetchvolt.svg" alt="FetchVolt logo" width="120">

**One download. Many connections.**

FetchVolt is a Windows 11 desktop downloader and network monitor. Open **FetchVolt.exe** to use it. Build the executable from the source in this repository using the instructions below. The native build bundles its runtime and the React interface. It uses Microsoft Edge WebView2 Runtime, which must be available on Windows.

## License

FetchVolt is source-available under [PolyForm Noncommercial 1.0.0](LICENSE). You may fork, improve and redistribute it for permitted purposes, with license and required notices preserved. Commercial use is restricted, with the standard license's explicit organizational exceptions. This is not an OSI-approved open-source license. See [LICENSING.md](LICENSING.md) and [CONTRIBUTING.md](CONTRIBUTING.md); third-party components retain their own terms.

## Install and uninstall

Keep **Install-NetBooster.ps1**, **Uninstall-NetBooster.ps1**, and **FetchVolt.exe** together. From that folder, run in PowerShell 7 as your normal user.

```powershell
.\Install-NetBooster.ps1 -WhatIf
.\Install-NetBooster.ps1
```

The installer checks the bundled executable and uninstall script against embedded SHA-256 hashes, then checks the staged copies before installing. It installs under **%LOCALAPPDATA%\Programs\Net Booster**, adds a Start menu shortcut and registers with **Settings → Apps → Installed apps**. To update an existing installation, close FetchVolt and keep the new executable, installer and uninstaller together in one folder. Run the new `Install-NetBooster.ps1` from PowerShell 7. It replaces the installed files in place and preserves your history and appearance settings. If you run the executable directly without installing it, close it before replacing that copy.

Use the **Uninstall** action under Installed apps, or run the matching script in PowerShell 7. Uninstall keeps your downloads and local history by default. Add **-RemoveHistory** only if you want to delete the app’s database.

```powershell
.\Uninstall-NetBooster.ps1
.\Uninstall-NetBooster.ps1 -RemoveHistory
```

Both scripts honor the active PowerShell execution policy. This local build and its scripts are unsigned. Where policy requires a trusted publisher signature, use an organization-approved signed release. The embedded hashes detect changed payloads when the installer itself comes from a trusted copy.

## Download a file

1. Connect the networks you want to use. Wi-Fi, Ethernet, Bluetooth PAN and up to four USB-tethered phones can be selected together for one file. Each phone needs its own active Windows adapter. For Bluetooth tethering, pair a phone with Windows and join its Personal Area Network (PAN). For USB tethering, connect a phone with a data-capable cable and enable USB tethering or Personal Hotspot. An iPhone requires Apple Devices or iTunes on Windows.
2. Paste a direct HTTPS file URL in the **Downloads** view.
3. Click one to seven adapters in the **Connections** list. The list shows active adapters with an IPv4 default gateway. The first selected adapter in list order checks the file. If a newly connected adapter is missing, click **Refresh adapters**.
4. Set **Priority**, click **Add download**, and choose where to save the file. Select a file under **Transfers** to see its progress and per-adapter contribution in the animated tree.

The app uses separate IPv4 connections for file chunks. The server must honor byte ranges and supply a strong ETag for a multi-link transfer. Otherwise, the app uses one adapter for a single transfer. If a link fails while fetching chunks, the app retries its missing chunk over another selected link. A file that changes mid-transfer is rejected. Downloads are written to a temporary file next to the destination and moved into place after completion.

To compare speeds, download the same file with only Wi-Fi selected, then repeat with additional adapters selected. Wi-Fi and Bluetooth from the same phone share the phone’s upstream connection, which can limit any gain. Wi-Fi and Ethernet on the same router likewise share that router’s plan speed, so only adapters with separate uplinks, such as a USB-tethered phone on mobile data, add bandwidth. Each selected connection runs up to four parallel streams, which lets fast, high-latency links such as mobile data fill their speed. The app verifies HTTPS certificates, rejects redirects to HTTP, and requires Microsoft Defender Antivirus to complete a clean scan before making the file available. A detection, failed scan, or 5-minute scan timeout blocks publication. Scanning requires receiving the bytes into a temporary file first. Antivirus cannot guarantee detection of every threat. It marks completed files with Windows Mark of the Web before publishing them. Save to a filesystem that supports named streams, such as NTFS. Browser cookies and authenticated browser sessions are outside the app’s direct-download flow.

Downloads are limited to 128 GiB per file, use fixed-size read buffers, and have network deadlines to bound stalled transfers. A completed file replaces the destination only after integrity checks, the Defender scan, and Mark of the Web tagging succeed. If Defender is disabled or unavailable, the app cannot publish the file.

## Simultaneous downloads and priority

Up to two files download at once. Both share the bandwidth of whichever adapters they have in common. Additional files wait in memory and start in High, Normal, then Low priority order. Files with the same priority start in the order they were added. Priority can be changed for waiting files and does not interrupt or throttle active transfers. For a running range-capable download, select the file under **Transfers**, update the adapter checkboxes, and click **Apply to active download**. Newly selected adapters can pick up remaining chunks. A deselected adapter finishes its in-flight chunk. Single-stream downloads keep their original connection.

Use **Pause**, **Resume**, or **Cancel** beside a running file. Pausing is available when the server supplies byte ranges and a strong ETag. Range-capable downloads keep completed chunks and retry interrupted chunks after a connection failure. **Reconnecting** means the app is waiting to retry the remaining work. Paused jobs keep their worker slot and temporary file until resumed or cancelled.

After an unexpected app or Windows shutdown, range-capable downloads appear as **Saved progress**. Select available adapters and choose **Resume saved download**. FetchVolt verifies the saved chunks against their stored SHA-256 digests and checks that the server still provides the same file identifier and length. Interrupted chunks are fetched again. If the server changes the file, recovery is blocked.

Recovery records under **%LOCALAPPDATA%\Net Booster\transfers** contain the source URL, save path, file identifier and chunk hashes. These records can include private query tokens from your link, so treat them as private user data. Cancelling or discarding a transfer deletes its staging file and recovery record. Servers that return only a single stream support Cancel but cannot safely pause and resume.

You can remove a waiting file from Transfers. Closing the window while transfers exist offers **Save progress and close**, **Cancel downloads and close**, and **Keep open**. Saved byte ranges are recoverable after reopening. Single-stream downloads cannot retain resumable ranges. Completed outcomes are retained in History. Waiting files that have not started are session-only.

## Turbo

Enable **Turbo** on a waiting or running file to give it all available internet adapters, up to seven. Other range-capable downloads are held while it runs. Turning Turbo off, cancelling the file, or finishing it restores normal scheduling with up to two active transfers. Newly connected adapters join the Turbo file when Windows reports them. A server that does not support byte ranges cannot combine connections.

## Settings

Open **Settings** to customize your local display name, theme, solid/glass surfaces, speed units, transfer tree layout and animation preference. Your profile name and initials are separate from the author copyright. Preferences are saved for your Windows user. The Storage panel shows used, free, and total space on local fixed drives.

- **Auto** uses a horizontal tree in wide windows and a vertical tree in narrow windows. Select **Vertical** or **Horizontal** to keep that layout for downloads with multiple connections.
- A single connection uses a compact route. Its transfer progress appears once you add a download.
- Pulses indicate bytes recently received by that download. Branches fade when their adapters become unavailable.

## Network and History

- **Network** samples native Windows traffic counters about once per second. Adapter discovery refreshes separately. Receive and send rates are averages since the previous sample in decimal Mbps. Traffic includes all apps. The MiB columns show cumulative Windows counters, which can reset when an adapter restarts. The link rate measures the local connection. A dash indicates that a rate or counter is unavailable.
- **History** shows the latest 500 stored events, including the initial adapter states when the app opens, subsequent changes while it runs, and saved or failed downloads. Polling can miss brief transitions. Windows adapter status describes the local interface and does not confirm internet reachability.
- History is stored in **%LOCALAPPDATA%\Net Booster\history.sqlite3**. It contains local timestamps, adapter names and IPv4 addresses, saved filenames, outcomes, and transfer summaries. Source URLs are not recorded. To clear the saved history, close the app and delete the database.

The **Launch at Windows sign-in** option registers FetchVolt for your current Windows account and starts its window minimized. It is available in the installed executable and is off by default. You can disable it in Settings or Windows Startup Apps.

## MCP for AI tools

FetchVolt includes a local stdio MCP server in the same executable. Open **AI & MCP**, choose an existing local output folder and copy the configuration into your compatible MCP host. The installed server does not require uv, Python installation or exported helper source files. The copy action supports the Windows WebView clipboard and prepares older configurations if needed.

```powershell
& "$env:LOCALAPPDATA/Programs/Net Booster/Net Booster.exe" --mcp-server --root "P:/Downloads/FetchVolt-test"
```

| Tool | Use |
| --- | --- |
| `list_connections` | Get the IDs of active adapters with an IPv4 gateway. |
| `start_download` | Pass the public HTTPS URL, a relative destination such as `assets/file.zip`, one to seven adapter IDs, and optionally a SHA-256 hash. Subfolders must already exist. |
| `download_status` | Poll the returned ID. A saved result includes the full path, ready for the agent to use. |

The service blocks private addresses, path traversal, linked subfolders, and overwrites. Files appear in the requested folder only after the transfer, optional checksum, Windows Defender scan, and Mark of the Web tagging succeed. Keep the MCP session running until the job finishes. Each MCP server session can run two downloads concurrently and keeps the latest 20 outcomes in memory.

## Browser extension and website

The installer offers optional browser setup. You can also open it in Settings. Loading the extension requires browser approval, and automatic handoff starts off. Supported public HTTPS files enter the app's durable inbox before the browser transfer is cancelled. On native-connection failure the extension attempts browser resume. Login sessions, cookies and POST payloads are not copied. See [Browser Link](docs/BROWSER-INTEGRATION.md) for the handoff, scope and security limits.

Edge and Chrome use the Chromium extension. Other Chromium browsers depend on compatibility; Firefox is a development preview pending signing. The extension exposes no HTTP listener or MCP server. The app's existing folder-scoped MCP server serves AI clients separately.

The static website and public release assets belong to `Rajeshkumarg-14/fetchvolt-site`; the reviewed, noncommercial-licensed application source is published at [Rajeshkumarg-14/FetchVolt](https://github.com/Rajeshkumarg-14/FetchVolt). The website has self-hosted fonts, interactive network illustration, bounded intro/reveal motion and privacy/terms/security notices. Contact is GitHub Issues. Project-authored material uses PolyForm Noncommercial 1.0.0; describe FetchVolt as source-available, with noncommercial terms.

## Diagnostic logs

Open **%LOCALAPPDATA%\Net Booster\logs** in File Explorer. FetchVolt writes a separate log for each session and records transfer state, Defender results, adapter-monitor failures, and error codes. Diagnostic logs omit URLs, filenames, local IP addresses, and raw exception messages. The separate History view still records its usual download and adapter details.

Each session rotates at 1 MiB and keeps two backups. Startup keeps the most recent 12 log files when Windows allows them to be removed. Closing FetchVolt and deleting the logs folder clears diagnostics without affecting download history.

Range workers stream directly into their assigned offsets using 64 KiB reads. A retried range rewrites its own bytes. A failed or incomplete transfer never replaces the selected destination.

## Develop and verify

Run these from the project directory on the P: drive with Node.js, uv, and Python 3.14.

```powershell
Push-Location ui
npm ci
npm run build
Pop-Location
uv run --no-project --python 3.14 --with pywebview==6.2.1 --with psutil==7.2.2 --with mcp==2.3.0 python -m unittest discover -s tests -t . -v
uv run --no-project --python 3.14 --with pywebview==6.2.1 --with psutil==7.2.2 python app/desktop.py
```

Rebuild the native standalone executable from the same directory. Build dependencies are pinned in the script. The output is kept in `P:\.cache\portflock-native-build` until packaged verification succeeds.

```powershell
.\scripts\Build-Native.ps1
```

See [native packaging](docs/NATIVE-PACKAGING.md) for compiler and release validation limits. Native compilation raises inspection effort; it cannot prevent reverse engineering or reliably confuse an AI. Do not rely on code secrecy for security.

The React bundle is embedded as local HTML with a script hash policy. The desktop bridge accepts adapter selections, preferences, and queue actions. File destinations come from the native Windows save dialog.

After rebuilding or signing the payload, update the two SHA-256 values in **Install-NetBooster.ps1** using `Get-FileHash -Algorithm SHA256` on the final executable and uninstall script. If distributing a signed release, sign the installer script after updating those values.

The automated suite runs 1,270 transfer scenarios across all 127 nonempty combinations of seven connections, plus focused tests for socket deadlines, queue behavior, integrity, and Defender error handling. These are deterministic simulations unless explicitly run against real hardware. To validate the physical links, connect the intended adapters and download a large file from a server that provides a strong ETag and byte ranges. Confirm that the selected adapters report file bytes, compare the saved file hash against the publisher’s hash when available, and reopen the app to check that History retained the result.

## Credits

See [copyright and third-party notices](NOTICE.md).

Copyright © 2026 Rajesh Kumar G. [GitHub](https://github.com/Rajeshkumarg-14) · [rajeshkumarg.com](https://rajeshkumarg.com)

## Connection speed test

Network > Test your connection runs only when requested. Choose one connected IPv4 adapter. It samples three HTTPS response times and receives up to 10 MB (9.54 MiB) from Cloudflare, plus network overhead. Cloudflare receives the connection's public IP under its privacy policy. This does not run an upload test or measure combined-link capacity. A small sample can underestimate fast links; other traffic affects results. Active app downloads must be paused first. Cancellation interrupts an active response; connection/header work has bounded deadlines. Results and the five-entry successful-test history are session-only. No sample payload is written to disk, executed or published.

The implementation uses Cloudflare's documented public download endpoint (https://github.com/cloudflare/speedtest), not its JavaScript engine or branding, and does not submit a separate result report. Provider endpoint availability may change.

## Terminal commands and updates

The 2.6 installer adds a managed `fetchvolt.cmd` launcher and the installation directory to your Windows user PATH. Open a new terminal after installation. No administrator PATH change is needed.

```powershell
fetchvolt --help
fetchvolt --version
fetchvolt connections
fetchvolt update --check
fetchvolt update --check --json
fetchvolt update
```

Running `fetchvolt` without arguments opens the app. Native browser messaging and `--mcp-server` remain separate protocol modes. Unknown arguments fail without opening the GUI.

`update --check` reads a bounded, publisher-signed manifest without downloading the setup bundle. `update` installs only a newer official release into the managed per-user installation. Close the GUI first, saving supported download progress normally. Updates preserve your settings, history and recovery files. The terminal launcher waits for the update worker's result. Portable copies and source checkouts must use the verified setup bundle instead of self-replacing.

Update checks require HTTPS and an RSA-3072/SHA-256 publisher signature pinned in the app; hashes alone are not accepted as publisher authentication. Packages and every payload file are size-bounded and SHA-256 checked. Archives reject unexpected/duplicate paths and links. Microsoft Defender must scan extracted files successfully; they receive Mark of the Web. Windows execution policy and SmartScreen are not bypassed. The local PowerShell 7 worker rechecks the signed payload after the old process exits and restores originals if replacement fails before commit. Windows user-account access is a trust boundary; this is not protection against compromise of the same account or publisher key.

Version 2.5 and earlier need one normal installer upgrade to obtain the terminal launcher. Future CLI updates need no uninstall/reinstall. The app remains an unsigned preview; the update-manifest signature is separate from Windows Authenticode signing. See docs/CLI-UPDATES.md for publishing and recovery.
