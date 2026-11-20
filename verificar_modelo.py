"""Comprueba en el PC el mismo espectro y la misma H_v que corre en la Pico.

No usa el ADC. Genera senos, los pasa por espectro.analizar y compara
contra la tabla publicada del modelo calibrado.
"""

import math
import sys

from espectro import analizar, recorte_seno
from fft_radix2 import fft_inplace
from modelo import hv, invertir, vpp_mv

FS = 500.0
N = 2048

# Y en mm y Vpp en mV que imprimió el modelo calibrado (S_inf = 3.835).
TABLA_VPP = (
    (4.00, 0.400, 3.9),
    (10.50, 0.428, 79.9),
    (15.54, 0.428, 239.9),
    (25.37, 0.522, 680.6),
    (35.00, 0.522, 941.6),
)

# Puntos medidos: f, V_pico del osciloscopio, Y de la mesa en mm.
TABLA_MEDIDA = (
    (10.50, 0.040, 0.428),
    (15.54, 0.120, 0.428),
    (25.37, 0.340, 0.522),
)


def _fallo(msg):
    print("FALLO:", msg)
    return 1


def test_fft_contra_dft():
    n = 64
    src = [math.sin(i * 0.37) + 0.2 * math.cos(i * 0.11) for i in range(n)]
    re = src[:]
    im = [0.0] * n
    fft_inplace(re, im)
    peor = 0.0
    for k in range(n):
        sr = 0.0
        si = 0.0
        for t in range(n):
            ang = -2.0 * math.pi * k * t / n
            sr += src[t] * math.cos(ang)
            si += src[t] * math.sin(ang)
        peor = max(peor, abs(sr - re[k]), abs(si - im[k]))
    print("FFT vs DFT directa (N=64), error max = {:.3e}".format(peor))
    if peor > 1e-9:
        return _fallo("la FFT no coincide con la DFT directa ({:.3e})".format(peor))
    return 0


def _seno(f_hz, amp, fase, offset):
    buf = [0.0] * N
    w = 2.0 * math.pi * f_hz / FS
    for i in range(N):
        buf[i] = offset + amp * math.sin(w * i + fase)
    return buf


def test_tabla_vpp():
    print("")
    print("f_Hz     Y_mm    Vpp_modelo   Vpp_publicado   dif_mV")
    peor = 0.0
    for f_hz, y_mm, vpp_pub in TABLA_VPP:
        vpp = vpp_mv(f_hz, y_mm)
        dif = abs(vpp - vpp_pub)
        peor = max(peor, dif)
        print(
            "{:6.2f}   {:6.3f}   {:10.2f}   {:13.1f}   {:7.3f}".format(
                f_hz, y_mm, vpp, vpp_pub, vpp - vpp_pub
            )
        )
    if peor > 0.15:
        return _fallo("Vpp del modelo se aparta {:.3f} mV de la tabla".format(peor))
    return 0


def test_tono(f_hz, amp, fase):
    esp = analizar(_seno(f_hz, amp, fase, 1.65), FS)
    if not esp.valido:
        return _fallo("{:.3f} Hz rechazado ({:s})".format(f_hz, esp.motivo))
    err_f = abs(esp.f_hz - f_hz)
    err_v = abs(esp.v_pico - amp) / amp
    print(
        "tono {:7.3f} Hz fase {:5.2f}:  f = {:8.4f} (err {:7.4f} Hz)   "
        "V_pico = {:8.3f} mV (err {:6.3f} %)   V_media = {:.4f} V".format(
            f_hz,
            fase,
            esp.f_hz,
            esp.f_hz - f_hz,
            esp.v_pico * 1000.0,
            100.0 * (esp.v_pico - amp) / amp,
            esp.v_media,
        )
    )
    if err_f > 0.005:
        return _fallo("frecuencia {:.4f} Hz, error {:.4f} Hz".format(esp.f_hz, err_f))
    if err_v > 0.003:
        return _fallo("amplitud {:.6f} V, error relativo {:.4f}".format(esp.v_pico, err_v))
    if abs(esp.v_media - 1.65) > 0.02:
        return _fallo("la media no salió cerca de 1.65 V ({:.6f})".format(esp.v_media))
    return 0


