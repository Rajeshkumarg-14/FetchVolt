#Requires -Version 7.0
[CmdletBinding()]
param([switch]$InitializeKey,[string]$ManifestPath,[string]$OutputPath,[string]$KeyFile=(Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'FetchVolt\publisher\update-key.dpapi'))
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Security
$rsa=[Security.Cryptography.RSACryptoServiceProvider]::new(3072)
$rsa.PersistKeyInCsp=$false
try {
    if($InitializeKey) {
        if(Test-Path -LiteralPath $KeyFile){throw 'A publisher key already exists. Never rotate a deployed trust key accidentally.'}
        $null=[IO.Directory]::CreateDirectory((Split-Path -Parent $KeyFile))
        $secret=[Text.Encoding]::UTF8.GetBytes($rsa.ToXmlString($true))
        try { $protected=[Security.Cryptography.ProtectedData]::Protect($secret,$null,[Security.Cryptography.DataProtectionScope]::CurrentUser); [IO.File]::WriteAllBytes($KeyFile,$protected) }
        finally {[Array]::Clear($secret,0,$secret.Length)}
        $public=$rsa.ToXmlString($false)
        $module=Join-Path (Split-Path -Parent $PSScriptRoot) 'app\update_key.py'
        [IO.File]::WriteAllText($module,"# Public update-verification key. Private key is never shipped.`nPUBLIC_KEY_XML = '''$public'''`n",[Text.UTF8Encoding]::new($false))
        Write-Host 'Publisher signing key protected with current-user Windows DPAPI; public trust key written.'
        return
    }
    if(!$ManifestPath -or !$OutputPath){throw 'Provide -ManifestPath and -OutputPath.'}
    $secret=[Security.Cryptography.ProtectedData]::Unprotect([IO.File]::ReadAllBytes($KeyFile),$null,[Security.Cryptography.DataProtectionScope]::CurrentUser)
    try {$rsa.FromXmlString([Text.Encoding]::UTF8.GetString($secret))} finally {[Array]::Clear($secret,0,$secret.Length)}
    $bytes=[IO.File]::ReadAllBytes((Resolve-Path -LiteralPath $ManifestPath))
    if($bytes.Length -gt 24576){throw 'Manifest exceeds the signed metadata limit.'}
    $signature=$rsa.SignData($bytes,'SHA256')
    $wrapper=[ordered]@{algorithm='rsa-pkcs1v15-sha256';payload=[Convert]::ToBase64String($bytes);signature=[Convert]::ToBase64String($signature)}
    [IO.File]::WriteAllText([IO.Path]::GetFullPath($OutputPath),($wrapper|ConvertTo-Json -Compress),[Text.UTF8Encoding]::new($false))
    Write-Host 'Signed update manifest created. Verify artifacts before publishing it.'
} finally {$rsa.Dispose()}
