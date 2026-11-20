"""Inversión de la respuesta calibrada del sismómetro de excitación por base.

La EDO identificada es

    m_ef*z'' + c_tot*z' + c_nl*|z'|*z' + k_ef*z = -m_f*y''
    V_adc = 1.65 - Kem*z'

La estimación en la Pico no integra esa EDO. Usa la función de transferencia
lineal que ya ajustó los tres puntos medidos:

    H_v(f) = S_inf * r^2 / sqrt((1 - r^2)^2 + (2*zeta*r)^2),   r = f / fn

    Y_punto = V_pico / H_v(f)
    Y       = Y_punto / (2*pi*f)

zeta y c_tot salen de ese ajuste lineal. El término 3.8*|z'|*z' queda en la
EDO como amortiguamiento cuadrático; no se vuelve a sumar encima de H_v,
porque si no la tabla de 80, 240 y 680 mV dejaría de cerrar.

Kem convierte V_pico en velocidad relativa de la masa, |z'|. Esa velocidad
no es la de la mesa: la inercia que ve la base es m_f, no m_ef, y
S_inf = Kem * (m_f / m_ef).
"""

import math

from config import FN_HZ, KEM, S_INF, ZETA


def hv(f_hz):
    """Sensibilidad bobina / velocidad de la mesa, en V*s/m."""
    if f_hz <= 0.0 or FN_HZ <= 0.0:
        return 0.0
    r = f_hz / FN_HZ
    r2 = r * r
    dos_zr = (2.0 * ZETA) * r
    den = math.sqrt((1.0 - r2) * (1.0 - r2) + dos_zr * dos_zr)
    if den < 1e-12:
        return 0.0
    return S_INF * (r2 / den)


def invertir(f_hz, v_pico_v):
    """Devuelve (H_v, Y_punto_m_s, Y_m) a partir del pico fundamental en voltios."""
    if f_hz <= 0.0 or v_pico_v < 0.0:
        return None
    h = hv(f_hz)
    if h < 1e-4:
        return None
    ydot = v_pico_v / h
    y = ydot / (2.0 * math.pi * f_hz)
    return h, ydot, y


def velocidad_relativa(v_pico_v):
    """|z'| de la masa, en m/s. Sale de V = Kem*|z'|, no de H_v."""
    if v_pico_v <= 0.0 or KEM <= 0.0:
        return 0.0
    return v_pico_v / KEM


def vpp_mv(f_hz, y_mm):
    """Vpp que predice el modelo si la mesa se mueve Y milímetros a f_hz."""
    if f_hz <= 0.0 or y_mm <= 0.0:
        return 0.0
    ydot = 2.0 * math.pi * f_hz * (y_mm / 1000.0)
    return 2.0 * hv(f_hz) * ydot * 1000.0
