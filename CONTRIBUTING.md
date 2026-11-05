# Contributing to FetchVolt

Fork the reviewed public source, create a branch, and submit a pull request explaining the problem, resulting behavior and validation. Fixes and improvements must comply with LICENSE and LICENSING.md. Do not submit credentials, private URLs, logs, downloaded files or user data.

By submitting a contribution, you offer your contribution under PolyForm Noncommercial License 1.0.0 and confirm that you have the rights needed to do so. Keep existing notices; disclose third-party code and its license. You retain ownership of your contribution. No copyright assignment is required or implied.

Use Windows 11, Python 3.14, PowerShell 7 and Node.js. Build the React frontend before opening the app. The development checkout uses a Dev Drive at P: and package caches under P:/.cache; configure an equivalent environment before running native packaging. See README.md and docs/NATIVE-PACKAGING.md for pinned dependencies and commands.

Run relevant Python/JavaScript regression tests. Never disable HTTPS verification, Windows security, endpoint restrictions, download integrity checks or required Defender scanning to make a test pass. Keep simulated failure tests separate from real hardware validation. Include focused regression tests for behavioral fixes.

For security issues, follow SECURITY.md rather than publishing sensitive details in an issue or pull request.
