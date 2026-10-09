<# Unsigned preview by default; -Signed delegates to the tested signing pipeline. #>
[CmdletBinding()]
param(
    [switch]$SkipSign,
    [switch]$Signed,
    [string]$CertificateThumbprint = $env:SIGN_CERT_THUMBPRINT,
    [string]$TimestampServer = 'http://timestamp.digicert.com',
    [string]$SignToolPath = $env:SIGNTOOL_PATH
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($Signed -and $SkipSign) { throw 'Signed and SkipSign are mutually exclusive.' }
if ($Signed) {
    & (Join-Path $PSScriptRoot 'sign_and_release.ps1') -CertificateThumbprint $CertificateThumbprint -TimestampServer $TimestampServer -SignToolPath $SignToolPath
} else {
    . (Join-Path $PSScriptRoot 'ReleasePipeline.ps1')
    Invoke-EmlReleaseBuild
}
