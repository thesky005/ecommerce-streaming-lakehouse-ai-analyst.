# Prepares a no-admin, no-Docker local environment for running the Spark jobs on Windows.
# Downloads a portable Java 17 runtime, Hadoop winutils, and uv (which installs Python 3.11)
# into .tools/, then builds .venv with every Python dependency.
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$root = Split-Path -Parent $PSScriptRoot
$tools = Join-Path $root ".tools"
New-Item -ItemType Directory -Force $tools | Out-Null

function Get-Download([string]$Url, [string]$Destination) {
    Write-Host "Downloading $Url"
    Invoke-WebRequest -Uri $Url -OutFile $Destination -UseBasicParsing
}

# 1. Portable Java 17 runtime (Spark 3.5 supports Java 8/11/17).
$jdk = Join-Path $tools "jdk"
if (-not (Test-Path (Join-Path $jdk "bin\java.exe"))) {
    $zip = Join-Path $tools "jre.zip"
    Get-Download "https://api.adoptium.net/v3/binary/latest/17/ga/windows/x64/jre/hotspot/normal/eclipse" $zip
    $extract = Join-Path $tools "jre-extract"
    Expand-Archive $zip $extract -Force
    Move-Item (Get-ChildItem $extract -Directory | Select-Object -First 1).FullName $jdk
    Remove-Item $zip, $extract -Recurse -Force
}

# 2. Hadoop native helpers that Spark needs to write files on Windows.
$hadoopBin = Join-Path $tools "hadoop\bin"
New-Item -ItemType Directory -Force $hadoopBin | Out-Null
foreach ($file in "winutils.exe", "hadoop.dll") {
    $target = Join-Path $hadoopBin $file
    if (-not (Test-Path $target)) {
        Get-Download "https://raw.githubusercontent.com/cdarlint/winutils/master/hadoop-3.3.6/bin/$file" $target
    }
}

# 3. uv, which installs a user-level Python 3.11 (PySpark 3.5 does not support 3.13).
$uv = Join-Path $tools "uv\uv.exe"
if (-not (Test-Path $uv)) {
    $zip = Join-Path $tools "uv.zip"
    Get-Download "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip" $zip
    Expand-Archive $zip (Join-Path $tools "uv") -Force
    Remove-Item $zip -Force
}

# 4. Python 3.11 virtual environment with all project dependencies.
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
$needsVenv = $true
if (Test-Path $venvPython) {
    $version = & $venvPython -c "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')" 2>$null
    $needsVenv = $version -ne "3.11"
}
if ($needsVenv) {
    if (Test-Path (Join-Path $root ".venv")) { Remove-Item (Join-Path $root ".venv") -Recurse -Force }
    & $uv python install 3.11
    & $uv venv (Join-Path $root ".venv") --python 3.11
}
& $uv pip install --python $venvPython -r (Join-Path $root "requirements\dev.txt")

Write-Host ""
Write-Host "Local environment ready. Run the pipeline with:"
Write-Host "  .\.venv\Scripts\python.exe scripts\run_local.py"
