# Firmware DiscPCB — espejo (mirror) en el repo

Copia **de referencia** del firmware MicroPython del **Pico 2** que orquesta el EmStat,
la temperatura y los canales de electrodo. La fuente original vive fuera de git en
`~/MicroPython/DiscPCB/` y es lo que realmente se flashea a la placa.

> ⚠️ **Este directorio NO se ejecuta ni se flashea desde aquí.** Es un espejo para que
> el firmware quede versionado junto al host (`ui/`, `Drivers/`) y se pueda leer/diff sin
> salir del proyecto. **Editar aquí no cambia la placa**: hay que copiar a
> `~/MicroPython/DiscPCB/` y flashear. Mantener ambos en sync manualmente.

## La cadena de tres nodos

```
App Python (este repo) ──TCP:5006──► Wemos D1 mini ──UART_LINK──► Pico 2 ──UART──► EmStat
   ui/EventEmstatFrame.py            (WemosD1Mini.ino)      (emstat_wifi_v1.9.py)     celda
                          ◄──UDP:5005 broadcast──┘ (bifurca cada línea EMSTAT a TCP+UDP)
```

- El **Pico 2** (`emstat_wifi_v1.9.py`) arma el script MethodSCRIPT, lo manda al EmStat,
  lee la respuesta línea a línea y la reenvía al Wemos como `EMSTAT:<json>\n` por UART.
  También difunde temperatura como `UDP:<...>\n`.
- El **Wemos** recibe esas líneas por UART y las **bifurca**: las sirve por **TCP (5006)**
  al host y las **difunde por UDP broadcast (5005)**, sin modificar el `payload` (por eso
  el `seq` viaja idéntico por ambos). Espejo del sketch:
  [../WemosD1Mini/](../WemosD1Mini/README.md) (original bajo
  `~/OneDrive - …/Documents/Arduino/WemosD1Mini/`).

Diagramas detallados (pines, baudios, flujos de control/datos/abort):
[docs/emstat_arquitectura_cadena.md](../../docs/emstat_arquitectura_cadena.md).

## Inventario de archivos

| Archivo | Rol |
|---|---|
| `emstat_wifi_v1.9.py` | **Firmware actual del Pico** (`main.py` en la placa): v1.8 + rama `"ca"` (Chronoamperometry: escalón de potencial, equilibrio opcional, topes `max_ms`/`idle_ms` por corrida). Ver [docs/ca_cronoamperometria.md](../../docs/ca_cronoamperometria.md). |
| `emstat_wifi_v1.8.py` | Versión previa (flasheada 2026-06-11): EIS Fase 2 (5 modos, topes `max_ms`/`idle_ms` por corrida, fin normal con `'*'` o `'+'`). Ver [docs/eis_impedancia.md §7](../../docs/eis_impedancia.md). |
| `emstat_wifi_v1.7.py` | Versión previa: EIS Fase 1 + `seq` para recuperación UDP. |
| `emstat_wifi_v1.6.py` | Versión previa: abort en caliente + robustez de lectura. |
| `emstat_wifi_v1.5.py` / `v1.4.py` | Versiones históricas. |
| `EmstatDrivers.py` | Constructores MethodSCRIPT (cv/sqwv/eis/ca) + clase `EmstatPico` (UART). |
| `mlx90614.py` | Driver I2C del sensor de temperatura MLX90614. |
| `protocol/emstat_wifi_v1.6.md` | Doc del protocolo del firmware (fuente de verdad del contrato). Carpeta `protocol/` y no `docs/` porque `.gitignore` excluye cualquier carpeta `docs`. |

## `seq`: recuperación de datos perdidos en TCP vía UDP (v1.7)

**Problema.** A veces el Wemos recorta/cierra el TCP y se pierden paquetes `emstat_data`
o incluso el `emstat_end` — visible en Wireshark: el paquete **sí** sale por el broadcast
UDP (5005) pero **no** llega por TCP. El host descartaba ese UDP en silencio.

**Cimiento de la solución.** El Pico inyecta un contador `"seq"` en **cada** mensaje
EMSTAT, en el único punto por el que todos pasan antes de bifurcarse a TCP+UDP
(`send_emstat_line`). Así **ambos transportes cargan el mismo `seq`**, y el host puede:

- **deduplicar** (mismo `seq` = mismo paquete, venga por donde venga),
- **detectar huecos** y **rellenar** desde UDP los `seq` que faltaron en TCP,
- **medir cobertura** por transporte (`seq` que solo trajo UDP = pérdida de TCP probada).

```python
# emstat_wifi_v1.7.py
_emstat_seq = 0  # reinicia en cada emstat_start

def send_emstat_line(obj: dict):
    global _emstat_seq
    if obj.get("type") == "emstat_start":
        _emstat_seq = 0
    obj["seq"] = _emstat_seq
    _emstat_seq += 1
    uart_link.write(HDR_EMSTAT + json.dumps(obj) + "\n")
```

Numeración: `emstat_start`→`seq 0`, primer dato→`seq 1`, … Granularidad **1 mensaje = 1
P-line** (`run_experiment_read_loop` emite un `emstat_data` por línea, no agrupa). El campo
`raw` **no** se toca. Ejemplo verificado en hardware (Wireshark):

```
EMSTAT:{"raw": "Pda8A3F3EAn;ba80701BEf,14,200;...", "type": "emstat_data", "seq": 106}
```

> Nota: el `,14,200` del `raw` **no es un índice** — son metadata MethodSCRIPT (status +
> current-range, diagnóstico). El EmStat no emite secuencia propia; por eso el `seq` se
> genera en el Pico. Ver [docs/emstat_udp_recovery.md](../../docs/emstat_udp_recovery.md).

## SWV: pacing del UART y fixes del script

El SWV fallaba con errores de MethodSCRIPT (`e!4001`/`e!4008`) en líneas **inconsistentes**
entre corridas. Un eco temporal del script (`DEBUG_ECHO_SCRIPT`) probó que el script se
genera bien, pero llega **corrupto e intermitente** al EmStat: `write_lines` enviaba las ~26
líneas en ráfaga a 230400 baud y **desbordaba el RX del EmStat**.

- **`EmstatDrivers.write_lines`** ahora hace `time.sleep_ms(5)` entre líneas (pacing) para que
  el EmStat drene su buffer. Resolvió la corrupción.
- **Fixes del builder SWV** (`construct_header_experiment` / `construc_individual_script_sqwv`):
  `var i_forward` ya no se declara duplicado, y los bloques de acondicionamiento/deposición
  requieren **tiempo y potencial** (no generan `set_e `/`meas_loop_ca` con potencial vacío).

Detalle completo: [docs/emstat_swv_y_fiabilidad_uart.md](../../docs/emstat_swv_y_fiabilidad_uart.md).

## Flashear

1. Libera el REPL: botón **safe-boot en GP22 a GND** al encender, o **Ctrl-C** durante la
   ventana de arranque (`BOOT_DELAY_S = 5 s`).
2. Copia `emstat_wifi_v1.9.py` a la placa como `main.py` (junto con `EmstatDrivers.py`,
   `mlx90614.py`, `mcp23017.py`).
3. Reinicia. El LED parpadea lento (`LED_IDLE`) si el EmStat responde; rápido si no.

## Sincronización con el espejo

Tras editar el original y flashear, refresca este espejo:

```powershell
Copy-Item ~\MicroPython\DiscPCB\*.py firmware\DiscPCB\ -Force
Copy-Item ~\MicroPython\DiscPCB\docs\*.md firmware\DiscPCB\docs\ -Force
```
