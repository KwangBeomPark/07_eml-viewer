<# Read-only signature verification; this script never signs or publishes. #>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Directory,
    [Parameter(Mandatory = $true)][string]$CertificateThumbprint
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Signing.ps1')
$files = @(Get-ChildItem -LiteralPath $Directory -Filter '*.exe' -Recurse -File)
if ($files.Count -eq 0) { throw 'No executable signature candidates.' }
foreach ($file in $files) { Assert-EmlSignature $file.FullName $CertificateThumbprint | Out-Null }
