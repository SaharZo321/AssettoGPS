[CmdletBinding()]
param(
    [string]$Version = "0.2.0-beta.7",
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$buildRoot = Join-Path $repoRoot "build"
$workPath = Join-Path $buildRoot "pyinstaller-work"
$distPath = Join-Path $buildRoot "pyinstaller-dist"
$stageRoot = Join-Path $buildRoot "release"
$appStage = Join-Path $stageRoot "apps\lua\AssettoGPS"
$serverStage = Join-Path $appStage "server"
$zipPath = Join-Path $buildRoot "AssettoGPS-$Version.zip"
$frontendData = "$((Join-Path $repoRoot "frontend"));frontend"

if (-not $stageRoot.StartsWith($repoRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Release staging path escaped the repository: $stageRoot"
}

Push-Location $repoRoot
try {
    if (-not $SkipTests) {
        uv run --group build python -m unittest discover -s tests -v
        if ($LASTEXITCODE -ne 0) {
            throw "Unit tests failed."
        }
    }

    $pyInstallerArgs = @(
        "run", "--group", "build", "python", "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name", "AssettoGPS.Server",
        "--paths", "backend",
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

    if (Test-Path -LiteralPath $stageRoot) {
        Remove-Item -LiteralPath $stageRoot -Recurse -Force
    }
    New-Item -ItemType Directory -Path $serverStage -Force | Out-Null

    Copy-Item -Path "ac_app\lua\AssettoGPS\*" -Destination $appStage -Recurse
    Copy-Item -LiteralPath (Join-Path $distPath "AssettoGPS.Server.exe") -Destination $serverStage
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
