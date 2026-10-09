<#
.SYNOPSIS
Build, test and sign a new release in isolation, then promote without overwrites.
.DESCRIPTION
Requires the user's active signing session. Never installs or publishes.
Existing official artifacts (including the same version) are protected.
#>
[CmdletBinding()]
param(
    [string]$CertificateThumbprint = $env:SIGN_CERT_THUMBPRINT,
    [string]$TimestampServer = 'http://timestamp.digicert.com',
    [string]$SignToolPath = $env:SIGNTOOL_PATH,
    [switch]$SkipBuild
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($SkipBuild) { throw 'SkipBuild is not signable: rebuild with test/source provenance.' }
if ([string]::IsNullOrWhiteSpace($CertificateThumbprint)) { throw 'Specify -CertificateThumbprint or SIGN_CERT_THUMBPRINT.' }
. (Join-Path $PSScriptRoot 'ReleasePipeline.ps1')
Invoke-EmlReleaseBuild -Signed -CertificateThumbprint $CertificateThumbprint -TimestampServer $TimestampServer -SignToolPath $SignToolPath
