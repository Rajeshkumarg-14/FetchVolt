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
    'FetchVolt.exe' = '6E7C3EFC2E0BD054A86264FBE5F739D47F867A9F37576FF7CE907B0165929F42'
    'Uninstall-NetBooster.ps1' = '6BC2BAD9429656423464856A88D37F08DAB7CEA500FC95B6912D0301765454CE'
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
$cli = Join-Path $install 'fetchvolt.cmd'
Assert-PlainPath $cli
$cliText = @'
@rem FetchVolt managed terminal launcher
@echo off
"%~dp0Net Booster.exe" %*
if not "%errorlevel%"=="42" exit /b %errorlevel%
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -Command "$p=Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Programs\Net Booster\.update-result.json';for($i=0;$i -lt 120;$i++){try{$r=Get-Content -LiteralPath $p -Raw|ConvertFrom-Json;if($r.state -ne 'pending'){Write-Host $r.message;exit [int]$r.exitCode}}catch{};Start-Sleep -Seconds 1};Write-Error 'Update result timed out; check the installation before retrying.';exit 1"
exit /b %errorlevel%
'@
[IO.File]::WriteAllText($cli,$cliText.Replace("`n","`r`n"),[Text.ASCIIEncoding]::new())
foreach($name in @('LICENSE','LICENSING.md','NOTICE.md')) {
 $source=Join-Path $PSScriptRoot $name;$destination=Join-Path $install $name;Assert-PlainPath $destination
 if(Test-Path -LiteralPath $source -PathType Leaf){[IO.File]::Copy($source,$destination,$true)}
}
$environmentKey=[Microsoft.Win32.Registry]::CurrentUser.CreateSubKey('Environment')
try {
 $raw=[string]$environmentKey.GetValue('Path','',[Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
 $parts=@(); if($raw){$parts=@($raw -split ';')}
 $kind=if($environmentKey.GetValueNames() -contains 'Path'){$environmentKey.GetValueKind('Path')}else{[Microsoft.Win32.RegistryValueKind]::ExpandString}
 if($install -notin $parts){$environmentKey.SetValue('Path',(($parts+$install)-join ';'),$kind)}
} finally {$environmentKey.Dispose()}
$env:Path += ';'+$install
$null=New-ItemProperty -LiteralPath $registry -Name CliPath -Value $install -PropertyType String -Force
$null=New-ItemProperty -LiteralPath $registry -Name DisplayVersion -Value '2.6.1' -PropertyType String -Force
Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; public class FetchVoltEnvironment { [DllImport("user32.dll",CharSet=CharSet.Unicode)] public static extern IntPtr SendMessageTimeout(IntPtr h,uint m,UIntPtr w,string l,uint f,uint t,out UIntPtr r); }'
[UIntPtr]$broadcastResult=[UIntPtr]::Zero
$null=[FetchVoltEnvironment]::SendMessageTimeout([IntPtr]0xffff,0x1a,[UIntPtr]::Zero,'Environment',2,1000,[ref]$broadcastResult)
Write-Host "FetchVolt installed in $install. Open a new terminal to use fetchvolt --help."

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