def test_puntos_medidos():
    print("")
    print("Inversion de los puntos medidos (osciloscopio -> mesa):")
    for f_hz, v_pico, y_mm in TABLA_MEDIDA:
        h = hv(f_hz)
        inv = invertir(f_hz, v_pico)
        if inv is None:
            return _fallo("no se pudo invertir {:.2f} Hz".format(f_hz))
        _h, ydot, y = inv
        print(
            "  {:.2f} Hz   H = {:.3f} V*s/m   Y = {:.4f} mm (publicado {:.3f})   "
            "Y_punto = {:.2f} mm/s".format(
                f_hz, h, y * 1000.0, y_mm, ydot * 1000.0
            )
        )
        if abs(y * 1000.0 - y_mm) / y_mm > 0.01:
            return _fallo(
                "Y = {:.4f} mm no cierra con {:.3f} mm".format(y * 1000.0, y_mm)
            )
    return 0


def test_pipeline_medido():
    """El camino de la Pico: seno de V_pico conocido -> f, luego H_v -> Y."""
    print("")
    print("Pipeline FFT + H_v sobre los V_pico medidos:")
    for f_hz, v_pico, y_mm in TABLA_MEDIDA:
        esp = analizar(_seno(f_hz, v_pico, 0.7, 1.65), FS)
        if not esp.valido:
            return _fallo("pipeline rechazó {:.2f} Hz".format(f_hz))
        inv = invertir(esp.f_hz, esp.v_pico)
        if inv is None:
            return _fallo("pipeline sin H_v en {:.2f} Hz".format(f_hz))
        _h, ydot, y = inv
        err_f = abs(esp.f_hz - f_hz)
        err_y = abs(y * 1000.0 - y_mm) / y_mm
        print(
            "  {:.2f} Hz -> f = {:.4f} Hz (err {:+.4f})   Y = {:.4f} mm "
            "(publicado {:.3f}, err {:.2f} %)   Y_punto = {:.2f} mm/s".format(
                f_hz,
                esp.f_hz,
                esp.f_hz - f_hz,
                y * 1000.0,
                y_mm,
                100.0 * (y * 1000.0 - y_mm) / y_mm,
                ydot * 1000.0,
            )
        )
        if err_f > 0.005:
            return _fallo("pipeline, error de f = {:.4f} Hz".format(err_f))
        if err_y > 0.01:
            return _fallo("pipeline, error de Y = {:.2f} %".format(100.0 * err_y))
    return 0


def test_recorte_seno():
    print("")
    print("Recorte de 5 periodos (la curva que se dibuja):")
    for f_hz, amp, fase in ((12.0, 0.08, 0.4), (25.37, 0.34, 1.2), (115.0, 0.05, -0.8)):
        w = 2.0 * math.pi * f_hz / FS
        volts = [amp * math.sin(w * i + fase) for i in range(N)]
        rec = recorte_seno(volts, FS, f_hz)
        if rec is None:
            return _fallo("recorte vacio a {:.2f} Hz".format(f_hz))
        muestras, a_fit, p_fit = rec
        err_a = abs(a_fit - amp) / amp
        y0 = a_fit * math.sin(p_fit)
        err_y = abs(y0 - muestras[0])
        print(
            "  {:6.2f} Hz   {:d} muestras   amp err {:.3f} %   ajuste en t=0 {:.4f} mV".format(
                f_hz, len(muestras), 100.0 * err_a, err_y * 1000.0
            )
        )
        if err_a > 0.01 or err_y > 0.002 * max(1.0, amp):
            return _fallo("el seno no cae sobre las muestras a {:.2f} Hz".format(f_hz))
    return 0


def main():
    rc = 0
    rc |= test_fft_contra_dft()
    rc |= test_tabla_vpp()
    print("")
    print("Recuperacion de senos con offset 1.65 V:")
    for f_hz, amp, fase in (
        (4.00, 0.0020, 0.3),
        (10.50, 0.040, 1.1),
        (15.54, 0.120, 0.7),
        (24.5361328125, 0.200, 1.4),
        (25.3681, 0.340, 2.2),
        (35.00, 0.470, 0.0),
    ):
        rc |= test_tono(f_hz, amp, fase)
    rc |= test_puntos_medidos()
    rc |= test_pipeline_medido()
    rc |= test_recorte_seno()
    if rc == 0:
        print("")
        print("OK")
    return rc


if __name__ == "__main__":
    sys.exit(main())
