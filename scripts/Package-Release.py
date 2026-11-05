"""Assemble the Windows ZIP and publishable checksums from a verified binary.

Run in the pinned build environment, after packaged runtime verification.
This tool creates local artifacts only; it does not upload or change releases.
"""
import argparse
import hashlib
import html
import importlib.metadata as metadata
import json
from pathlib import Path
import re
import sysconfig
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = '2.5.0'
RUNTIME_PACKAGES = (
    'Nuitka', 'pywebview', 'psutil', 'mcp', 'pythonnet', 'clr_loader', 'cffi', 'pycparser', 'bottle',
    'proxy_tools', 'typing_extensions', 'anyio', 'pydantic', 'pydantic_core', 'annotated_types',
    'typing_inspection', 'httpx', 'httpcore', 'httpx_sse', 'starlette', 'sse_starlette', 'uvicorn',
    'websockets', 'attrs', 'jsonschema', 'referencing', 'rpds_py', 'jsonschema_specifications',
    'certifi', 'idna', 'sniffio', 'h11', 'pyjwt', 'python_multipart', 'packaging', 'click',
)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def notices():
    bundle = (ROOT / 'ui/dist/index.html').read_text('utf-8')
    match = re.search(r'<template id="third-party-notices"><pre>(.*?)</pre></template>', bundle, re.S)
    if not match:
        raise ValueError('Build the UI with embedded third-party notices first.')
    blocks = [html.unescape(match[1])]
    for name in RUNTIME_PACKAGES:
        try:
            distribution = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue
        for file in distribution.files or ():
            path = str(file).replace('\\', '/')
            if '.dist-info/' not in path or not re.match(r'^(licen[sc]e|copying|notice)', file.name, re.I):
                continue
            content = distribution.locate_file(file).read_text('utf-8', errors='replace')
            blocks.append(f'{name} {distribution.version}: {file.name}\n{content}')
    python_license = Path(sysconfig.get_path('stdlib')).parent / 'LICENSE.txt'
    if python_license.is_file():
        blocks.append('CPython license and history\n' + python_license.read_text('utf-8', errors='replace'))
    for license_file in Path('P:/.cache/nuitka/downloads/pip').glob('*/Lib/site-packages/ziglang/LICENSE'):
        blocks.append('Zig compiler/runtime notices\n' + license_file.read_text('utf-8', errors='replace'))
    if not any('LICENSE-RUNTIME' in block for block in blocks):
        raise ValueError('Nuitka runtime exception notice is missing. Run in the pinned build environment.')
    return '\n\n'.join(blocks).encode('utf-8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--exe', type=Path, required=True)
    args = parser.parse_args()
    payload = args.exe.read_bytes()
    if not payload.startswith(b'MZ'):
        raise ValueError('Expected a verified Windows executable.')
    uninstall = (ROOT / 'Uninstall-NetBooster.ps1').read_bytes()
    installer_path = ROOT / 'Install-NetBooster.ps1'
    installer = installer_path.read_text('utf-8')
    installer = re.sub(r"('FetchVolt.exe' = ')[A-F0-9]+", lambda m: m[1] + digest(payload).upper(), installer)
    installer = re.sub(r"('Uninstall-NetBooster.ps1' = ')[A-F0-9]+", lambda m: m[1] + digest(uninstall).upper(), installer)
    installer_path.write_text(installer, encoding='utf-8', newline='\n')
    files = {'FetchVolt.exe': payload, 'Install-NetBooster.ps1': installer_path.read_bytes(),
             'Uninstall-NetBooster.ps1': uninstall, 'NOTICE.md': (ROOT / 'NOTICE.md').read_bytes(),
             'LICENSE': (ROOT / 'LICENSE').read_bytes(), 'LICENSING.md': (ROOT / 'LICENSING.md').read_bytes(),
             'THIRD-PARTY-NOTICES.txt': notices()}
    files['INSTALL.txt'] = (
        f'FetchVolt {VERSION} for Windows 11 x64\nCopyright 2026 Rajesh Kumar G\n\n'
        'Verify the ZIP against the release SHA256SUMS.txt before use.\n'
        'Extract every file into the same folder. FetchVolt.exe can run directly.\n'
        'For per-user installation, open PowerShell 7 in this folder and run:\n'
        '  .\\Install-NetBooster.ps1\n'
        'Follow your Windows execution policy. Do not disable Windows security.\n'
        'The installer offers optional browser extension setup. Browser approval is required.\n'
        'You can set it up later from Settings > Browser extension.\n'
        'This preview is unsigned. Project-authored material is PolyForm Noncommercial 1.0.0.\n'
        'Read LICENSE, LICENSING.md, NOTICE.md and THIRD-PARTY-NOTICES.txt.\n\n'
        'MCP: AI & MCP in the app provides configuration for the same executable.\n'
        'The installed MCP server needs no exported Python source or uv installation.\n'
        'Close the app before updating. Use Installed apps to uninstall.\n'
        'Remove Browser Link through each browser separately.\n'
        'Contact: https://github.com/Rajeshkumarg-14/fetchvolt-site/issues\n'
    ).encode('utf-8')
    files['PAYLOAD-SHA256.txt'] = ''.join(f'{digest(data)}  {name}\n' for name, data in files.items()).encode('ascii')
    folder = ROOT / 'releases'
    folder.mkdir(exist_ok=True)
    name = f'FetchVolt-Setup-{VERSION}.zip'
    target = folder / name
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for filename, data in files.items():
            archive.writestr(filename, data)
    checksum = digest(target.read_bytes())
    (folder / 'SHA256SUMS.txt').write_text(f'{checksum}  {name}\n{digest(payload)}  FetchVolt.exe\n', 'ascii')
    release = {'available': True, 'version': VERSION, 'sha256': checksum, 'bytes': target.stat().st_size,
               'url': f'https://github.com/Rajeshkumarg-14/fetchvolt-site/releases/download/v{VERSION}/{name}'}
    (folder / 'release.json').write_text(json.dumps(release, indent=2), 'utf-8')
    print(json.dumps({'zip': str(target), 'bytes': target.stat().st_size, 'sha256': checksum}))


if __name__ == '__main__':
    main()
