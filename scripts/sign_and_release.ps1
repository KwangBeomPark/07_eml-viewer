<#
.SYNOPSIS
    App07_EmlViewer - Automated Digital Signing & Release Pipeline
.DESCRIPTION
    Re-builds PyInstaller distribution, performs code signing,
    compiles the Inno Setup installer into release\,
    signs the installer binary, verifies Authenticode signatures,
    and generates SHA-256 checksums without BOM.
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\sign_and_release.ps1
#>

[CmdletBinding()]
param(
    [string]$CertificateThumbprint = "E9C72CF5090840A1805296525D56BE680622A7FD",
    [string]$TimestampServer = "http://timestamp.digicert.com",
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Resolve-Path "$PSScriptRoot\.."
Push-Location $ProjectRoot

try {
    # 1. Load signing helper
    . (Join-Path $PSScriptRoot "Signing.ps1")

    # 2. Read package version
    $VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    $Python = if (Test-Path $VenvPython) { $VenvPython } else { "python" }
    $Version = & $Python -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])"

    Write-Host "`n=== App07_EmlViewer Release Pipeline (v$Version) ===" -ForegroundColor Cyan

    # 3. Clean Re-build Application Binary (Prevent stale binaries)
    $appPath = Join-Path $ProjectRoot "dist\EmlViewer\EmlViewer.exe"
    if (-not $SkipBuild) {
        Write-Host "Building clean PyInstaller distribution..." -ForegroundColor Yellow
        & $Python -m PyInstaller --clean --noconfirm "packaging\pyinstaller\eml_viewer.spec"
        if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed with exit code $LASTEXITCODE" }
    }

    if (-not (Test-Path $appPath)) {
        throw "Main application executable not found: $appPath"
    }

    # 4. Sign and Verify Main Application Binary
    Write-Host "Signing main application binary: $appPath"
    Invoke-SignBinary -FilePath $appPath -CertificateThumbprint $CertificateThumbprint -TimestampServer $TimestampServer
    $appSig = Get-AuthenticodeSignature -LiteralPath $appPath
    if ($appSig.Status -ne "Valid") {
        throw "Authenticode signature verification failed for $appPath (Status: $($appSig.Status))"
    }
    Write-Host "Signature verified: Valid" -ForegroundColor Green

    # 5. Compile Inno Setup Installer
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
        if ($Command) { $Iscc = $Command.Source }
    }
    if ($null -eq $Iscc) {
        throw "Could not find Inno Setup 6 or 7 ISCC.exe."
    }

    $ReleaseDir = Join-Path $ProjectRoot "release"
    New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null

    Write-Host "Compiling installer into release\ directory..."
    & $Iscc "/DMyAppVersion=$Version" "packaging\inno\eml_viewer.iss"
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup compilation failed with exit code $LASTEXITCODE" }

    $installerName = "App07_EmlViewer_Setup_v$Version.exe"
    $installerPath = Join-Path $ReleaseDir $installerName
    if (-not (Test-Path $installerPath)) {
        throw "Installer binary not found: $installerPath"
    }

    # 6. Sign and Verify Installer Binary
    Write-Host "Signing installer binary: $installerPath"
    Invoke-SignBinary -FilePath $installerPath -CertificateThumbprint $CertificateThumbprint -TimestampServer $TimestampServer
    $installerSig = Get-AuthenticodeSignature -LiteralPath $installerPath
    if ($installerSig.Status -ne "Valid") {
        throw "Authenticode signature verification failed for $installerPath (Status: $($installerSig.Status))"
    }
    Write-Host "Signature verified: Valid" -ForegroundColor Green

    # Legacy compatibility copy
    $legacyInstallerPath = Join-Path $ReleaseDir "EmlViewerSetup-$Version.exe"
    Copy-Item -Path $installerPath -Destination $legacyInstallerPath -Force

    # 7. Package ZIP distributions
    $installerZipPath = Join-Path $ReleaseDir "App07_EmlViewer_Setup_v$Version.zip"
    if (Test-Path $installerZipPath) { Remove-Item -Force $installerZipPath }
    Write-Host "Creating installer zip: $installerZipPath..."
    Compress-Archive -Path $installerPath -DestinationPath $installerZipPath -Force

    $portableZipPath = Join-Path $ReleaseDir "App07_EmlViewer_v$Version-win64-portable.zip"
    if (Test-Path $portableZipPath) { Remove-Item -Force $portableZipPath }
    Write-Host "Creating portable zip: $portableZipPath..."
    $distDir = Join-Path $ProjectRoot "dist\EmlViewer"
    Compress-Archive -Path $distDir -DestinationPath $portableZipPath -Force

    # 8. Checksum generation (Standard format without BOM)
    Write-Host "Generating SHA-256 checksums..."
    $installerHash = (Get-FileHash -LiteralPath $installerPath -Algorithm SHA256).Hash.ToLowerInvariant()
    Set-Content -LiteralPath "$installerPath.sha256" -Value "$installerHash *$installerName" -Encoding ascii

    $checksumsPath = Join-Path $ReleaseDir "SHA256SUMS.txt"
    $artifactsToHash = @($installerPath, $legacyInstallerPath, $installerZipPath, $portableZipPath)
    $hashLines = foreach ($file in $artifactsToHash) {
        if (Test-Path $file) {
            $hash = (Get-FileHash -Path $file -Algorithm SHA256).Hash.ToLowerInvariant()
            $fileName = Split-Path -Leaf $file
            "$hash  $fileName"
        }
    }
    [System.IO.File]::WriteAllLines($checksumsPath, $hashLines, [System.Text.UTF8Encoding]::new($false))

    Write-Host "`n[SUCCESS] App07_EmlViewer v$Version successfully built, signed, and packaged in release\" -ForegroundColor Green
}
finally {
    Pop-Location
}
