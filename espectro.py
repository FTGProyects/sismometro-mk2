"""Ventana de Hann, espectro de amplitud e interpolación parabólica en log.

La escala es la del análisis de la mesa:

    mag[k] = 2 / (N * ganancia_coherente) * |X[k]|

con ganancia_coherente = sum(w) / N. Así mag[k] sale en voltios pico
de la fundamental, no en cuentas de la FFT.

La parábola sobre el log de los tres bins es el estimador pedido. Sobre una
Hann esa parábola deja el tono corrido (hasta ~0.016 bin) y la amplitud
hasta ~2.5 % alta entre dos bins. La respuesta conocida de la Hann,

    G(d) = |sin(pi*d) / (pi*d*(1 - d*d))|,

se invierte para pasar de esa fracción p al desplazamiento real d del bin
y a V_pico = mag[k] / G(d). En el centro del bin G = 1 y no cambia nada.
"""

import math

from config import F_MAX_HZ, F_MIN_HZ, SNR_MIN, V_PICO_MIN_V, arreglo
from fft_radix2 import fft_inplace

_w = None
_cg = 1.0
_re = None
_im = None
_mag = None


class Espectro:
    def __init__(self):
        self.valido = False
        self.motivo = "vacio"
        self.f_hz = 0.0
        self.f_bin_hz = 0.0
        self.p = 0.0
        self.v_pico = 0.0
        self.v_rms = 0.0
        self.vpp = 0.0
        self.v_media = 0.0
        self.snr = 0.0
        self.k = 0
        self.f2_hz = 0.0
        self.v2_pico = 0.0
        self.cg = 0.0


