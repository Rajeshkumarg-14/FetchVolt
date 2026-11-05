# Native release builds

`Build-Native.ps1` pins Nuitka 4.3.4, pywebview 6.2.1, psutil 7.2.2 and MCP 2.3.0. Build output and compiler caches live on P:. The build uses four jobs, low-memory choices, no LTO and a portable Zig compiler because this laptop's MSVC installation lacks its Windows SDK.

The onefile build compiles application modules to native machine code and includes a local React bundle, fonts and the browser extension. MCP runs in the same executable with `--mcp-server`; it no longer needs the app to export Python helper sources. No anti-debugging traps, security-tool bypasses, misleading instructions for AI tools or claims of irreversible binaries are part of this workflow.

Native compilation increases the work needed to inspect implementation details. It does not make local code, constants or frontend assets secret, prevent reverse engineering or guarantee confusing an AI. Runtime safety comes from explicit validation, permissions, endpoint restrictions, TLS, file integrity, Defender and Windows security boundaries.

Before publishing, verify the actual compiled GUI, profile saving, clipboard JSON contents, native messaging and MCP stdio modes. Download a benign publisher-provided test file and compare its hash. Scan the release binary with Defender. Then use `Package-Release.py` in the pinned build environment to create the setup ZIP, full third-party notices and checksums. The compiler output is not a released artifact until these checks pass.

The owner has not selected a software license. Nuitka's separate license and runtime exception, font licenses and application dependency notices must be retained without representing them as FetchVolt's own license. Code signing remains a separate publishing task; unsigned previews must say so.
