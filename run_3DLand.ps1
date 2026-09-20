$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvDirectory = Join-Path $projectRoot ".venv"
$venvPython = Join-Path $venvDirectory "Scripts\python.exe"
$requirementsFile = Join-Path $projectRoot "requirements.txt"
$applicationFile = Join-Path $projectRoot "main_3d.py"

if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host "Creating the .venv virtual environment..." -ForegroundColor Cyan

    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3.10 -m venv $venvDirectory
    }
    elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python -m venv $venvDirectory
    }
    else {
        throw "Python was not found. Install Python 3.10 or add it to PATH."
    }

    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $venvPython)) {
        throw "Could not create the .venv virtual environment."
    }
}

& $venvPython -c "import ursina" 2>$null
if ($LASTEXITCODE -ne 0) {
    if (-not (Test-Path -LiteralPath $requirementsFile)) {
        throw "requirements.txt was not found."
    }

    Write-Host "Installing dependencies..." -ForegroundColor Cyan
    & $venvPython -m pip install -r $requirementsFile
    if ($LASTEXITCODE -ne 0) {
        throw "Could not install the dependencies."
    }
}

if (-not (Test-Path -LiteralPath $applicationFile)) {
    throw "main_3d.py was not found."
}

Write-Host "Starting the 3D plot planner..." -ForegroundColor Green
$applicationExitCode = 0
Push-Location -LiteralPath $projectRoot
try {
    & $venvPython $applicationFile
    $applicationExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}

exit $applicationExitCode
