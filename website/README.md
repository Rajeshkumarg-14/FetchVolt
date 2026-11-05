# FetchVolt website

Single static page for GitHub Pages, with legal sections linked by stable URL fragments. No build step, backend, external fonts, analytics or tracking cookies.

Publish the contents of this directory to the root of `Rajeshkumarg-14/fetchvolt-site`, then enable Pages on `main` from `/`. Reviewed application source is published separately at `Rajeshkumarg-14/FetchVolt` under PolyForm Noncommercial 1.0.0. Release assets belong on the public site's GitHub Releases, not in Git history.

`release.json` is updated only after a verified setup ZIP exists. It contains its version, SHA-256, byte length and exact GitHub release asset URL. The page validates this metadata before using it. GitHub Pages does not provide arbitrary response-header configuration; CSP is supplied in the HTML and is not claimed to supply frame-ancestors or server-side headers.

Run locally: `python -m http.server 19196 --bind 127.0.0.1 --directory website` from the app repository root. Browser test at desktop and mobile widths; test tree toggles, Turbo, legal anchors, download link and checksum copy.

Product typography: self-hosted Bricolage Grotesque and Manrope (SIL OFL, license files in assets). Design: native HTML/CSS, black surfaces with the existing mint/blue FetchVolt identity. Direction values: design variance 7, motion 5, density 4. Signature interaction: selectable network branches merge into one file; Turbo speeds the illustration, with a static reduced-motion alternative. The image is an actual app screenshot, not fabricated performance data.

Contact is GitHub Issues at the owner's request. The owner selected unmodified PolyForm Noncommercial 1.0.0 on 5 November 2026, including its express organizational exceptions. Use source-available terminology and preserve the owner and third-party notices.

FetchVolt redesign: black/silver and electric lime, approved by the owner. Self-hosted Bricolage Grotesque display and Manrope body fonts. The interactive network diagram is illustrative; no speed test or adapter access runs on the website. Local preview: `python -m http.server 18766 --bind 127.0.0.1 --directory website` from the private repository root.
