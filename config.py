"""Constantes del sismómetro calibrado y del bloque que mide la Pico.

El ajuste lineal (10.50 Hz, 15.54 Hz y 25.37 Hz) fijó fn, zeta y S_inf.
S_inf = 3.835 V*s/m es el valor del ajuste; en el texto se redondea a 3.84.
Con ese valor la tabla de Vpp del modelo queda en 79.9, 239.9 y 680.6 mV.
"""

import array


def arreglo(tipo, n, valor):
    """array de n elementos. En MicroPython 1.29 `array * int` no existe."""
    return array.array(tipo, (valor for _ in range(n)))


# GP26 = ADC0. El divisor resistivo pone el reposo en 1.65 V.
ADC_PIN = 26
VREF_V = 3.3
ADC_MAX = 65535
V_CENTRO_V = 1.65
CLIP_MARGEN = 10

# 2048 muestras * 2000 us = 4.096 s. df = 500/2048 = 0.244140625 Hz.
PERIODO_US = 2000
FS_HZ = 1000000.0 / PERIODO_US
N_MUESTRAS = 2048

# Banda donde se busca la fundamental. 4 Hz queda dentro; el bin 0 no.
F_MIN_HZ = 1.0
F_MAX_HZ = 120.0

# Piso pensado para ver tonos de unos 3–4 mVpp tras la FFT.
V_PICO_MIN_V = 0.0015
SNR_MIN = 6.0

# Modelo identificado.
FN_HZ = 17.93
ZETA = 0.561
S_INF = 3.835
KEM = 12.30
M_EF_KG = 0.0664
M_F_KG = 0.0207
K_EF_N_M = 842.5
C_TOT_KG_S = 8.40
C_NL_KG_M = 3.8


def linea_edo():
    return (
        "{:.4f}*z'' + {:.2f}*z' + {:.1f}*|z'|*z' + {:.1f}*z = -{:.4f}*y''".format(
            M_EF_KG, C_TOT_KG_S, C_NL_KG_M, K_EF_N_M, M_F_KG
        )
    )


def linea_voltaje():
    return "V_adc = {:.2f} - {:.2f}*z'".format(V_CENTRO_V, KEM)
