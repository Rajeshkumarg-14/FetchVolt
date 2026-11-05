# Copyright and third-party notices

Copyright © 2026 Rajesh Kumar G. This notice applies to the FetchVolt project code and branding authored for this project. Third-party components retain their own notices and license terms.

- **Project owner:** Rajesh Kumar G
- **GitHub:** [Rajeshkumarg-14](https://github.com/Rajeshkumarg-14)
- **Website:** [rajeshkumarg.com](https://rajeshkumarg.com)

Required Notice: Copyright 2026 Rajesh Kumar G (https://rajeshkumarg.com)

Project-authored portions are licensed under PolyForm Noncommercial License 1.0.0. See LICENSE and LICENSING.md. Third-party materials retain their separate terms.

## Frontend

- **Manrope.** The app embeds the variable font from [Google Fonts](https://github.com/google/fonts/tree/main/ofl/manrope), under the SIL Open Font License. The full license is included in the local frontend notices.
- **Website fonts.** Bricolage Grotesque and Manrope are self-hosted under their SIL Open Font Licenses, included in `website/assets`.

- **React Bits Rubber Segment.** The component was adapted from React Bits. Its original notice and MIT + Commons Clause terms are included with the source. The terms allow use as part of an application and restrict redistribution of the component itself. [License](ui/components/ReactBits-LICENSE.md)
- **React, Radix UI, Motion, Lucide, and supporting packages.** The lockfile identifies the versions. The frontend build embeds the full license and notice files found for packages that contribute code to the bundle. [Package lockfile](ui/package-lock.json)
- **react-remove-scroll-bar 2.3.8.** The npm package omits its license file and declares MIT. The repository includes the MIT notice from upstream. [Upstream license](https://github.com/theKashey/react-remove-scroll-bar/blob/7301c160fda44cb8cf2b9fdfde61efad35736196/LICENSE)

## Windows build

- Native live traffic counters use [psutil](https://github.com/giampaolo/psutil/blob/master/LICENSE).
- The Windows package uses [CPython](https://docs.python.org/3/license.html), [pywebview](https://github.com/r0x0r/pywebview/blob/master/LICENSE), and [Nuitka](https://nuitka.net/pages/licensing.html), including its runtime exception. The setup bundle includes their notices and Zig compiler/runtime notices. Legacy PyInstaller builds retain their separate bootloader license.
- [Microsoft Edge WebView2](https://developer.microsoft.com/microsoft-edge/webview2/) and Microsoft Defender Antivirus are Windows components used at runtime.
