# Real-world QA: FetchVolt 2.6.0

Run date: 5 November 2026. Baseline source: `29690f5`; installed executable reports 2.6.0. Added fixture tests are local changes and are not part of that published binary.

## Confirmed responsiveness defect — cancellation during initial headers

Priority: medium. Cancelling a transfer while its initial HTTPS response headers are pending does not immediately interrupt that request. A real loopback TLS server delayed headers for 0.8 seconds; cancellation took **0.802 seconds** to finish. No destination file was published.

`app/net_booster.py` calls `fetch_response` before `live_links.attach(conn)` for the initial probe. `request` internally creates its response lease, but LiveLinks cannot expire it while `getresponse()` is waiting. The default header deadline is 30 seconds; connection/TLS establishment has its own timeout. The 0.8-second observation establishes the waiting behavior, not a measured 30-second stall. Range requests have a similar interval before their lease is attached. The desktop waits up to 20 seconds for workers on save-and-close; therefore cancellation latency can outlast that grace period under a slow initial response. A native window-close hang under that condition has **not** been reproduced in this run.

`test_cancel_pending_headers_returns_within_250ms` reproduces the defect and is deliberately marked `expectedFailure`. It must be removed from expected-failure status once fixed. Other bounded-timeout checks pass. This issue is **not fixed** in the source or installed executable by this QA task.

Recommended fix: give transfer cancellation access to the lease while connection/header work is pending, release that registration on every failure and redirect, and retain independent deadlines. Verify cancellation before connection, during TLS/headers, and while an adapter is being replaced. Rebuild and test the installed executable before claiming the fix is shipped.

## Executed transfer scenarios

`tests/python/test_real_network.py` runs a real HTTPS server bound only to 127.0.0.1. It creates an ephemeral certificate in a temporary directory with .NET; the client trusts that certificate only inside the test process. System certificate stores, Windows security settings and production TLS configuration are untouched. Requires PowerShell 7 for fixture creation.

The 24 successful scenarios cover:

- Single-stream and seven concurrent logical paths; exact SHA-256 and byte accounting.
- Server range fallback and HTTPS redirects.
- Mid-response socket disconnect with retry on another logical path.
- Truncated body preserving an existing destination.
- Changed ETag and wrong Content-Range rejection.
- Stalled response headers and body deadlines.
- Pause/resume during active socket reads and adding a logical path during a transfer.
- Save-and-close recovery that requests only missing verified ranges.
- Intentional cancellation removing staged data and checkpoints.
- Two concurrent files.
- Abrupt child-process termination after a durable checkpoint, followed by recovery.
- An untrusted TLS certificate and incorrect expected SHA-256 being rejected.
- Destination collision preserving the original file.
- Injected low disk space and scanner unavailability blocking publication.
- Twenty repeated 1 MiB transfers with Windows handle/thread counts and RSS bounds.
- Desktop save-close controller draining a real active transfer thread, preserving its checkpoint. The window object is a fixture; this is not a compiled GUI end-to-end download test.
- A real Microsoft Defender scan of the harmless socket-downloaded payload, with Mark of the Web retained.

The additional initial-header cancellation scenario is the documented expected failure above. Most cases substitute a scanner fixture to isolate transport behavior; the explicitly enabled Defender case calls the real scanner. No malware sample is downloaded or executed. Disk exhaustion is injected rather than filling the user's drive. All seven logical paths use Windows interface index 0 and the same loopback route; they do not represent seven physical adapters.

The resource test allows at most 12 additional process handles, two threads and 48 MiB of RSS growth after the repeated transfers and collection. It passed those bounds; this short run is not a long-duration leak proof. Recovery, output and certificate files are confined to disposable test directories. Existing user downloads and recovery records are not changed.

## Installed executable checks

The actual installed `Net Booster.exe` passed:

| Command | Observed result | Elapsed |
| --- | --- | ---: |
| `--version` | FetchVolt 2.6.0 | 1.80 s |
| `connections` | Valid JSON; one connected adapter | 9.80 s |
| `update --check --json` | Current/latest 2.6.0; available false | 1.99 s |

The update check contacted the published HTTPS metadata endpoint and used the installed publisher-signature validator. It did not apply an update. Adapter discovery latency is recorded as an observation, not a demonstrated GUI freeze.

## Reproduction

From the FetchVolt repository root:

```powershell
$env:FETCHVOLT_REAL_DEFENDER_TEST='1'
uv run --no-project --python 3.14 --with pywebview==6.2.1 --with psutil==7.2.2 --with mcp==2.3.0 python -m unittest tests.python.test_real_network -v
```

Without the environment opt-in, the real Defender test is skipped. The header-cancellation expected failure remains visible in both modes.

## Limits

This is functional fault injection with a focused source review, not an exhaustive security audit. It does not establish absence of vulnerabilities. Not exercised: physical USB/Wi-Fi removal and reconnection, seven real uplinks, metered/carrier networks, overnight transfers, sleep/hibernate, actual disk-full events, malware-detection efficacy, compiled GUI download interactions, or installing a newer published update over 2.6.0. Only one connected adapter was available during this run. No network adapters, browser profiles, system policies or production release assets were modified.

Final regression result: **2,052 Python tests run: 2,051 successful, one expected failure** (the confirmed initial-header cancellation delay), with the real Defender case enabled and no skips. All **nine JavaScript tests** passed. The 25 new integration cases account for 24 successful scenarios and that one expected failure. Test/report changes are local and have not been committed or published.

## Update, 6 November 2026 (2.6.1 work)

- `tests/python/test_real_network.py` is now committed. Its seven-path scenario runs with one stream per adapter, because the engine now opens up to four parallel range streams per adapter and a tiny fixture file would otherwise be drained by the first adapters.
- A different cancellation defect was found and fixed: the single-stream fallback used for servers that send no ETag or Last-Modified dropped the live link, so Cancel, Pause and save-and-close could not reach that transfer until the whole file finished. It is covered by `test_live_links.py`. The initial-header cancellation delay described above is **still not fixed**.
- Test count after these changes: 2,116 Python tests pass. The numbers in the previous section describe the 2.6.0 baseline.
- Not verified here: the speed gain of multiple streams per adapter on a fast, high-latency link, and a real uninstall of the installed app.
