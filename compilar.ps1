# Genera dist\Sismometro-mk2.exe con el visor y el firmware dentro.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

python -m pip install -r requirements.txt pyinstaller

$archivos = @(
    "config.py",
    "fft_radix2.py",
    "espectro.py",
    "modelo.py",
    "adquisicion.py",
    "main.py"
)

$argumentos = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--onefile",
    "--windowed",
    "--name", "Sismometro-mk2",
    "--hidden-import", "montar",
    "--collect-submodules", "mpremote",
    "--collect-all", "pyqtgraph"
)

foreach ($archivo in $archivos) {
    $argumentos += @("--add-data", "${archivo};firmware")
}

$argumentos += "plot_fast.py"
python @argumentos
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Host "Listo: dist\Sismometro-mk2.exe"
