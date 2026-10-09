Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\scripts\Signing.ps1')
. (Join-Path $PSScriptRoot '..\scripts\ReleasePipeline.ps1')
$script:signature = $null
function Get-AuthenticodeSignature { param([string]$LiteralPath); return $script:signature }
function Assert-Throws {
    param([scriptblock]$Action)
    $thrown = $false
    try { & $Action | Out-Null } catch { $thrown = $true }
    if (-not $thrown) { throw 'Expected safe failure was not raised.' }
}
foreach ($case in @('NotSigned', 'WrongSigner', 'NoTimestamp', 'Valid')) {
    $script:signature = [pscustomobject]@{
        Status = if ($case -eq 'NotSigned') { 'NotSigned' } else { 'Valid' }
        SignerCertificate = [pscustomobject]@{ Thumbprint = if ($case -eq 'WrongSigner') { 'OTHER' } else { 'EXPECTED' } }
        TimeStamperCertificate = if ($case -eq 'NoTimestamp') { $null } else { [pscustomobject]@{ Thumbprint = 'TIMESTAMP' } }
    }
    if ($case -eq 'Valid') {
        $receipt = Assert-EmlSignature 'fixture.exe' 'EXPECTED'
        if ($receipt.status -ne 'Valid') { throw 'Expected valid receipt.' }
    } else { Assert-Throws { Assert-EmlSignature 'fixture.exe' 'EXPECTED' } }
}
Assert-Throws { Find-EmlSignTool (Join-Path $PSScriptRoot 'missing-signtool.exe') }
Assert-Throws { Invoke-SignBinary -FilePath 'missing-file.exe' -CertificateThumbprint 'EXPECTED' }
Assert-EmlPlainDirectoryPath (Join-Path $PSScriptRoot '..\build\fixture-child')
Assert-Throws { Assert-EmlPlainDirectoryPath $PSCommandPath }
$developmentBuild = Join-Path $PSScriptRoot '..\scripts\build_windows.ps1'
Assert-Throws { & $developmentBuild -Signed -SkipSign }
Assert-Throws { & $developmentBuild -Signed -CertificateThumbprint '' }
Write-Host '10 signing/path safety assertions passed (mock signature objects; no signing invoked).'
