# Copia el firmware a la Pico y la reinicia.
# Cierra Thonny y la grafica antes: si tienen el COM, la copia falla.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "Subiendo firmware a la Pico..."
& python montar.py
if ($LASTEXITCODE -ne 0) {
    Write-Host "No se pudo copiar. Cierra Thonny y la grafica si tienen el puerto."
    exit $LASTEXITCODE
}

Write-Host "Pico reiniciada. main.py ya esta corriendo."
