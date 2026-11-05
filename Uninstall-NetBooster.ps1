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
$cli=Join-Path $install 'fetchvolt.cmd'
if((Test-Path -LiteralPath $cli -PathType Leaf) -and (Get-Content -LiteralPath $cli -First 1) -eq '@rem FetchVolt managed terminal launcher'){$files += $cli}
$files += @('LICENSE','LICENSING.md','NOTICE.md','.update-result.json','.update-lock' | ForEach-Object {Join-Path $install $_})
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
$updateResult=Join-Path $install '.update-result.json'
if((Test-Path -LiteralPath $updateResult -PathType Leaf) -and (Get-Item -LiteralPath $updateResult).Length -le 4096){
    $status=Get-Content -LiteralPath $updateResult -Raw|ConvertFrom-Json
    if($status.state -eq 'pending' -and $status.PSObject.Properties.Name -contains 'pid' -and (Get-Process -Id ([int]$status.pid) -ErrorAction SilentlyContinue)){throw 'Wait for the verified update to finish before uninstalling FetchVolt.'}
}
if (!$PSCmdlet.ShouldProcess($install, 'Remove FetchVolt for the current user')) { return }
foreach($stage in @(Get-ChildItem -LiteralPath $install -Directory -Filter '.fetchvolt-update-*' -Force -ErrorAction SilentlyContinue)){
    Assert-PlainPath $stage.FullName
    $resolved=[IO.Path]::GetFullPath($stage.FullName)
    if(!$resolved.StartsWith($install+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase) -or $stage.Name -notmatch '^\.fetchvolt-update-[A-Za-z0-9_-]+$'){throw 'Unexpected update staging path.'}
    $marker=Join-Path $resolved 'complete.marker'
    if((Test-Path -LiteralPath $marker -PathType Leaf) -and [IO.File]::ReadAllText($marker) -eq "FetchVolt update completed`n"){
        foreach($entry in @(Get-ChildItem -LiteralPath $resolved -Recurse -Force)){Assert-PlainPath $entry.FullName}
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}


if (Test-Path -LiteralPath $exe -PathType Leaf) {
    Start-Process -FilePath $exe -ArgumentList '--browser-remove' -WindowStyle Hidden -Wait
}

$entry=Get-ItemProperty -LiteralPath $registry -Name CliPath -ErrorAction SilentlyContinue
if($entry -and $entry.CliPath -eq $install){
 $key=[Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Environment',$true)
 try{if($key -and $key.GetValueNames() -contains 'Path'){$kind=$key.GetValueKind('Path');$raw=[string]$key.GetValue('Path','',[Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames);$parts=@($raw -split ';'|Where-Object {$_ -ne $install});$key.SetValue('Path',($parts-join ';'),$kind)}}finally{if($key){$key.Dispose()}}
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
