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

    $Version = & $Python -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])"
    Write-Host "Building EML Viewer version $Version..."

    & $Python -m PyInstaller --clean --noconfirm "packaging\pyinstaller\eml_viewer.spec"

    $exePath = Join-Path $ProjectRoot "dist\EmlViewer\EmlViewer.exe"
    if (-not $SkipSign -and (Test-Path $exePath)) {
        Invoke-SignBinary -FilePath $exePath -CertificateThumbprint $CertificateThumbprint -TimestampServer $TimestampServer
    }

    $IsccCandidates = @(
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe"
    )
    $Iscc = $null
    foreach ($Candidate in $IsccCandidates) {
        if (Test-Path $Candidate) {
            $Iscc = $Candidate
            break
        }
    }
    if ($null -eq $Iscc) {
        $Command = Get-Command iscc -ErrorAction SilentlyContinue
        if ($Command) {
            $Iscc = $Command.Source
        }
    }
    if ($null -eq $Iscc) {
        throw "Could not find Inno Setup 6 ISCC.exe. Please install Inno Setup 6 and run again."
    }

    New-Item -ItemType Directory -Force -Path "installer" | Out-Null
    & $Iscc "/DMyAppVersion=$Version" "packaging\inno\eml_viewer.iss"

    $installerPath = Join-Path $ProjectRoot "installer\EmlViewerSetup-$Version.exe"
    if (-not (Test-Path $installerPath)) {
        throw "Expected installer output not found: $installerPath"
    }

    if (-not $SkipSign) {
        Invoke-SignBinary -FilePath $installerPath -CertificateThumbprint $CertificateThumbprint -TimestampServer $TimestampServer
    }

    Write-Host "Installer build and signing complete: $installerPath" -ForegroundColor Green
}
finally {
    Pop-Location
}
