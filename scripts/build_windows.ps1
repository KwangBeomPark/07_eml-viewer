[CmdletBinding()]
param(
    [switch]$SkipSign,
    [switch]$Signed,
    [string]$CertificateThumbprint = $env:SIGN_CERT_THUMBPRINT,
    [string]$TimestampServer = "http://timestamp.digicert.com"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
if ($Signed -and $SkipSign) { throw 'Signed and SkipSign are mutually exclusive.' }
if ($Signed -and [string]::IsNullOrWhiteSpace($CertificateThumbprint)) {
    throw 'CertificateThumbprint is required for an explicitly signed development build.'
}

$ProjectRoot = Resolve-Path "$PSScriptRoot\.."
Push-Location $ProjectRoot

. (Join-Path $PSScriptRoot "Signing.ps1")

try {
    $VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    $Python = if (Test-Path $VenvPython) { $VenvPython } else { "python" }

    & $Python -m PyInstaller --clean --noconfirm "installer\eml_viewer.spec"
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed: $LASTEXITCODE" }
    Write-Host "Build complete: dist\EmlViewer"

    $exePath = Join-Path $ProjectRoot "dist\EmlViewer\EmlViewer.exe"
    if ($Signed -and (Test-Path $exePath)) {
        Invoke-SignBinary -FilePath $exePath -CertificateThumbprint $CertificateThumbprint -TimestampServer $TimestampServer
    }
}
finally {
    Pop-Location
}
