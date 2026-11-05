#Requires -Version 7.0
[CmdletBinding(SupportsShouldProcess)]
param([switch]$RemoveHistory)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$local = [Environment]::GetFolderPath('LocalApplicationData')
$programs = [Environment]::GetFolderPath('Programs')
$install = Join-Path $local 'Programs\Net Booster'
$data = Join-Path $local 'Net Booster'
$exe = Join-Path $install 'Net Booster.exe'
$shortcut = Join-Path $programs 'FetchVolt.lnk'
$registry = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\NetBooster'

function Assert-PlainPath([string]$Path) {
    for ($item = $Path; $item; $item = Split-Path -Parent $item) {
        $entry = Get-Item -LiteralPath $item -Force -ErrorAction SilentlyContinue
        if ($entry -and ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw "Refusing to use a linked path: $item"
        }
    }
}

$files = @($exe, (Join-Path $install 'Uninstall-NetBooster.ps1'), $shortcut)
if ($RemoveHistory) {
    $files += @('history.sqlite3', 'history.sqlite3-journal', 'history.sqlite3-wal', 'history.sqlite3-shm' |
        ForEach-Object { Join-Path $data $_ })
}
foreach ($file in $files) {
    Assert-PlainPath $file
    if (Test-Path -LiteralPath $file -PathType Container) { throw "Expected a file: $file" }
}
$running = Get-Process -Name 'Net Booster','PortWeave','PortFlock','FetchVolt' -ErrorAction SilentlyContinue
if ($running | Where-Object { $_.Path -eq $exe -or $RemoveHistory }) {
    throw 'Close FetchVolt before uninstalling.'
}
if (!$PSCmdlet.ShouldProcess($install, 'Remove FetchVolt for the current user')) { return }

if (Test-Path -LiteralPath $exe -PathType Leaf) {
    Start-Process -FilePath $exe -ArgumentList '--browser-remove' -WindowStyle Hidden -Wait
}

if (Test-Path -LiteralPath $registry) {
    Remove-Item -LiteralPath $registry
}
$startupKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$expectedStartup = '"{0}" --startup' -f $exe
$startupEntry = Get-ItemProperty -LiteralPath $startupKey -Name 'PortFlock' -ErrorAction SilentlyContinue
if ($startupEntry -and $startupEntry.PortFlock -eq $expectedStartup) {
    Remove-ItemProperty -LiteralPath $startupKey -Name 'PortFlock'
}
foreach ($file in $files) {
    if (Test-Path -LiteralPath $file -PathType Leaf) { [IO.File]::Delete($file) }
}
foreach ($folder in @($install, $(if ($RemoveHistory) { $data }))) {
    if ($folder -and [IO.Directory]::Exists($folder) -and
        ![IO.Directory]::EnumerateFileSystemEntries($folder).GetEnumerator().MoveNext()) {
        [IO.Directory]::Delete($folder)
    }
}
Write-Host 'FetchVolt was removed for this user.'
