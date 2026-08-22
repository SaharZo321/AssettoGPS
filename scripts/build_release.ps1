[CmdletBinding()]
param(
    [string]$Version = "0.2.0-beta.16",
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$buildRoot = Join-Path $repoRoot "build"
$workPath = Join-Path $buildRoot "pyinstaller-work"
$distPath = Join-Path $buildRoot "pyinstaller-dist"
$frontendRuntime = Join-Path $buildRoot "frontend-runtime"
$stageRoot = Join-Path $buildRoot "release"
$appStage = Join-Path $stageRoot "apps\lua\AssettoGPS"
$serverStage = Join-Path $appStage "server"
$zipPath = Join-Path $buildRoot "AssettoGPS-$Version.zip"
$frontendData = "$frontendRuntime;frontend"

if (
    -not $stageRoot.StartsWith($repoRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
    -not $frontendRuntime.StartsWith($buildRoot, [System.StringComparison]::OrdinalIgnoreCase)
) {
    throw "Release staging path escaped the repository: $stageRoot"
}

Push-Location $repoRoot
try {
    & corepack.cmd pnpm install --frozen-lockfile
    if ($LASTEXITCODE -ne 0) {
        throw 'Frontend dependency installation failed.'
    }
    & corepack.cmd pnpm run build
    if ($LASTEXITCODE -ne 0) {
        throw 'Frontend TypeScript build failed.'
    }

    if (Test-Path -LiteralPath $frontendRuntime) {
        Remove-Item -LiteralPath $frontendRuntime -Recurse -Force
    }
    New-Item -ItemType Directory -Path $frontendRuntime -Force | Out-Null
    foreach ($directory in @("assets", "css", "js", "vendor")) {
        Copy-Item -LiteralPath (Join-Path $repoRoot "frontend\$directory") -Destination $frontendRuntime -Recurse -Force
    }
    foreach ($file in @("index.html", "manifest.json")) {
        Copy-Item -LiteralPath (Join-Path $repoRoot "frontend\$file") -Destination $frontendRuntime -Force
    }

    uv sync --group build --locked
    if ($LASTEXITCODE -ne 0) {
        throw "Dependency synchronization failed."
    }

    if (-not $SkipTests) {
        uv run --group build python -m unittest discover -s tests -v
        if ($LASTEXITCODE -ne 0) {
            throw "Unit tests failed."
        }
        uv run python scripts\verify_srp_routing.py
        if ($LASTEXITCODE -ne 0) {
            throw "SRP routing audit failed."
        }
    }

    $pyInstallerArgs = @(
        "run", "--group", "build", "python", "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name", "AssettoGPS.Server",
        "--paths", "backend",
        "--exclude-module", "mock_telemetry",
        "--exclude-module", "dev_server",
        "--add-data", $frontendData,
        "--distpath", $distPath,
        "--workpath", $workPath,
        "--specpath", $buildRoot,
        "backend\server.py"
    )
    & uv @pyInstallerArgs
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller build failed."
    }

    $serverExecutable = Join-Path $distPath "AssettoGPS.Server.exe"
    $archiveListing = (
        & uv run --group build pyi-archive_viewer -r -b $serverExecutable 2>&1 |
            Out-String
    )
    if ($LASTEXITCODE -ne 0) {
        throw "Could not inspect the packaged server archive."
    }
    if ($archiveListing -match "(?i)mock_telemetry|dev_server") {
        throw "Development telemetry code was included in the public executable."
    }

    $frontendMockReferences = @(
        Get-ChildItem -LiteralPath (Join-Path $repoRoot "frontend") -Recurse -File |
            Select-String -SimpleMatch -Pattern "mock"
    )
    if ($frontendMockReferences.Count -gt 0) {
        $locations = $frontendMockReferences |
            ForEach-Object { "$($_.Path):$($_.LineNumber)" }
        throw "Generated-telemetry references were found in the public frontend: $($locations -join ', ')"
    }

    if (Test-Path -LiteralPath $stageRoot) {
        Remove-Item -LiteralPath $stageRoot -Recurse -Force
    }
    New-Item -ItemType Directory -Path $serverStage -Force | Out-Null

    Copy-Item -Path "ac_app\lua\AssettoGPS\*" -Destination $appStage -Recurse
    Copy-Item -LiteralPath $serverExecutable -Destination $serverStage
    Copy-Item -LiteralPath "README.md" -Destination $stageRoot

    uv run --group build python tests\smoke_server.py (Join-Path $serverStage "AssettoGPS.Server.exe")
    if ($LASTEXITCODE -ne 0) {
        throw "Packaged server smoke test failed."
    }

    if (Test-Path -LiteralPath $zipPath) {
        Remove-Item -LiteralPath $zipPath -Force
    }
    Compress-Archive -Path (Join-Path $stageRoot "*") -DestinationPath $zipPath

    Write-Output "Release package: $zipPath"
}
finally {
    Pop-Location
}
