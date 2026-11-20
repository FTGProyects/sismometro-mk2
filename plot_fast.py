#!/usr/bin/env python3
"""Grafica en el PC lo que imprime la Pico en cada bloque.

Lee la linea
    D    f_Hz    V_pico_V    Ydot_m_s    Y_m    H_Vsm
y, en cada bloque valido, cinco periodos de la bobina:
    S    n    amp_V    fase_rad    fs    f_Hz
    v0,v1,v2,...
Dibuja esa senoide suave encima de las muestras, mas el historial de f y de Y.
"""

from __future__ import annotations

import argparse
import math
import sys
import threading
import time
from collections import deque

import numpy as np
import pyqtgraph as pg
import serial
from PyQt6 import QtCore, QtWidgets
from serial.tools import list_ports

PICO_VID = 0x2E8A
BAUD = 115200
UI_HZ = 10
VENTANA_S = 180.0
SILENCIO_S = 90.0


def parse_d(line: str) -> tuple[float, float, float, float, float] | None:
    """f_Hz, V_pico_V, Ydot_m_s, Y_m, H. None si la linea no es una medicion."""
    if not line.startswith("D\t"):
        return None
    partes = line.split("\t")
    if len(partes) != 6:
        return None
    try:
        vals = tuple(float(p) for p in partes[1:])
    except ValueError:
        return None
    if len(vals) != 5 or not all(math.isfinite(v) for v in vals):
        return None
    return vals  # type: ignore[return-value]


def parse_s(line: str) -> dict[str, float] | None:
    """Cabecera de la onda: n, amp_V, fase, fs, f_Hz."""
    if not line.startswith("S\t"):
        return None
    partes = line.split("\t")
    if len(partes) != 6:
        return None
    try:
        n = int(partes[1])
        amp = float(partes[2])
        fase = float(partes[3])
        fs = float(partes[4])
        f_hz = float(partes[5])
    except ValueError:
        return None
    if n < 8 or fs <= 0.0 or f_hz <= 0.0 or not math.isfinite(amp):
        return None
    return {"n": float(n), "amp": amp, "fase": fase, "fs": fs, "f": f_hz}


def parse_muestras(line: str) -> list[float] | None:
    if "," not in line:
        return None
    try:
        vals = [float(p) for p in line.split(",") if p]
    except ValueError:
        return None
    if len(vals) < 8 or not all(math.isfinite(v) for v in vals):
        return None
    return vals


def probar() -> int:
    med = parse_d("D\t25.370000\t0.340000\t8.314000e-02\t5.215000e-04\t4.0900")
    if med is None:
        print("no leyo la linea D", file=sys.stderr)
        return 1
    f, v, ydot, y, h = med
    if abs(f - 25.37) > 1e-9 or abs(v - 0.34) > 1e-9:
        print("valores mal leidos", med, file=sys.stderr)
        return 1
    if abs(ydot - 0.08314) > 1e-9 or abs(y - 5.215e-4) > 1e-12 or abs(h - 4.09) > 1e-9:
        print("notacion cientifica mal leida", med, file=sys.stderr)
        return 1
    if parse_d("capturando...") is not None or parse_d("D\t1\t2") is not None:
        print("acepto una linea que no es medicion", file=sys.stderr)
        return 1
    cab = parse_s("S\t22\t1.200000e-01\t0.700000\t500.000000\t115.000000")
    if cab is None or abs(cab["f"] - 115.0) > 1e-9 or abs(cab["amp"] - 0.12) > 1e-9:
        print("no leyo la cabecera S", cab, file=sys.stderr)
        return 1
    if parse_muestras("0.1,0.2,0.0,-0.1,-0.2,0.0,0.1,0.2") is None:
        print("no leyo las muestras", file=sys.stderr)
        return 1
    print("OK")
    return 0


def buscar_puerto() -> str | None:
    for info in list_ports.comports():
        if info.vid in (PICO_VID, 11914):
            return info.device
    for info in list_ports.comports():
        desc = (info.description or "").lower()
        if "usb" in desc and "bluetooth" not in desc:
            return info.device
    return None


