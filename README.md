# Sismómetro mk2

Firmware para **Raspberry Pi Pico** y visor en el PC. Cada bloque lee la bobina, encuentra la fundamental y convierte ese voltaje en velocidad y desplazamiento de la mesa.

<p>
  <img alt="Placa" src="https://img.shields.io/badge/placa-Raspberry%20Pi%20Pico-C51A4A">
  <img alt="Firmware" src="https://img.shields.io/badge/firmware-MicroPython-2E8A4A">
  <img alt="Muestreo" src="https://img.shields.io/badge/fs-500%20Hz-1F6FEB">
  <img alt="Bloque" src="https://img.shields.io/badge/bloque-2048%20muestras%20%C2%B7%204.096%20s-6E7681">
</p>

La bobina no mide la mesa directamente. Mide la velocidad de la masa. El firmware invierte la respuesta calibrada `H_v(f)` y devuelve el movimiento de la base.

```text
GP26  →  500 Hz × 4.096 s  →  Hann + FFT  →  pico corregido  →  Y, Ẏ
ADC0        2048 muestras       radix-2         3 bins + Hann      mesa
```

## Qué sale en pantalla

| Vista | Qué muestra |
| --- | --- |
| Bobina | Cinco periodos de la senoide, muestras y ajuste |
| Frecuencia | Historial de `f` durante 3 minutos |
| Desplazamiento | Historial de `Y` de la mesa |
| Posición | Esos mismos cinco periodos, ya en milímetros |

En la consola de la Pico, cada bloque válido termina con una línea `D` y, debajo, la onda `S`.

## Cadena de medida

1. **Captura.** ADC0 en GP26, reposo en 1.65 V. El periodo se adelanta siempre 2000 µs, así que un atraso de una muestra se recupera en la siguiente y la `fs` media se queda en 500 Hz.
2. **Espectro.** Se resta la media, se aplica una ventana de Hann y una FFT radix-2. La magnitud queda en voltios pico, no en cuentas.
3. **Pico.** Parábola sobre el logaritmo de los tres bins del máximo. La respuesta conocida de la Hann corrige el sesgo: sin eso, entre dos bins la amplitud queda hasta un 2.5 % alta.
4. **Mesa.** Se invierte la sensibilidad calibrada.

```text
H_v(f) = S_inf · r² / √((1 − r²)² + (2·ζ·r)²)    r = f / fn

Ẏ = V_pico / H_v(f)
Y  = Ẏ / (2πf)
```

La estimación de la Pico usa esta `H_v` lineal. El término cuadrático `3.8·|ż|·ż` queda escrito en la ecuación del movimiento y no se vuelve a sumar encima, porque si no la tabla de calibración deja de cerrar.

## Modelo calibrado

El ajuste en 10.50 Hz, 15.54 Hz y 25.37 Hz fijó `fn`, `ζ` y `S_inf`.

| Símbolo | Valor | Sentido |
| --- | ---: | --- |
| `fn` | 17.93 Hz | Frecuencia natural |
| `ζ` | 0.561 | Amortiguamiento viscoso del ajuste |
| `S_inf` | 3.835 V·s/m | Sensibilidad de alta frecuencia |
| `Kem` | 12.30 V·s/m | Bobina → velocidad de la masa |
| `m_ef` | 0.0664 kg | Masa efectiva |
| `m_f` | 0.0207 kg | Masa que ve la base |
| `k_ef` | 842.5 N/m | Rigidez efectiva |
| `c_tot` | 8.40 kg/s | Amortiguamiento lineal |

```text
0.0664·z″ + 8.40·z′ + 3.8·|z′|·z′ + 842.5·z = −0.0207·y″
V_adc = 1.65 − 12.30·z′
```

`S_inf = Kem · (m_f / m_ef)`. La velocidad de la masa no es la de la mesa.

## Ejecutable

En [Releases](https://github.com/FTGProyects/sismometro-mk2/releases) está `Sismometro-mk2.exe`. No hace falta instalar Python.

1. Conecta la Pico por USB y cierra Thonny.
2. Abre el programa.
3. Pulsa **Montar firmware**. Copia los seis módulos que lleva dentro y reinicia la placa.
4. La gráfica se engancha sola al puerto.

El mismo botón está en la ventana si arrancas el visor desde el código. Windows puede pedir confirmación la primera vez: el ejecutable no va firmado.

## Arranque

Hace falta Python 3 en el PC y MicroPython en la Pico. Cierra Thonny antes de copiar el firmware: si tiene el puerto serie, la copia falla.

```powershell
python -m pip install -r requirements.txt
.\iniciar_grafica.ps1 -Deploy
```

`-Deploy` copia estos archivos y reinicia la placa: `config.py`, `fft_radix2.py`, `espectro.py`, `modelo.py`, `adquisicion.py`, `main.py`.

Si la Pico no es el único puerto, indícalo:

```powershell
.\iniciar_grafica.ps1 -Deploy -Port COM5
```

Solo la gráfica, con el firmware ya cargado:

```powershell
.\iniciar_grafica.ps1
```

El visor busca una placa con VID `2E8A` a 115200 baudios y reintenta la conexión 25 veces.

Para comprobar en el PC el mismo espectro y la misma `H_v`, sin ADC:

```powershell
python verificar_modelo.py
```

Compara senos sintéticos contra la tabla del modelo (4.00, 10.50, 15.54, 25.37 y 35.00 Hz).

## Líneas que viajan por el serie

Medición, separada por tabuladores:

```text
D    f_Hz    V_pico_V    Ydot_m_s    Y_m    H_Vsm
```

Onda, cinco periodos de la bobina. La cabecera `S` y, en la línea siguiente, los voltios separados por comas:

```text
S    n    amp_V    fase_rad    fs    f_Hz
1.64821,1.65102,1.65380,...
```

Si no hay fundamental, la Pico lo dice y no imprime `D` ni `S`. El candidato se descarta por debajo de 1.5 mV de pico, fuera de 1–120 Hz, o con pico/mediana menor que 6.

## Avisos de la Pico

| Mensaje | Qué revisar |
| --- | --- |
| `V_media` lejos de 1.65 V | Divisor de ADC0 |
| El ADC tocó 0 V o 3.3 V | Bajar la ganancia: el bloque está recortado |
| Muestras atrasadas | Un IRQ de USB retrasó alguna lectura. La `fs` media se sostiene; sube el ruido |

## Archivos

| Archivo | Dónde corre | Papel |
| --- | --- | --- |
| `main.py` | Pico | Bucle de captura, espectro e impresión |
| `adquisicion.py` | Pico | Bloque de 2048 muestras en ADC0 |
| `fft_radix2.py` | Pico | FFT in-place |
| `espectro.py` | Pico y PC | Hann, magnitud en voltios e interpolación |
| `modelo.py` | Pico y PC | `H_v(f)` y paso a `Y` |
| `config.py` | Pico y PC | Constantes del instrumento |
| `plot_fast.py` | PC | Ventana PyQt6 |
| `verificar_modelo.py` | PC | Prueba del espectro y de la tabla |
| `montar.py` | PC | Copia el firmware y reinicia la Pico |
| `deploy_pico.ps1` | PC | Atajo de `montar.py` |
| `iniciar_grafica.ps1` | PC | Despliegue opcional y visor |
| `compilar.ps1` | PC | Genera `Sismometro-mk2.exe` |

`plot_fast.py` y `verificar_modelo.py` se quedan en el PC.