def preparar(n):
    """Reserva la ventana y los buffers una sola vez (el heap de la Pico es justo)."""
    global _w, _cg, _re, _im, _mag
    if _w is not None and len(_w) == n:
        return
    if n < 8 or (n & (n - 1)) != 0:
        raise ValueError("N debe ser potencia de 2")
    w = arreglo("f", n, 0.0)
    acc = 0.0
    paso = (2.0 * math.pi / (n - 1)) if n > 1 else 0.0
    for i in range(n):
        wi = 0.5 * (1.0 - math.cos(paso * i))
        w[i] = wi
        acc += wi
    _w = w
    _cg = acc / n
    _re = arreglo("f", n, 0.0)
    _im = arreglo("f", n, 0.0)
    _mag = arreglo("f", n // 2 + 1, 0.0)


def _centrar(volts):
    n = len(volts)
    acc = 0.0
    for i in range(n):
        acc += volts[i]
    media = acc / n
    for i in range(n):
        volts[i] -= media
    return media


def _estadistica(volts):
    n = len(volts)
    acc2 = 0.0
    vmin = volts[0]
    vmax = volts[0]
    for i in range(n):
        x = volts[i]
        acc2 += x * x
        if x < vmin:
            vmin = x
        elif x > vmax:
            vmax = x
    return math.sqrt(acc2 / n), vmax - vmin


def _magnitud(n, cg):
    """Amplitud unilateral corregida por la ganancia coherente de la Hann."""
    re = _re
    im = _im
    mag = _mag
    esc = 1.0 / (n * cg)
    mag[0] = esc * math.sqrt(re[0] * re[0] + im[0] * im[0])
    dos = 2.0 * esc
    mitad = n // 2
    for k in range(1, mitad):
        mag[k] = dos * math.sqrt(re[k] * re[k] + im[k] * im[k])
    mag[mitad] = esc * math.sqrt(re[mitad] * re[mitad] + im[mitad] * im[mitad])


def _limites(n, fs, f_min, f_max):
    k_min = int(f_min * n / fs)
    if k_min < 1:
        k_min = 1
    k_max = int(f_max * n / fs)
    tope = n // 2 - 1
    if k_max > tope:
        k_max = tope
    return k_min, k_max


def _mediana(k_min, k_max):
    banda = []
    mag = _mag
    for k in range(k_min, k_max + 1):
        banda.append(mag[k])
    banda.sort()
    return banda[len(banda) // 2]


def _parabola_log(k):
    """Fracción p de la parábola sobre el log. Queda en [-0.5, 0.5]."""
    mag = _mag
    izquierda = mag[k - 1]
    centro = mag[k]
    derecha = mag[k + 1]
    if izquierda <= 0.0 or centro <= 0.0 or derecha <= 0.0:
        return 0.0
    alpha = math.log(izquierda)
    beta = math.log(centro)
    gamma = math.log(derecha)
    den = alpha - 2.0 * beta + gamma
    if abs(den) <= 1e-12:
        return 0.0
    p = 0.5 * (alpha - gamma) / den
    if p > 0.5:
        return 0.5
    if p < -0.5:
        return -0.5
    return p


def _ganancia_hann(delta):
    """G(d) de la Hann, 1 en el centro del bin y ~0.849 a mitad de bin."""
    if abs(delta) < 1e-6:
        return 1.0
    den = math.pi * delta * (1.0 - delta * delta)
    if abs(den) < 1e-8:
        return 0.0
    return abs(math.sin(math.pi * delta) / den)


def _p_de_hann(delta):
    """p que devolvería la parábola logarítmica con un tono a `delta` bins."""
    if abs(delta) < 1e-7:
        return 0.0
    izq = _ganancia_hann(delta + 1.0)
    cen = _ganancia_hann(delta)
    der = _ganancia_hann(delta - 1.0)
    if izq <= 0.0 or cen <= 0.0 or der <= 0.0:
        return delta
    alpha = math.log(izq)
    beta = math.log(cen)
    gamma = math.log(der)
    den = alpha - 2.0 * beta + gamma
    if abs(den) < 1e-12:
        return delta
    return 0.5 * (alpha - gamma) / den


def _delta_de_p(p):
    """Quita el sesgo de la parábola. p(delta) es impar y creciente."""
    if p > 0.5:
        p = 0.5
    elif p < -0.5:
        p = -0.5
    lo = -0.5
    hi = 0.5
    for _ in range(30):
        mid = 0.5 * (lo + hi)
        if _p_de_hann(mid) < p:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def _segundo_pico(k_pico, k_min, k_max, fs, n):
    mag = _mag
    mejor = 0.0
    k2 = -1
    for k in range(k_min, k_max + 1):
        if abs(k - k_pico) <= 3:
            continue
        if mag[k] > mejor:
            mejor = mag[k]
            k2 = k
    if k2 < 0:
        return 0.0, 0.0
    return k2 * fs / n, mejor


def analizar(volts, fs, f_min=F_MIN_HZ, f_max=F_MAX_HZ):
    """Quita la media (el 1.65 V), aplica Hann y devuelve la fundamental."""
    n = len(volts)
    preparar(n)
    esp = Espectro()
    esp.cg = _cg
    esp.v_media = _centrar(volts)
    esp.v_rms, esp.vpp = _estadistica(volts)

    w = _w
    re = _re
    im = _im
    for i in range(n):
        re[i] = volts[i] * w[i]
        im[i] = 0.0
    fft_inplace(re, im)
    _magnitud(n, _cg)

    k_min, k_max = _limites(n, fs, f_min, f_max)
    if k_max <= k_min + 2:
        return esp

    mag = _mag
    k = k_min
    mejor = mag[k_min]
    for i in range(k_min + 1, k_max + 1):
        if mag[i] > mejor:
            mejor = mag[i]
            k = i
    esp.k = k
    df = fs / n
    esp.f_bin_hz = k * df

    if 0 < k < (n // 2):
        delta = _delta_de_p(_parabola_log(k))
    else:
        delta = 0.0
    esp.p = delta
    ganancia = _ganancia_hann(delta)
    if ganancia > 1e-6:
        esp.v_pico = mejor / ganancia
    else:
        esp.v_pico = mejor
    esp.f_hz = (k + delta) * df

    mediana = _mediana(k_min, k_max)
    if mediana > 1e-12:
        esp.snr = mejor / mediana
    elif mejor > 0.0:
        esp.snr = 1e9
    else:
        esp.snr = 0.0

    esp.f2_hz, esp.v2_pico = _segundo_pico(k, k_min, k_max, fs, n)

    if esp.v_pico < V_PICO_MIN_V:
        esp.motivo = "amplitud"
    elif esp.snr < SNR_MIN:
        esp.motivo = "snr"
    else:
        esp.valido = True
        esp.motivo = "ok"
    return esp


def recorte_seno(volts, fs, f_hz, periodos=5, max_muestras=420):
    """Trozo de unos pocos periodos y el seno que mejor lo sigue.

    Devuelve (muestras, amplitud_V, fase_rad) con t = 0 en la primera muestra,
    v(t) = amplitud * sin(2*pi*f*t + fase). None si no da para dibujar.
    """
    n = len(volts)
    if f_hz <= 0.0 or fs <= 0.0 or n < 16:
        return None
    ns = int(round(periodos * fs / f_hz))
    if ns < 16:
        ns = 16
    if ns > max_muestras:
        ns = max_muestras
    if ns > n:
        ns = n
    i0 = (n - ns) // 2
    w = 2.0 * math.pi * f_hz / fs
    sum_x_s = 0.0
    sum_x_c = 0.0
    sum_s2 = 0.0
    sum_c2 = 0.0
    sum_sc = 0.0
    muestras = []
    for i in range(ns):
        x = float(volts[i0 + i])
        muestras.append(x)
        si = math.sin(w * i)
        ci = math.cos(w * i)
        sum_x_s += x * si
        sum_x_c += x * ci
        sum_s2 += si * si
        sum_c2 += ci * ci
        sum_sc += si * ci
    det = sum_s2 * sum_c2 - sum_sc * sum_sc
    if abs(det) < 1e-18:
        return None
    a = (sum_x_s * sum_c2 - sum_x_c * sum_sc) / det
    b = (sum_x_c * sum_s2 - sum_x_s * sum_sc) / det
    return muestras, math.sqrt(a * a + b * b), math.atan2(b, a)