def abrir_serial(puerto: str, intentos: int, espera_s: float = 0.5) -> serial.Serial | None:
    ultimo: Exception | None = None
    for _ in range(max(1, intentos)):
        try:
            ser = serial.Serial()
            ser.port = puerto
            ser.baudrate = BAUD
            ser.timeout = 0.2
            # DTR en alto: para la Pico eso significa "hay un terminal".
            # Con DTR en bajo, MicroPython tira todo el print.
            ser.dtr = True
            ser.rts = False
            ser.open()
            return ser
        except (serial.SerialException, OSError) as exc:
            ultimo = exc
            time.sleep(espera_s)
    if ultimo is not None:
        print(ultimo, file=sys.stderr)
    return None


def arrancar_main(ser: serial.Serial) -> None:
    """Si la Pico se quedó en >>>, un soft reset vuelve a correr main.py."""
    ser.dtr = True
    ser.rts = False
    time.sleep(0.05)
    ser.write(b"\x03")
    time.sleep(0.06)
    ser.write(b"\x03")
    time.sleep(0.15)
    try:
        ser.reset_input_buffer()
    except Exception:
        pass
    ser.write(b"\x04")


class LectorSerial:
    """Lee el USB de la Pico. Cada D es un bloque de 4.096 s."""

    def __init__(self, puerto: str, intentos: int) -> None:
        self.puerto = puerto
        self.intentos = intentos
        self._ser: serial.Serial | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._last = 0.0
        self._t0: float | None = None
        self._n = 0
        self.t: deque[float] = deque(maxlen=500)
        self.f: deque[float] = deque(maxlen=500)
        self.y_mm: deque[float] = deque(maxlen=500)
        self.ultima: dict[str, float] | None = None
        self.onda: dict[str, np.ndarray | float] | None = None
        self._espera_muestras: dict[str, float] | None = None
        self.estado = "Conectando..."
        threading.Thread(target=self._bucle, daemon=True, name="serial").start()

    def _bucle(self) -> None:
        primero = True
        while not self._stop.is_set():
            n = self.intentos if primero else 3
            primero = False
            ser = abrir_serial(self.puerto, n)
            if ser is None:
                with self._lock:
                    self.estado = (
                        "No se pudo abrir " + self.puerto + ". Cierra Thonny si lo tiene."
                    )
                time.sleep(1.0)
                continue
            self._ser = ser
            with self._lock:
                self.estado = "Arrancando main.py en " + self.puerto
            try:
                arrancar_main(ser)
            except serial.SerialException:
                try:
                    ser.close()
                except Exception:
                    pass
                self._ser = None
                continue
            while not self._stop.is_set():
                try:
                    raw = ser.readline()
                except serial.SerialException:
                    break
                if not raw:
                    continue
                self._last = time.monotonic()
                self._linea(raw.decode("utf-8", errors="ignore").strip())
            try:
                ser.close()
            except Exception:
                pass
            self._ser = None
            if not self._stop.is_set():
                with self._lock:
                    self.estado = "Puerto cerrado, reintentando..."
                time.sleep(0.6)

    def _guardar_onda(self, meta: dict[str, float], ys: list[float]) -> None:
        n = len(ys)
        fs = meta["fs"]
        f_hz = meta["f"]
        amp = meta["amp"]
        fase = meta["fase"]
        y = np.asarray(ys, dtype=np.float64) * 1000.0
        t = np.arange(n, dtype=np.float64) / fs * 1000.0
        n_curvas = max(400, int(round((n - 1) / fs * f_hz * 90)))
        if n_curvas > 1400:
            n_curvas = 1400
        tt = np.linspace(0.0, (n - 1) / fs, n_curvas)
        yy = amp * np.sin(2.0 * math.pi * f_hz * tt + fase) * 1000.0
        amp_mv = abs(amp) * 1000.0
        with self._lock:
            y_mesa = 0.0 if self.ultima is None else float(self.ultima["y_mm"])
            escala = (y_mesa / amp_mv) if amp_mv > 1e-9 else 0.0
            self.onda = {
                "t": t,
                "y": y,
                "tf": tt * 1000.0,
                "yf": yy,
                "yp": y * escala,
                "ypf": yy * escala,
                "f": f_hz,
                "amp_mv": amp_mv,
                "y_mm": y_mesa,
            }

    def _linea(self, line: str) -> None:
        if self._espera_muestras is not None:
            meta = self._espera_muestras
            self._espera_muestras = None
            ys = parse_muestras(line)
            if ys is not None:
                self._guardar_onda(meta, ys)
                with self._lock:
                    self.estado = "onda {:.2f} Hz".format(meta["f"])
                return
        if not line or set(line) <= set("= "):
            return
        cab = parse_s(line)
        if cab is not None:
            self._espera_muestras = cab
            return
        med = parse_d(line)
        now = time.monotonic()
        if self._t0 is None:
            self._t0 = now
        t = now - self._t0
        with self._lock:
            if med is None:
                self.estado = line
                if line.startswith("sin fundamental"):
                    self.t.append(t)
                    self.f.append(float("nan"))
                    self.y_mm.append(float("nan"))
                    self.ultima = None
                return
            f_hz, v_pico, ydot, y_m, h_v = med
            self.t.append(t)
            self.f.append(f_hz)
            self.y_mm.append(y_m * 1000.0)
            self._n += 1
            self.ultima = {
                "f": f_hz,
                "v_pico": v_pico,
                "ydot": ydot,
                "y_mm": y_m * 1000.0,
                "h": h_v,
            }
            self.estado = "bloque {:d}".format(self._n)

    def ahora(self) -> float:
        if self._t0 is None:
            return 0.0
        return time.monotonic() - self._t0

    def snapshot(self) -> dict:
        with self._lock:
            last = self._last
            return {
                "t": np.asarray(self.t, dtype=np.float64),
                "f": np.asarray(self.f, dtype=np.float64),
                "y": np.asarray(self.y_mm, dtype=np.float64),
                "ultima": None if self.ultima is None else dict(self.ultima),
                "onda": self.onda,
                "estado": self.estado,
                "n": self._n,
                "vivo": last > 0.0 and (time.monotonic() - last) < SILENCIO_S,
            }

    def cerrar(self) -> None:
        self._stop.set()
        ser = self._ser
        if ser is not None and ser.is_open:
            try:
                ser.close()
            except Exception:
                pass


