Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Find-EmlSignTool {
    param([string]$SignToolPath = $env:SIGNTOOL_PATH)
    if ($SignToolPath) {
        if (-not (Test-Path -LiteralPath $SignToolPath -PathType Leaf)) { throw 'Configured SIGNTOOL_PATH does not exist.' }
        return (Resolve-Path -LiteralPath $SignToolPath).Path
    }
    $command = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    $local = Join-Path $PSScriptRoot '..\tools\signtool\signtool.exe'
    if (Test-Path -LiteralPath $local -PathType Leaf) { return (Resolve-Path -LiteralPath $local).Path }
    $sdk = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10\bin'
    if (Test-Path -LiteralPath $sdk) {
        $versions = Get-ChildItem -LiteralPath $sdk -Directory | Where-Object { $_.Name -match '^\d+\.\d+\.\d+\.\d+$' } | Sort-Object { [version]$_.Name } -Descending
        foreach ($version in $versions) {
            $candidate = Join-Path $version.FullName 'x64\signtool.exe'
            if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
        }
    }
    throw 'signtool.exe was not found. Specify -SignToolPath or install the Windows SDK.'
}

function Assert-EmlSignature {
    param([string]$FilePath, [string]$CertificateThumbprint)
    $signature = Get-AuthenticodeSignature -LiteralPath $FilePath
    if ($signature.Status -ne 'Valid' -or -not $signature.SignerCertificate -or
        $signature.SignerCertificate.Thumbprint -ne $CertificateThumbprint -or -not $signature.TimeStamperCertificate) {
        throw "Valid timestamped signature by intended signer required: $FilePath"
    }
    return [ordered]@{ status = 'Valid'; signer_thumbprint = $signature.SignerCertificate.Thumbprint; timestamp_thumbprint = $signature.TimeStamperCertificate.Thumbprint }
}

function Invoke-SignBinary {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string]$CertificateThumbprint,
        [string]$TimestampServer = 'http://timestamp.digicert.com',
        [string]$SignToolPath = $env:SIGNTOOL_PATH
    )
    if (-not (Test-Path -LiteralPath $FilePath -PathType Leaf)) { throw "File to sign not found: $FilePath" }
    if ([string]::IsNullOrWhiteSpace($CertificateThumbprint) -or [string]::IsNullOrWhiteSpace($TimestampServer)) { throw 'Signer and timestamp server are required.' }
    $tool = Find-EmlSignTool $SignToolPath
    & $tool sign /sha1 $CertificateThumbprint /fd sha256 /tr $TimestampServer /td sha256 $FilePath
    if ($LASTEXITCODE -ne 0) { throw "signtool failed: $LASTEXITCODE" }
    Assert-EmlSignature $FilePath $CertificateThumbprint | Out-Null
}
