[CmdletBinding()]
param(
    [switch]$Wipe
)

$ErrorActionPreference = "Stop"

if ($Wipe) {
    docker compose down -v
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Write-Host "Stopped and wiped volumes."
} else {
    docker compose down
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Write-Host "Stopped."
}
