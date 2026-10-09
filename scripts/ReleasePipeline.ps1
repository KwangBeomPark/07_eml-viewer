Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Signing.ps1')

function Invoke-EmlPython {
    param([string]$Python, [string[]]$Arguments)
    $output = & $Python @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Python operation failed: $($Arguments[0])" }
    return $output
}

function Find-EmlIscc {
    $command = Get-Command iscc.exe -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    foreach ($base in @(($env:LOCALAPPDATA + '\Programs'), $env:ProgramFiles, ${env:ProgramFiles(x86)})) {
        foreach ($version in @(7, 6)) {
            $candidate = Join-Path $base "Inno Setup $version\ISCC.exe"
            if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
        }
    }
    throw 'Inno Setup 6 or 7 ISCC.exe not found.'
}

function Assert-EmlPlainDirectoryPath {
    param([string]$Path)
    $current = [IO.Path]::GetFullPath($Path)
    while ($current) {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force
            if (-not $item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
                throw "Plain directory path required: $current"
            }
        }
        $parent = [IO.Path]::GetDirectoryName($current)
        if ($parent -eq $current) { break }
        $current = $parent
    }
}

function Invoke-EmlReleaseBuild {
    [CmdletBinding()]
    param([switch]$Signed, [string]$CertificateThumbprint, [string]$TimestampServer, [string]$SignToolPath)
    $root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
    $python = Join-Path $root '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python)) { $python = 'python' }
    $helper = Join-Path $PSScriptRoot 'release_artifacts.py'
    $iscc = Find-EmlIscc
    if ($Signed) { Find-EmlSignTool $SignToolPath | Out-Null }
    Push-Location $root
    try {
        $version = (Invoke-EmlPython $python @('-c', "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")).Trim()
        if ($Signed) { Invoke-EmlPython $python @($helper, 'preflight', '--release', (Join-Path $root 'release'), '--version', $version) | Out-Null }
        $sourceJson = (Invoke-EmlPython $python @($helper, 'identity', '--root', $root)) -join "`n"
        $source = $sourceJson | ConvertFrom-Json
        if ($Signed -and $source.dirty) { throw 'Commit the reviewed source before creating an official signed release.' }
        $stage = Join-Path $root ('build\release-staging\' + [guid]::NewGuid().ToString('N'))
        $artifacts = Join-Path $stage 'artifacts'
        Assert-EmlPlainDirectoryPath $stage
        Assert-EmlPlainDirectoryPath (Join-Path $root 'release')
        New-Item -ItemType Directory -Path $artifacts -Force | Out-Null
        Write-Host "Isolated output: $stage"
        if ($Signed) {
            $previousQtPlatform = $env:QT_QPA_PLATFORM
            try {
                $env:QT_QPA_PLATFORM = 'offscreen'
                & $python -m pytest tests -q *> (Join-Path $stage 'pytest.txt')
                if ($LASTEXITCODE -ne 0) { throw "Tests failed; see $stage\pytest.txt" }
            } finally { $env:QT_QPA_PLATFORM = $previousQtPlatform }
            & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'tests\Test-ReleaseSigning.ps1') *> (Join-Path $stage 'signing-tests.txt')
            if ($LASTEXITCODE -ne 0) { throw "Signing regression tests failed; see $stage\signing-tests.txt" }
            & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'scripts\test_user_data_backup.ps1') *> (Join-Path $stage 'backup-tests.txt')
            if ($LASTEXITCODE -ne 0) { throw "Backup regression tests failed; see $stage\backup-tests.txt" }
        }
        Invoke-EmlPython $python @('-m', 'PyInstaller', '--clean', '--noconfirm', '--distpath', (Join-Path $stage 'dist'), '--workpath', (Join-Path $stage 'work'), 'installer\eml_viewer.spec') | Out-Host
        $bundle = Join-Path $stage 'dist\EmlViewer'
        if (-not (Test-Path -LiteralPath (Join-Path $bundle 'EmlViewer.exe'))) { throw 'Main executable missing.' }
        $payloadSignatures = [ordered]@{}
        if ($Signed) {
            foreach ($exe in Get-ChildItem -LiteralPath $bundle -Filter '*.exe' -Recurse -File) {
                Invoke-SignBinary -FilePath $exe.FullName -CertificateThumbprint $CertificateThumbprint -TimestampServer $TimestampServer -SignToolPath $SignToolPath
                $name = 'EmlViewer/' + $exe.FullName.Substring($bundle.Length + 1).Replace('\', '/')
                $payloadSignatures[$name] = Assert-EmlSignature $exe.FullName $CertificateThumbprint
            }
        }
        & $iscc "/DMyAppVersion=$version" "/DMyAppSourceDir=$bundle" "/O$artifacts" 'installer\setup.iss'
        if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed: $LASTEXITCODE" }
        $installerName = "App07_EmlViewer_Setup_v$version.exe"
        $installer = Join-Path $artifacts $installerName
        if (-not (Test-Path -LiteralPath $installer -PathType Leaf)) { throw 'Installer missing.' }
        if (-not $Signed) {
            Write-Host "Unsigned preview only: $installer. Nothing promoted to release."
            return
        }
        Invoke-SignBinary -FilePath $installer -CertificateThumbprint $CertificateThumbprint -TimestampServer $TimestampServer -SignToolPath $SignToolPath
        $payloadSignatures[$installerName] = Assert-EmlSignature $installer $CertificateThumbprint
        Invoke-EmlPython $python @($helper, 'package', '--stage', $stage, '--version', $version) | Out-Host
        $afterJson = (Invoke-EmlPython $python @($helper, 'identity', '--root', $root)) -join "`n"
        if ($afterJson -ne $sourceJson) { throw 'Source changed during build; rebuild required.' }
        $receipt = [ordered]@{ source = $source; tests = 'pytest tests -q: passed'; signing_tests = 'Test-ReleaseSigning.ps1: passed'; backup_tests = 'test_user_data_backup.ps1: passed'; built_utc = [DateTime]::UtcNow.ToString('o'); signer_thumbprint = $CertificateThumbprint; signed_payloads = $payloadSignatures }
        [IO.File]::WriteAllText((Join-Path $stage 'receipt.json'), ($receipt | ConvertTo-Json -Depth 12), [Text.UTF8Encoding]::new($false))
        Invoke-EmlPython $python @($helper, 'manifest', '--stage', $stage, '--version', $version) | Out-Host
        Invoke-EmlPython $python @($helper, 'promote', '--root', $root, '--stage', $stage, '--version', $version, '--release', (Join-Path $root 'release')) | Out-Host
        Write-Host "Validated release promoted without overwrites: v$version. Publication is separate."
    } finally { Pop-Location }
}
