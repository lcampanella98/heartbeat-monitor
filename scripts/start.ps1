[CmdletBinding()]
param(
    [switch]$Demo,
    [switch]$Smtp
)

$ErrorActionPreference = "Stop"

$composeFiles = @("-f", "docker-compose.yml")
if ($Demo) {
    Write-Host "Activating demo mode..."
    $composeFiles += @("-f", "docker-compose.demo.yml")
}
if ($Smtp) {
    Write-Host "Activating SMTP mode..."
    $composeFiles += @("-f", "docker-compose.smtp.yml")
}

Write-Host "Starting heartbeat-monitor..."
docker compose @composeFiles up -d --build
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Waiting for backend..."
$ready = $false
for ($i = 1; $i -le 60; $i++) {
    try {
        $response = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/system/status" -ErrorAction Stop
        Write-Host "Ready at http://localhost:8000"
        Write-Host "check_source=$($response.check_source)  email_sink=$($response.email_sink)"
        $ready = $true
        break
    } catch {
        Start-Sleep -Seconds 1
    }
}

if (-not $ready) {
    Write-Error "ERROR: backend did not become ready within 60 seconds"
    exit 1
}
