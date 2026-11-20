"""Copia el firmware a la Pico y la reinicia.

Los seis módulos viven junto a este archivo cuando se corre desde el
repositorio, y dentro del ejecutable cuando se abre el .exe.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ARCHIVOS = (
    "config.py",
    "fft_radix2.py",
    "espectro.py",
    "modelo.py",
    "adquisicion.py",
    "main.py",
)


class ErrorMontaje(Exception):
    pass


def directorio_firmware() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS"))
        empaquetado = base / "firmware"
        if empaquetado.is_dir():
            return empaquetado
        return base
    return Path(__file__).resolve().parent


def archivos() -> list[Path]:
    raiz = directorio_firmware()
    rutas = [raiz / nombre for nombre in ARCHIVOS]
    faltan = [ruta.name for ruta in rutas if not ruta.is_file()]
    if faltan:
        raise ErrorMontaje("Faltan archivos del firmware: " + ", ".join(faltan))
    return rutas


def montar(puerto: str | None = None) -> None:
    """Sube los seis módulos y hace un reset de la placa."""
    from mpremote.commands import CommandError, do_connect, do_disconnect, do_exec, do_filesystem
    from mpremote.main import State

    rutas = archivos()
    state = State()
    try:
        _conectar(state, do_connect, CommandError, puerto)
        try:
            do_filesystem(
                state,
                argparse.Namespace(
                    command=["cp"],
                    path=[str(ruta) for ruta in rutas] + [":"],
                    recursive=False,
                    force=True,
                    verbose=False,
                    size=False,
                    human=False,
                ),
            )
        except CommandError as exc:
            raise ErrorMontaje("La copia falló: " + str(exc)) from exc
        try:
            do_exec(
                state,
                argparse.Namespace(
                    expr=["import time, machine; time.sleep_ms(100); machine.reset()"],
                    follow=False,
                ),
            )
        except (CommandError, OSError):
            # El reset corta el USB a propósito. Los archivos ya quedaron copiados.
            pass
    finally:
        try:
            do_disconnect(state)
        except Exception:
            pass


def _conectar(state, do_connect, command_error, puerto: str | None) -> None:
    destino = puerto if puerto else "auto"
    try:
        do_connect(state, argparse.Namespace(device=[destino]))
    except command_error as exc:
        texto = str(exc).lower()
        if "no device" in texto:
            raise ErrorMontaje("No aparece ninguna Pico en el USB.") from exc
        if "failed to access" in texto or "in use" in texto or "permission" in texto:
            raise ErrorMontaje(
                "El puerto está ocupado. Cierra Thonny y vuelve a intentar."
            ) from exc
        raise ErrorMontaje("No se pudo abrir la Pico: " + str(exc)) from exc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Copia el firmware a la Pico y la reinicia.")
    ap.add_argument("--port", help="COM de la Pico. Si se omite, se busca sola.")
    args = ap.parse_args(argv)
    try:
        montar(args.port)
    except ErrorMontaje as exc:
        print(exc, file=sys.stderr)
        return 1
    print("Firmware copiado. Pico reiniciada.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