class Ventana(QtWidgets.QMainWindow):
    def __init__(self, puerto: str, intentos: int) -> None:
        super().__init__()
        self.puerto = puerto
        self.intentos = intentos
        self.lector: LectorSerial | None = None

        self.setWindowTitle("Sismometro mk2")
        self.resize(1100, 1040)

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout(central)

        self.lbl_hz = QtWidgets.QLabel("— Hz")
        self.lbl_hz.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        fuente = self.lbl_hz.font()
        fuente.setPointSize(28)
        fuente.setBold(True)
        self.lbl_hz.setFont(fuente)

        self.lbl_info = QtWidgets.QLabel("Conectando...")
        self.lbl_info.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.lbl_info.setWordWrap(True)
        layout.addWidget(self.lbl_hz)
        layout.addWidget(self.lbl_info)

        pg.setConfigOptions(antialias=True, useOpenGL=False, background="#12141a", foreground="#d5d8e0")
        self.plot_s = pg.PlotWidget(title="Bobina")
        self.plot_s.setLabel("left", "V", units="mV")
        self.plot_s.setLabel("bottom", "tiempo", units="ms")
        self.plot_s.showGrid(x=True, y=True, alpha=0.22)
        self.plot_s.enableAutoRange(x=False, y=False)
        self.plot_s.addLine(y=0, pen=pg.mkPen(255, 255, 255, 45))
        self.plot_s.addLegend(offset=(8, 8))
        self.curve_raw = self.plot_s.plot(
            pen=pg.mkPen(150, 175, 205, 210, width=1.2),
            symbol=None,
            name="muestras",
        )
        self.curve_fit = self.plot_s.plot(
            pen=pg.mkPen("#ffd166", width=2.6),
            name="seno",
        )
        layout.addWidget(self.plot_s, stretch=3)

        self.plot_f = pg.PlotWidget(title="Frecuencia")
        self.plot_y = pg.PlotWidget(title="Desplazamiento de la mesa")
        self.plot_f.setLabel("left", "f", units="Hz")
        self.plot_y.setLabel("left", "Y", units="mm")
        self.plot_y.setLabel("bottom", "tiempo", units="s")
        self.plot_f.showAxis("bottom", False)
        self.plot_y.setXLink(self.plot_f)
        for plot in (self.plot_f, self.plot_y):
            plot.showGrid(x=True, y=True, alpha=0.25)
            plot.enableAutoRange(x=False, y=False)
        self.curve_f = self.plot_f.plot(
            pen=pg.mkPen("#c0392b", width=2),
            symbol="o",
            symbolSize=7,
            symbolBrush="#c0392b",
            connect="finite",
        )
        self.curve_y = self.plot_y.plot(
            pen=pg.mkPen("#1d6fbf", width=2),
            symbol="o",
            symbolSize=7,
            symbolBrush="#1d6fbf",
            connect="finite",
        )
        self.plot_p = pg.PlotWidget(title="Posición")
        self.plot_p.setLabel("left", "Y", units="mm")
        self.plot_p.setLabel("bottom", "tiempo", units="ms")
        self.plot_p.showGrid(x=True, y=True, alpha=0.25)
        self.plot_p.enableAutoRange(x=False, y=False)
        self.plot_p.addLine(y=0, pen=pg.mkPen(255, 255, 255, 45))
        self.curve_p_raw = self.plot_p.plot(pen=pg.mkPen(120, 210, 170, 200, width=1.2), symbol=None)
        self.curve_p = self.plot_p.plot(pen=pg.mkPen("#3ddc97", width=2.4))
        for plot in (self.plot_f, self.plot_y, self.plot_p):
            plot.setMinimumHeight(150)
        layout.addWidget(self.plot_f, stretch=1)
        layout.addWidget(self.plot_y, stretch=1)
        layout.addWidget(self.plot_p, stretch=1)

        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._tick)

    def iniciar(self) -> None:
        self.lector = LectorSerial(self.puerto, self.intentos)
        self._timer.start(1000 // UI_HZ)

    def _tick(self) -> None:
        if self.lector is None:
            return
        s = self.lector.snapshot()
        ultima = s["ultima"]
        if ultima is None:
            self.lbl_hz.setText("— Hz")
            detalle = "esperando un bloque valido"
        else:
            a = ultima["ydot"] * 2.0 * math.pi * ultima["f"]
            self.lbl_hz.setText("{:.3f} Hz".format(ultima["f"]))
            detalle = (
                "Y = {:.4f} mm    v = {:.2f} mm/s    a = {:.2f} m/s²    "
                "Vpp = {:.1f} mV    H = {:.3f} V·s/m    {:d} bloques"
            ).format(
                ultima["y_mm"],
                ultima["ydot"] * 1000.0,
                a,
                ultima["v_pico"] * 2000.0,
                ultima["h"],
                s["n"],
            )
        estado = str(s["estado"])
        if (
            estado.startswith("No se pudo")
            or estado.startswith("Conectando")
            or estado.startswith("Puerto")
            or estado.startswith("Arrancando")
        ):
            self.lbl_info.setText(estado)
        elif not s["vivo"] and s["n"] == 0:
            self.lbl_info.setText(
                "Sin datos en {} — cierra Thonny si tiene el puerto".format(self.puerto)
            )
        elif not s["vivo"]:
            self.lbl_info.setText("Sin datos recientes    ·    {}".format(detalle))
        else:
            self.lbl_info.setText("{}    ·    {}".format(estado, detalle))

        onda = s.get("onda")
        if onda is not None:
            self.plot_s.setTitle(
                "Bobina  ·  {:.3f} Hz  ·  {:.1f} mV pico".format(onda["f"], onda["amp_mv"])
            )
            self.curve_raw.setData(onda["t"], onda["y"])
            self.curve_fit.setData(onda["tf"], onda["yf"])
            if onda["t"].size <= 90:
                self.curve_raw.setSymbol("o")
                self.curve_raw.setSymbolSize(7)
                self.curve_raw.setSymbolBrush(pg.mkBrush(150, 190, 230, 220))
                self.curve_raw.setSymbolPen(None)
            else:
                self.curve_raw.setSymbol(None)
            tmax = float(onda["tf"][-1])
            self.plot_s.setXRange(0.0, max(tmax, 1.0), padding=0.01)
            pico = max(
                float(np.max(np.abs(onda["y"]))),
                float(np.max(np.abs(onda["yf"]))),
                0.5,
            )
            self.plot_s.setYRange(-pico * 1.22, pico * 1.22, padding=0)
            self.plot_p.setTitle(
                "Posición  ·  {:.3f} Hz  ·  {:.4f} mm".format(onda["f"], onda["y_mm"])
            )
            self.curve_p_raw.setData(onda["t"], onda["yp"])
            self.curve_p.setData(onda["tf"], onda["ypf"])
            if onda["t"].size <= 90:
                self.curve_p_raw.setSymbol("o")
                self.curve_p_raw.setSymbolSize(6)
                self.curve_p_raw.setSymbolBrush(pg.mkBrush(120, 210, 170, 220))
                self.curve_p_raw.setSymbolPen(None)
            else:
                self.curve_p_raw.setSymbol(None)
            self.plot_p.setXRange(0.0, max(tmax, 1.0), padding=0.01)
            pico_y = max(float(np.max(np.abs(onda["yp"]))), float(np.max(np.abs(onda["ypf"]))), 1e-4)
            self.plot_p.setYRange(-pico_y * 1.22, pico_y * 1.22, padding=0)

        t = s["t"]
        if t.size:
            t_fin = self.lector.ahora()
            t0 = max(0.0, t_fin - VENTANA_S)
            m = t >= t0
            self.curve_f.setData(t[m], s["f"][m])
            self.curve_y.setData(t[m], s["y"][m])
            self.plot_f.setXRange(t0, max(t_fin, t0 + 1.0), padding=0)
            self._rango_y(self.plot_f, s["f"][m], 0.2)
            self._rango_y(self.plot_y, s["y"][m], 0.01)

    def _rango_y(self, plot: pg.PlotWidget, y: np.ndarray, piso: float) -> None:
        fin = y[np.isfinite(y)] if y.size else y
        if fin.size == 0:
            return
        lo = float(np.min(fin))
        hi = float(np.max(fin))
        pad = max((hi - lo) * 0.25, piso)
        plot.setYRange(lo - pad, hi + pad, padding=0)

    def closeEvent(self, event) -> None:
        self._timer.stop()
        if self.lector is not None:
            self.lector.cerrar()
        super().closeEvent(event)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port")
    ap.add_argument("--reconectar", type=int, default=25)
    ap.add_argument("--probar", action="store_true", help="solo comprueba el lector de la linea D")
    args = ap.parse_args(argv)
    if args.probar:
        return probar()

    puerto = args.port or buscar_puerto()
    if not puerto:
        print("No hay COM de la Pico. Usa --port COMx", file=sys.stderr)
        return 1

    app = QtWidgets.QApplication(sys.argv)
    win = Ventana(puerto, args.reconectar)
    win.show()
    QtCore.QTimer.singleShot(10, win.iniciar)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
