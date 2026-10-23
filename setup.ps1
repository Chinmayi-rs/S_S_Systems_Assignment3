# setup.ps1 - one-step setup for Ballot Desk (run it from the project folder).
#
#   powershell -ExecutionPolicy Bypass -File .\setup.ps1                 setup only
#   powershell -ExecutionPolicy Bypass -File .\setup.ps1 -Run local      setup, then start the app
#   powershell -ExecutionPolicy Bypass -File .\setup.ps1 -Run docker     setup, then start Docker
#
# It is safe to run again: it never overwrites a key, a certificate or a secret you already have.
# This script contains no secrets, so it can be committed.

param(
    [ValidateSet('none', 'local', 'docker')]
    [string]$Run = 'none'
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

function Step([string]$message) { Write-Host "==> $message" -ForegroundColor Cyan }

function New-Secret {
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($bytes)
    $rng.Dispose()
    return (-join ($bytes | ForEach-Object { $_.ToString('x2') }))
}

# 1. Python
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw 'Python was not found. Install Python 3.11 or newer and tick "Add python.exe to PATH".'
}

# 2. Virtual environment and requirements
$venvPython = Join-Path $PSScriptRoot 'venv\Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
    Step 'Creating the virtual environment (venv)'
    python -m venv venv
}
Step 'Installing the requirements (this can take a minute)'
& $venvPython -m pip install --upgrade pip --quiet
& $venvPython -m pip install -r requirements.txt --quiet

# 3. PII encryption key (GR-18)
$keyFile = Join-Path $PSScriptRoot '.secrets\pii.key'
if (-not (Test-Path $keyFile)) {
    Step 'Creating the PII encryption key (.secrets\pii.key)'
    & $venvPython scripts\generate_pii_key.py
}
$piiKey = (Get-Content -Raw $keyFile).Trim()

# 4. The .env settings file
$envFile = Join-Path $PSScriptRoot '.env'
if (-not (Test-Path $envFile)) {
    Step 'Creating .env from .env.example'
    Copy-Item (Join-Path $PSScriptRoot '.env.example') $envFile
}
$script:lines = @(Get-Content $envFile)

function Set-Setting([string]$name, [string]$value, [scriptblock]$needsChange) {
    $found = $false
    for ($i = 0; $i -lt $script:lines.Count; $i++) {
        if ($script:lines[$i] -match "^$name=(.*)$") {
            $found = $true
            if (& $needsChange $Matches[1].Trim()) { $script:lines[$i] = "$name=$value" }
        }
    }
    if (-not $found) { $script:lines += "$name=$value" }
}

$isPlaceholder = { param($v) ($v -eq '') -or ($v -like 'change-me*') }
$isEmpty = { param($v) $v -eq '' }

Step 'Filling in the secrets in .env (only the ones still empty or "change-me")'
foreach ($name in 'SECRET_KEY', 'JWT_SECRET_KEY', 'RESULTS_KEY_SECRET', 'DELEGATE_KEY_SECRET') {
    Set-Setting $name (New-Secret) $isPlaceholder
}
Set-Setting 'PII_ENCRYPTION_KEY' $piiKey $isEmpty
Set-Content -Path $envFile -Value $script:lines -Encoding ascii

# 5. Local HTTPS certificate for Docker/nginx (GR-17)
$crt = Join-Path $PSScriptRoot 'nginx\certs\localhost.crt'
$key = Join-Path $PSScriptRoot 'nginx\certs\localhost.key'
if (-not (Test-Path $crt) -and -not (Test-Path $key)) {
    Step 'Creating the local HTTPS certificate (nginx\certs)'
    & $venvPython scripts\generate_certificate.py
}

Write-Host ''
Write-Host 'Setup finished.' -ForegroundColor Green
Write-Host '  Run the app:    .\venv\Scripts\Activate.ps1  then  python run.py   ->  http://localhost:8080'
Write-Host '  Run Docker:     docker compose up --build                          ->  https://localhost:8443'
Write-Host '  Sign-in codes:  python scripts\totp_codes.py --watch'
Write-Host '                  (Docker: docker compose exec web python scripts/totp_codes.py)'
Write-Host '  Do not run the app and Docker at the same time: both use port 8080.'
Write-Host ''

# 6. Optional: start straight away
if ($Run -eq 'local') {
    Step 'Starting the app on http://localhost:8080 (Ctrl+C to stop)'
    & $venvPython run.py
}
elseif ($Run -eq 'docker') {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw 'Docker was not found. Install and start Docker Desktop first.'
    }
    Step 'Starting Docker (Ctrl+C to stop)'
    docker compose up --build
}
