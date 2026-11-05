#Requires -Version 7.0
[CmdletBinding(SupportsShouldProcess)]
param([switch]$BrowserExtension, [switch]$SkipBrowserPrompt)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$local = [Environment]::GetFolderPath('LocalApplicationData')
$programs = [Environment]::GetFolderPath('Programs')
$install = Join-Path $local 'Programs\Net Booster'
$exe = Join-Path $install 'Net Booster.exe'
$uninstall = Join-Path $install 'Uninstall-NetBooster.ps1'
$shortcut = Join-Path $programs 'FetchVolt.lnk'
$legacyShortcuts = @(
    (Join-Path $programs 'PortFlock.lnk')
    (Join-Path $programs 'Net Booster.lnk')
    (Join-Path $programs 'PortWeave.lnk')
)
$registry = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\NetBooster'
$powerShell = Join-Path $PSHOME 'pwsh.exe'
$payload = [ordered]@{
    'FetchVolt.exe' = '1228414A68AF250A5A2741F441CF1670EEE0AE36DC15D9D076DA19B783F46BD8'
    'Uninstall-NetBooster.ps1' = '6140192EAD8489BF3E4A7CA7037022217882AF70CE1A925053BAEC031508A9B2'
}

function Assert-PlainPath([string]$Path) {
    for ($item = $Path; $item; $item = Split-Path -Parent $item) {
        $entry = Get-Item -LiteralPath $item -Force -ErrorAction SilentlyContinue
        if ($entry -and ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw "Refusing to use a linked path: $item"
        }
    }
}

foreach ($file in (@($exe, $uninstall, $shortcut) + $legacyShortcuts)) {
    Assert-PlainPath $file
    if (Test-Path -LiteralPath $file -PathType Container) { throw "Expected a file: $file" }
}
foreach ($name in $payload.Keys) {
    $source = Join-Path $PSScriptRoot $name
    Assert-PlainPath $source
    if ((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash -ne $payload[$name]) {
        throw "SHA-256 verification failed for $name."
    }
}
if (Get-Process -Name 'Net Booster' -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $exe }) {
    throw 'Close the installed copy of FetchVolt before updating it.'
}
if (!$PSCmdlet.ShouldProcess($install, 'Install FetchVolt for the current user')) { return }

$null = [IO.Directory]::CreateDirectory($install)
$null = [IO.Directory]::CreateDirectory($programs)
$staged = @{}
$temporaryShortcut = Join-Path $programs ('.NetBooster-' + [guid]::NewGuid() + '.lnk')
try {
    foreach ($name in $payload.Keys) {
        $stage = Join-Path $install ('.NetBooster-' + [guid]::NewGuid() + '.tmp')
        [IO.File]::Copy((Join-Path $PSScriptRoot $name), $stage)
        $staged[$name] = $stage
        if ((Get-FileHash -LiteralPath $stage -Algorithm SHA256).Hash -ne $payload[$name]) {
            throw "Staged payload verification failed for $name."
        }
    }

    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut($temporaryShortcut)
    $link.TargetPath = $exe
    $link.WorkingDirectory = $install
    $link.Description = 'FetchVolt downloader and network monitor'
    $link.Save()

    foreach ($name in $payload.Keys) {
        $destination = if ($name -eq 'FetchVolt.exe') { $exe } else { Join-Path $install $name }
        [IO.File]::Move($staged[$name], $destination, $true)
    }
    [IO.File]::Move($temporaryShortcut, $shortcut, $true)
    foreach ($legacyShortcut in $legacyShortcuts) {
        if ([IO.File]::Exists($legacyShortcut) -and $shell.CreateShortcut($legacyShortcut).TargetPath -eq $exe) {
            [IO.File]::Delete($legacyShortcut)
        }
    }

    $null = New-Item -Path $registry -Force
    $null = New-ItemProperty -LiteralPath $registry -Name DisplayName -Value 'FetchVolt' -PropertyType String -Force
    $null = New-ItemProperty -LiteralPath $registry -Name InstallLocation -Value $install -PropertyType String -Force
    $null = New-ItemProperty -LiteralPath $registry -Name DisplayIcon -Value $exe -PropertyType String -Force
    $uninstallCommand = '"{0}" -NoProfile -File "{1}"' -f $powerShell, $uninstall
    $null = New-ItemProperty -LiteralPath $registry -Name UninstallString -Value $uninstallCommand -PropertyType String -Force
} finally {
    foreach ($file in @($staged.Values) + $temporaryShortcut) {
        [IO.File]::Delete($file)
    }
}
Write-Host "FetchVolt installed in $install. Open it from the Start menu."
$offerBrowser = $BrowserExtension.IsPresent
if (!$offerBrowser -and !$SkipBrowserPrompt -and [Environment]::UserInteractive) {
    Add-Type -AssemblyName System.Windows.Forms
    $choice = [Windows.Forms.MessageBox]::Show(
        'Set up the optional FetchVolt browser extension for Edge, Chrome, or Firefox? Your browser will ask you to approve loading it. Automatic download handoff starts off.',
        'FetchVolt browser extension', [Windows.Forms.MessageBoxButtons]::YesNo,
        [Windows.Forms.MessageBoxIcon]::Question, [Windows.Forms.MessageBoxDefaultButton]::Button2)
    $offerBrowser = $choice -eq [Windows.Forms.DialogResult]::Yes
}
if ($offerBrowser) {
    Start-Process -FilePath $exe -ArgumentList '--browser-setup' -WindowStyle Hidden -Wait
}
