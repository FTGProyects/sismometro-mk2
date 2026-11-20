"""FFT compleja radix-2, sin normalizar, mismo signo que numpy.fft.fft.

X[k] = sum_n x[n] * exp(-2*pi*i*k*n/N)
La magnitud no se divide por N: ese factor lo aplica el espectro.
"""

import math


def _es_potencia_de_dos(n):
    return n >= 2 and (n & (n - 1)) == 0


def fft_inplace(re, im):
    """Transforma re+j*im en el sitio. n = len(re) debe ser potencia de 2."""
    n = len(re)
    if n != len(im) or not _es_potencia_de_dos(n):
        raise ValueError("FFT: longitud invalida")

    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j ^= bit
        if i < j:
            re_i = re[i]
            im_i = im[i]
            re[i] = re[j]
            im[i] = im[j]
            re[j] = re_i
            im[j] = im_i

    length = 2
    while length <= n:
        half = length >> 1
        ang_base = -2.0 * math.pi / length
        wlen_re = math.cos(ang_base)
        wlen_im = math.sin(ang_base)
        for i0 in range(0, n, length):
            wr = 1.0
            wi = 0.0
            for k in range(half):
                if (k & 7) == 0:
                    ang = ang_base * k
                    wr = math.cos(ang)
                    wi = math.sin(ang)
                i1 = i0 + k
                i2 = i1 + half
                tr = wr * re[i2] - wi * im[i2]
                ti = wr * im[i2] + wi * re[i2]
                re[i2] = re[i1] - tr
                im[i2] = im[i1] - ti
                re[i1] += tr
                im[i1] += ti
                nwr = wr * wlen_re - wi * wlen_im
                wi = wr * wlen_im + wi * wlen_re
                wr = nwr
        length <<= 1
