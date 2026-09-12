[CmdletBinding()]
param(
    [switch]$SkipSign,
    [string]$CertificateThumbprint = $env:SIGN_CERT_THUMBPRINT,
    [string]$TimestampServer = "http://timestamp.digicert.com"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path "$PSScriptRoot\.."
Push-Location $ProjectRoot

. (Join-Path $PSScriptRoot "Signing.ps1")

try {
    $VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    $Python = if (Test-Path $VenvPython) { $VenvPython } else { "python" }

    & $Python -m PyInstaller --clean --noconfirm "packaging\pyinstaller\eml_viewer.spec"
    Write-Host "Build complete: dist\EmlViewer"

    $exePath = Join-Path $ProjectRoot "dist\EmlViewer\EmlViewer.exe"
    if (-not $SkipSign -and (Test-Path $exePath)) {
        Invoke-SignBinary -FilePath $exePath -CertificateThumbprint $CertificateThumbprint -TimestampServer $TimestampServer
    }
}
finally {
    Pop-Location
}
