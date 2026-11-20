# Copia el firmware a la Pico y la reinicia.
# Cierra Thonny y la grafica antes: si tienen el COM, la copia falla.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$archivos = @(
    "config.py",
    "fft_radix2.py",
    "espectro.py",
    "modelo.py",
    "adquisicion.py",
    "main.py"
)

foreach ($archivo in $archivos) {
    if (-not (Test-Path -LiteralPath $archivo)) {
        Write-Error "Falta $archivo"
    }
}

Write-Host "Subiendo firmware a la Pico..."
& python -m mpremote connect auto fs --force cp @archivos ':' '+' reset
if ($LASTEXITCODE -ne 0) {
    Write-Host "No se pudo copiar. Cierra Thonny y la grafica si tienen el puerto."
    exit $LASTEXITCODE
}

Write-Host "Pico reiniciada. main.py ya esta corriendo."
