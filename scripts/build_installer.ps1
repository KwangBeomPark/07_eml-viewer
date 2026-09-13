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
        (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 7\ISCC.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe'),
        'C:\Program Files\Inno Setup 7\ISCC.exe',
        'C:\Program Files (x86)\Inno Setup 7\ISCC.exe',
        'C:\Program Files\Inno Setup 6\ISCC.exe',
        'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'
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
        throw "Could not find Inno Setup 6 or 7 ISCC.exe. Please install Inno Setup and run again."
    }

    New-Item -ItemType Directory -Force -Path "installer" | Out-Null
    & $Iscc "/DMyAppVersion=$Version" "packaging\inno\eml_viewer.iss"

    $installerName = "App07_EmlViewer_Setup_v$Version.exe"
    $installerPath = Join-Path $ProjectRoot "installer\$installerName"
    if (-not (Test-Path $installerPath)) {
        throw "Expected installer output not found: $installerPath"
    }

    if (-not $SkipSign) {
        Invoke-SignBinary -FilePath $installerPath -CertificateThumbprint $CertificateThumbprint -TimestampServer $TimestampServer
    }

    # Backward compatibility copy for previous in-app update checks looking for EmlViewerSetup-*.exe
    $legacyInstallerPath = Join-Path $ProjectRoot "installer\EmlViewerSetup-$Version.exe"
    Copy-Item -Path $installerPath -Destination $legacyInstallerPath -Force

    Write-Host "Installer build and signing complete: $installerPath" -ForegroundColor Green

    # 1. Package installer into ZIP (standard web distribution to prevent browser/SmartScreen raw exe download warnings)
    $installerZipPath = Join-Path $ProjectRoot "installer\App07_EmlViewer_Setup_v$Version.zip"
    if (Test-Path $installerZipPath) { Remove-Item -Force $installerZipPath }
    Write-Host "Creating installer zip: $installerZipPath..."
    Compress-Archive -Path $installerPath -DestinationPath $installerZipPath -Force

    # 2. Package portable distribution (no-install zip containing root EmlViewer folder)
    $portableZipPath = Join-Path $ProjectRoot "installer\App07_EmlViewer_v$Version-win64-portable.zip"
    if (Test-Path $portableZipPath) { Remove-Item -Force $portableZipPath }
    Write-Host "Creating portable zip: $portableZipPath..."
    $distDir = Join-Path $ProjectRoot "dist\EmlViewer"
    Compress-Archive -Path $distDir -DestinationPath $portableZipPath -Force

    # 3. Generate SHA256SUMS.txt
    $checksumsPath = Join-Path $ProjectRoot "installer\SHA256SUMS.txt"
    $artifactsToHash = @($installerPath, $legacyInstallerPath, $installerZipPath, $portableZipPath)
    $hashLines = foreach ($file in $artifactsToHash) {
        if (Test-Path $file) {
            $hash = (Get-FileHash -Path $file -Algorithm SHA256).Hash.ToLowerInvariant()
            $fileName = Split-Path -Leaf $file
            "$hash  $fileName"
        }
    }
    $hashLines | Out-File -FilePath $checksumsPath -Encoding utf8
    Write-Host "SHA256 checksums generated at $checksumsPath" -ForegroundColor Cyan
}
finally {
    Pop-Location
}
