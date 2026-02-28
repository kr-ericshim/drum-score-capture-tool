$ErrorActionPreference = "Stop"

$RootDir = Resolve-Path (Join-Path $PSScriptRoot "..")
$BackendDir = Join-Path $RootDir "backend"
$DesktopDir = Join-Path $RootDir "desktop"

function Write-Header {
  Write-Host ""
  Write-Host "==================================================" -ForegroundColor Cyan
  Write-Host " Drum Sheet Capture - Easy Setup (Windows)" -ForegroundColor Cyan
  Write-Host "==================================================" -ForegroundColor Cyan
}

function Find-PythonLauncher {
  if ($env:DRUMSHEET_PYTHON_BIN -and (Test-Path $env:DRUMSHEET_PYTHON_BIN)) {
    return @{ Cmd = $env:DRUMSHEET_PYTHON_BIN; Args = @(); Label = "env:DRUMSHEET_PYTHON_BIN" }
  }

  $candidates = @(
    @{ Cmd = "py"; Args = @("-3.11"); Label = "py -3.11" },
    @{ Cmd = "py"; Args = @("-3"); Label = "py -3" },
    @{ Cmd = "python"; Args = @(); Label = "python" }
  )

  foreach ($candidate in $candidates) {
    try {
      & $candidate.Cmd @($candidate.Args + @("--version")) *> $null
      if ($LASTEXITCODE -eq 0) {
        return $candidate
      }
    } catch {
      continue
    }
  }

  throw "Python 3.11 not found. Install Python 3.11 (x64) and run again."
}

function Require-Npm {
  try {
    npm --version *> $null
  } catch {
    throw "npm not found. Install Node.js LTS and run again."
  }
}

function Install-Backend {
  param (
    [Parameter(Mandatory = $true)]
    [hashtable]$PythonLauncher
  )

  $venvPath = Join-Path $BackendDir ".venv"
  $venvPython = Join-Path $venvPath "Scripts\python.exe"

  Write-Host "[1/4] Python venv setup" -ForegroundColor Yellow
  & $PythonLauncher.Cmd @($PythonLauncher.Args + @("-m", "venv", $venvPath))
  & $venvPython -m pip install --upgrade pip setuptools wheel

  Write-Host "[2/4] Core backend dependencies" -ForegroundColor Yellow
  & $venvPython -m pip install -r (Join-Path $BackendDir "requirements.txt")

  Write-Host "[3/4] Optional audio dependencies" -ForegroundColor Yellow
  & $venvPython -m pip install -r (Join-Path $BackendDir "requirements-uvr.txt")

  $hasNvidia = $false
  try {
    nvidia-smi *> $null
    if ($LASTEXITCODE -eq 0) {
      $hasNvidia = $true
    }
  } catch {
    $hasNvidia = $false
  }

  if ($hasNvidia) {
    Write-Host "NVIDIA GPU detected -> installing CUDA torch build" -ForegroundColor Green
    & $venvPython -m pip install --index-url https://download.pytorch.org/whl/cu128 torch torchaudio
  } else {
    Write-Host "No NVIDIA GPU detected -> installing CPU torch build" -ForegroundColor Green
    & $venvPython -m pip install torch torchaudio
  }

  & $venvPython -m pip install torchcodec "soundfile>=0.12.0"

  Write-Host "[4/4] Runtime check" -ForegroundColor Yellow
  & $venvPython (Join-Path $BackendDir "scripts\doctor.py")
}

function Install-Desktop {
  Write-Host "[Desktop] npm install" -ForegroundColor Yellow
  Push-Location $DesktopDir
  try {
    npm install
  } finally {
    Pop-Location
  }
}

function Write-NextSteps {
  Write-Host ""
  Write-Host "Setup completed." -ForegroundColor Green
  Write-Host "Run app:"
  Write-Host "  1) Double click: run_app_windows.bat"
  Write-Host "  2) Or terminal: cd desktop && npm start"
}

Write-Header
Require-Npm
$launcher = Find-PythonLauncher
Write-Host ("Using python launcher: " + $launcher.Label) -ForegroundColor Green
Install-Backend -PythonLauncher $launcher
Install-Desktop
Write-NextSteps
