"""Sismómetro mk2 — Raspberry Pi Pico.

Cada ciclo:
    1. ADC0 (GP26) a 500 Hz durante 4.096 s (2048 muestras).
    2. Se resta la media, ventana de Hann y FFT.
    3. Parábola sobre el log de los tres bins del pico, corregida con la
       respuesta de la Hann para no inflar V_pico entre dos bins.
    4. Se invierte H_v(f) para obtener la velocidad y el desplazamiento de la mesa.

La línea que empieza por D es la medición, en este orden:
    f_Hz, V_pico_V, Ydot_m_s, Y_m, H_Vsm
La línea S y la siguiente (voltios separados por comas) son 5 periodos
de la bobina para dibujar la senoide.

Sube a la Pico, junto a este archivo:
    config.py  fft_radix2.py  espectro.py  modelo.py  adquisicion.py
"""

import math
import time

from adquisicion import Adquisidor
from config import (
    FN_HZ,
    FS_HZ,
    KEM,
    M_EF_KG,
    M_F_KG,
    N_MUESTRAS,
    PERIODO_US,
    S_INF,
    V_CENTRO_V,
    ZETA,
    linea_edo,
    linea_voltaje,
)
from espectro import analizar, preparar, recorte_seno
from modelo import invertir, velocidad_relativa

_DURACION_S = N_MUESTRAS * PERIODO_US / 1000000.0


def _db(relacion):
    if relacion <= 0.0 or relacion >= 1e8:
        return 0.0
    return 20.0 * math.log10(relacion)


def imprimir(esp, inv, clips, atrasos, t_cap_ms, t_fft_ms):
    print("")
    print("========== bloque ==========")
    print(
        "captura {:d} ms   fft {:d} ms   clips {:d}   atrasos {:d}".format(
            t_cap_ms, t_fft_ms, clips, atrasos
        )
    )
    print(
        "V_media = {:.4f} V   Vpp_bloque = {:.2f} mV   V_rms = {:.2f} mV".format(
            esp.v_media, esp.vpp * 1000.0, esp.v_rms * 1000.0
        )
    )
    if abs(esp.v_media - V_CENTRO_V) > 0.15:
        print("aviso: V_media lejos de 1.65 V — revisa el divisor de ADC0")
    if clips:
        print("aviso: el ADC tocó 0 V o 3.3 V — baja la ganancia")
    if atrasos:
        print("aviso: hubo muestras atrasadas; la fs media se sostiene, sube el ruido")

    if not esp.valido or inv is None:
        print(
            "sin fundamental ({:s}): candidato {:.3f} Hz, {:.2f} mV, pico/mediana {:.1f}".format(
                esp.motivo, esp.f_hz, esp.v_pico * 1000.0, esp.snr
            )
        )
        print("===========================")
        return

    omega = 2.0 * math.pi * esp.f_hz
    h_v, ydot, y = inv
    zdot = velocidad_relativa(esp.v_pico)
    z = zdot / omega
    a_mesa = ydot * omega
    print(
        "f = {:.4f} Hz   (bin {:.4f} Hz, p = {:+.3f})".format(
            esp.f_hz, esp.f_bin_hz, esp.p
        )
    )
    print(
        "V_pico = {:.2f} mV    V_pp = {:.2f} mV".format(
            esp.v_pico * 1000.0, esp.v_pico * 2000.0
        )
    )
    print(
        "H_v = {:.3f} V*s/m    r = f/fn = {:.3f}".format(h_v, esp.f_hz / FN_HZ)
    )
    print(
        "mesa:  Y = {:.4f} mm    Y_punto = {:.2f} mm/s    a = {:.3f} m/s^2".format(
            y * 1000.0, ydot * 1000.0, a_mesa
        )
    )
    print(
        "masa:  |z| = {:.4f} mm    |z_punto| = {:.2f} mm/s".format(
            z * 1000.0, zdot * 1000.0
        )
    )
    if esp.snr >= 1e8:
        snr_txt = "pico/mediana > 1e8"
    else:
        snr_txt = "pico/mediana = {:.1f} ({:.1f} dB)".format(esp.snr, _db(esp.snr))
    print(
        "{:s}    2o bin {:.2f} Hz ({:.2f} mV)".format(
            snr_txt, esp.f2_hz, esp.v2_pico * 1000.0
        )
    )
    print(
        "D\t{:.6f}\t{:.6f}\t{:.6e}\t{:.6e}\t{:.4f}".format(
            esp.f_hz, esp.v_pico, ydot, y, h_v
        )
    )
    print("===========================")


def imprimir_onda(volts, f_hz):
    rec = recorte_seno(volts, FS_HZ, f_hz)
    if rec is None:
        return
    muestras, amp, fase = rec
    print(
        "S\t{:d}\t{:.6e}\t{:.6f}\t{:.6f}\t{:.6f}".format(
            len(muestras), amp, fase, FS_HZ, f_hz
        )
    )
    print(",".join("{:.5f}".format(v) for v in muestras))


def presentacion():
    relacion = M_F_KG / M_EF_KG
    kem_desde_s = S_INF / relacion
    print("Sismometro mk2")
    print(
        "ADC0 GP26   fs = {:.1f} Hz   N = {:d}   T = {:.3f} s".format(
            FS_HZ, N_MUESTRAS, _DURACION_S
        )
    )
    print(
        "fn = {:.2f} Hz   zeta = {:.3f}   S_inf = {:.3f} V*s/m   Kem = {:.2f} V*s/m".format(
            FN_HZ, ZETA, S_INF, KEM
        )
    )
    print(
        "H(f) = {:.3f} * r^2 / sqrt((1-r^2)^2 + ({:.3f}*r)^2),  r = f/{:.2f}".format(
            S_INF, 2.0 * ZETA, FN_HZ
        )
    )
    print(linea_edo())
    print(linea_voltaje())
    print(
        "m_f/m_ef = {:.3f}   Kem desde S_inf = {:.2f} V*s/m".format(
            relacion, kem_desde_s
        )
    )
    print("columnas D: f_Hz  V_pico_V  Ydot_m_s  Y_m  H_Vsm")
    print("capturando {:.3f} s por bloque".format(_DURACION_S))


def main():
    time.sleep_ms(400)
    preparar(N_MUESTRAS)
    acq = Adquisidor()
    presentacion()
    while True:
        print("")
        print("capturando...")
        t0 = time.ticks_ms()
        volts = acq.capturar()
        t1 = time.ticks_ms()
        print("fft...")
        esp = analizar(volts, FS_HZ)
        t2 = time.ticks_ms()
        inv = None
        if esp.valido:
            inv = invertir(esp.f_hz, esp.v_pico)
        imprimir(
            esp,
            inv,
            acq.clips,
            acq.atrasos,
            time.ticks_diff(t1, t0),
            time.ticks_diff(t2, t1),
        )
        if inv is not None:
            imprimir_onda(volts, esp.f_hz)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("")
        print("Detenido.")
