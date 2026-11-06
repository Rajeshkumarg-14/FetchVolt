#Requires -Version 7.0
[CmdletBinding()]
param([string]$OutputDirectory = 'P:\.cache\portflock-native-build', [switch]$CleanCache)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if (!(Test-Path P:\)) { throw 'The Dev Drive is not mounted.' }
Push-Location (Split-Path -Parent $PSScriptRoot)
try {
    $env:NUITKA_CACHE_DIR = 'P:\.cache\nuitka'
    $null = New-Item -ItemType Directory -Path $OutputDirectory -Force
    npm run build --prefix ui
    if ($LASTEXITCODE) { throw 'Frontend build failed.' }
    $data = @('--include-data-files=ui/dist/index.html=ui/dist/index.html','--include-data-files=scripts/Apply-Update.ps1=scripts/Apply-Update.ps1')
    foreach ($name in @('LICENSE','LICENSING.md','NOTICE.md')) { $data += "--include-data-files=${name}=${name}" }
    foreach ($name in @('manifest.json','background.js','policy.js','popup.html','popup.js','popup.css','icon.png')) {
        $data += "--include-data-files=extension/${name}=extension/${name}"
    }
    $compiler = @('--zig')
    # A stale object cache can link old compiled code into a new build; use -CleanCache when behavior does not match source.
    if ($CleanCache) { $compiler += '--clean-cache=all' }
    uv run --no-project --python 3.14 --with Nuitka==4.3.4 --with pywebview==6.2.1 --with psutil==7.2.2 --with mcp==2.3.0 python -m nuitka `
        --mode=onefile @compiler --jobs=4 --lto=no --low-memory --enable-plugin=tk-inter --assume-yes-for-downloads `
        --include-package=mcp --include-module=browser_setup --include-distribution-metadata=mcp @data `
        --windows-console-mode=disable --windows-icon-from-ico=branding/fetchvolt.ico `
        '--company-name=Rajesh Kumar G' --product-name=FetchVolt --file-version=2.6.1.0 --product-version=2.6.1.0 `
        '--copyright=Copyright 2026 Rajesh Kumar G' --output-filename=FetchVolt.exe "--output-dir=$OutputDirectory" app/desktop.py
    if ($LASTEXITCODE) { throw 'Native compilation failed.' }
    Write-Host "Native build available at $OutputDirectory\FetchVolt.exe. Verify it before replacing the release payload."
} finally { Pop-Location }
