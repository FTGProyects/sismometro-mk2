"""Bloque de N muestras en ADC0, con periodo fijo por ticks_us.

El plazo se adelanta siempre PERIOD_US, no a partir del instante en que
terminó la lectura. Así un retraso de un sample se recupera en el siguiente
y la fs media queda en 500 Hz. Un IRQ de USB puede atrasar una muestra;
no se desactivan las IRQ porque el bloque dura 4.096 s y el USB se caería.
"""

import gc
import time

from machine import ADC, Pin

from config import ADC_MAX, ADC_PIN, CLIP_MARGEN, N_MUESTRAS, PERIODO_US, VREF_V, arreglo


class Adquisidor:
    def __init__(self):
        self.raw = arreglo("H", N_MUESTRAS, 0)
        self.volts = arreglo("f", N_MUESTRAS, 0.0)
        self.adc = ADC(Pin(ADC_PIN))
        self.clips = 0
        self.atrasos = 0

    def capturar(self):
        n = N_MUESTRAS
        raw = self.raw
        adc = self.adc
        dt = PERIODO_US
        for _ in range(8):
            adc.read_u16()
        gc.collect()
        gc.disable()
        atrasos = 0
        try:
            t_next = time.ticks_add(time.ticks_us(), dt)
            for i in range(n):
                if time.ticks_diff(t_next, time.ticks_us()) > 0:
                    while time.ticks_diff(t_next, time.ticks_us()) > 0:
                        pass
                else:
                    atrasos += 1
                raw[i] = adc.read_u16()
                t_next = time.ticks_add(t_next, dt)
        finally:
            gc.enable()

        volts = self.volts
        escala = VREF_V / ADC_MAX
        clips = 0
        tope = ADC_MAX - CLIP_MARGEN
        for i in range(n):
            muestra = raw[i]
            volts[i] = muestra * escala
            if muestra <= CLIP_MARGEN or muestra >= tope:
                clips += 1
        self.clips = clips
        self.atrasos = atrasos
        return volts
