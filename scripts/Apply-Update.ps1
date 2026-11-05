#Requires -Version 7.0
[CmdletBinding()]
param([Parameter(Mandatory)][int]$WaitPid)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$install=Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Programs\Net Booster'
$stage=[IO.Path]::GetFullPath($PSScriptRoot)
$result=Join-Path $install '.update-result.json'
$lock=$null
$records=[Collections.Generic.List[object]]::new()
$success=$false
function AssertPlain([string]$path) {
 for($item=$path;$item;$item=Split-Path -Parent $item){$entry=Get-Item -LiteralPath $item -Force -ErrorAction SilentlyContinue;if($entry -and ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint)){throw 'Linked update path rejected.'}}
}
function Hash([string]$path){(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()}
try {
 if((Split-Path -Parent $stage) -ne $install -or (Split-Path -Leaf $stage) -notmatch '^\.fetchvolt-update-[A-Za-z0-9_-]+$'){throw 'Invalid staging root.'}
 AssertPlain $stage
 $parent=Get-Process -Id $WaitPid -ErrorAction SilentlyContinue
 if($parent -and !$parent.WaitForExit(90000)){throw 'Updater did not exit.'}
 $lockPath=[IO.File]::ReadAllText((Join-Path $stage 'lock-path.txt'));AssertPlain $lockPath
 $lock=[IO.File]::Open($lockPath,[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
 $wrapper=Get-Content -LiteralPath (Join-Path $stage 'update.json') -Raw|ConvertFrom-Json
 if($wrapper.algorithm -ne 'rsa-pkcs1v15-sha256'){throw 'Invalid update signature format.'}
 $payload=[Convert]::FromBase64String($wrapper.payload)
 $rsa=[Security.Cryptography.RSACryptoServiceProvider]::new();$rsa.PersistKeyInCsp=$false
 try {$rsa.FromXmlString('__PUBLIC_KEY_XML__');if(!$rsa.VerifyData($payload,'SHA256',[Convert]::FromBase64String($wrapper.signature))){throw 'Publisher verification failed.'}}finally{$rsa.Dispose()}
 $manifest=[Text.Encoding]::UTF8.GetString($payload)|ConvertFrom-Json
 $expected=@('FetchVolt.exe','Install-NetBooster.ps1','Uninstall-NetBooster.ps1','NOTICE.md','LICENSE','LICENSING.md','THIRD-PARTY-NOTICES.txt','INSTALL.txt','PAYLOAD-SHA256.txt')
 if($manifest.format -ne 1 -or $manifest.version -notmatch '^\d{1,5}\.\d{1,5}\.\d{1,5}$' -or @($manifest.files.PSObject.Properties).Count -ne $expected.Count){throw 'Invalid update manifest.'}
 foreach($name in $expected){
  $entry=$manifest.files.$name;$file=Join-Path $stage $name;AssertPlain $file
  if($entry.bytes -lt 1 -or $entry.bytes -gt 134217728 -or (Get-Item -LiteralPath $file).Length -ne $entry.bytes -or (Hash $file) -cne $entry.sha256){throw 'Signed payload changed.'}
 }
 $exe=Join-Path $install 'Net Booster.exe';AssertPlain $exe
 $current=[Diagnostics.FileVersionInfo]::GetVersionInfo($exe)
 if($current.ProductName -ne 'FetchVolt' -or [Version]($manifest.version+'.0') -le [Version]$current.FileVersion){throw 'Update target or version rejected.'}
 $new=[Diagnostics.FileVersionInfo]::GetVersionInfo((Join-Path $stage 'FetchVolt.exe'))
 if([Version]$new.FileVersion -ne [Version]($manifest.version+'.0')){throw 'Payload version mismatch.'}
 for($attempt=0;$attempt -lt 30;$attempt++){
  try{$probe=[IO.File]::Open($exe,[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None);$probe.Dispose();break}
  catch{if($attempt -eq 29){throw 'Installed application is still running.'};Start-Sleep -Seconds 1}
 }
 foreach($pair in @(@('FetchVolt.exe','Net Booster.exe'),@('Uninstall-NetBooster.ps1','Uninstall-NetBooster.ps1'),@('LICENSE','LICENSE'),@('LICENSING.md','LICENSING.md'),@('NOTICE.md','NOTICE.md'))){
  $source=Join-Path $stage $pair[0];$destination=Join-Path $install $pair[1];AssertPlain $destination
  $backup=Join-Path $stage ('original-'+$records.Count+'.bak')
  $record=@{Destination=$destination;Backup=$backup;HadOriginal=[IO.File]::Exists($destination)};$records.Add($record)
  if($record.HadOriginal){[IO.File]::Move($destination,$backup)}
  [IO.File]::Move($source,$destination)
 }
 [IO.File]::WriteAllText((Join-Path $stage 'complete.marker'),"FetchVolt update completed`n")
 $state=@{state='complete';message=('FetchVolt '+$manifest.version+' installed.');exitCode=0};$success=$true
 $registry='HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\NetBooster'
 try{$null=New-ItemProperty -LiteralPath $registry -Name DisplayVersion -Value $manifest.version -PropertyType String -Force}catch{}
 foreach($record in $records){try{if([IO.File]::Exists($record.Backup)){[IO.File]::Delete($record.Backup)}}catch{}}
} catch {
 $rollbackFailed=$false
 for($i=$records.Count-1;$i -ge 0;$i--){
  $record=$records[$i]
  try {
   if([IO.File]::Exists($record.Backup)){if([IO.File]::Exists($record.Destination)){[IO.File]::Delete($record.Destination)};[IO.File]::Move($record.Backup,$record.Destination)}
   elseif(!$record.HadOriginal -and [IO.File]::Exists($record.Destination)){[IO.File]::Delete($record.Destination)}
  }catch{$rollbackFailed=$true}
 }
 $message=if($rollbackFailed){'Update failed. Recovery files were preserved; reinstall the verified setup bundle.'}else{'Update failed; the existing installation was preserved. Check that the app is closed and Windows permits the update.'}
 $state=@{state='failed';message=$message;exitCode=1}
} finally {
 if($lock){$lock.Dispose()}
 try{[IO.File]::WriteAllText($result+'.tmp',($state|ConvertTo-Json -Compress));[IO.File]::Move($result+'.tmp',$result,$true)}catch{}
 if($success){foreach($name in @('package.zip','Install-NetBooster.ps1','THIRD-PARTY-NOTICES.txt','INSTALL.txt','PAYLOAD-SHA256.txt')){try{[IO.File]::Delete((Join-Path $stage $name))}catch{}}}
}
