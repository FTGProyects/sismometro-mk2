# Abre la grafica de f y del desplazamiento de la mesa.
#   .\iniciar_grafica.ps1
#   .\iniciar_grafica.ps1 -Deploy
#   .\iniciar_grafica.ps1 -Deploy -Port COM5
# -Deploy copia el firmware y reinicia la Pico. Cierra Thonny antes.
param(
    [switch]$Deploy,
    [string]$Port
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if ($Deploy) {
    & "$PSScriptRoot\deploy_pico.ps1"
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
    Write-Host "Esperando a que la Pico reaparezca en el USB..."
    Start-Sleep -Seconds 3
}

$argumentos = @("plot_fast.py", "--reconectar", "25")
if ($Port) {
    $argumentos += @("--port", $Port)
}

& python @argumentos
exit $LASTEXITCODE
