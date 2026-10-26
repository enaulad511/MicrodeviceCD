# Pendientes del proyecto (índice general)

Lista única de todo lo que está abierto en el proyecto, por área. Cada línea es corta y
enlaza al doc que tiene el detalle (el porqué, los datos, las checklists completas).
**Aquí solo se lleva el estado**: al cerrar algo, márcalo aquí y en su doc.

Leyenda:

- **HW**: necesita el equipo.
- **DEV**: código o decisión, sin equipo.
- Prioridad: ⬆ alta, ➖ media, ⬇ baja.

Actualizado: 14/10/2026.

## Preparación común antes de cualquier prueba en el equipo

- [ ] **Commitear y subir** lo que sigue local. Hoy son `ui/PcrFrame.py` (frescura por p90)
      y varios `docs/`. Sin esto, el Pi corre el código anterior.
- [ ] **En el Pi, `update_repo`.** En la restauración elegir `1` (la config previa). El
      paso 4 siembra las claves nuevas de `settings.json` sin tocar lo afinado.
- [ ] **`power_save` apagado:** `iw dev wlan0 get power_save` → `off`. Si vuelve a `on`,
      la temperatura llega cada 0.3 s ([pcr_eje_tiempo.md](pcr_eje_tiempo.md) §6).
- [ ] ⬆ HW — **`pip install openpyxl` en el Pi** (dependencia nueva del guardado .xlsx).
      Sin ella la app arranca, pero cada guardado cae al respaldo CSV o da error. Luego
      convertir lo viejo con `tools/csv_to_xlsx.py`
      ([almacenamiento_por_experimento.md](almacenamiento_por_experimento.md) §7).

## PCR (control térmico)

- [ ] ⬆ HW — **Corrida de validación de los cambios del 13–14/10**: frescura, salvaguarda
      de fases, fuzzy corregido, rampa a ext del ciclo 1 y metadata nueva. Checklist
      completa en [pcr_pendientes.md](pcr_pendientes.md) §7. Recomendado: una corrida
      corta (~5 ciclos) y luego Newn1 completa para comparar. Vigilar **sobreimpulso**.
- [ ] ⬆ HW — La desnaturalización debe llegar al setpoint; en Newn1 se quedó en 91.5 °C
      ([pcr_pendientes.md](pcr_pendientes.md) 2).
- [ ] ➖ HW — Los atascos de la rampa a ext deberían desaparecer sin re-afinar. **No tocar
      ganancias antes de ver la corrida** ([pcr_pendientes.md](pcr_pendientes.md) 3).
- [ ] ⬇ DEV — Si `dt_mean` sale entre 0.08 y 0.3 s, evaluar el `SO_RCVBUF` de 512 B de
      `ClientUDP`: descarta lecturas dentro de las ráfagas. No afecta al control
      ([pcr_pendientes.md](pcr_pendientes.md) 7).

## Temperatura y sensores

- [ ] ⬆ HW — **MLX90614 antes de migrar el PID al IR:**
  - flag de error con el sensor tapado: debe verse `MLX90614: lectura fallida` y el
    aviso en la UI, no una temperatura absurda;
  - sesgo de `t_obj` contra la termocupla en 55–95 °C.

  Detalle en [mlx90614_fiabilidad_lectura.md](mlx90614_fiabilidad_lectura.md) §8.
- [ ] ⬇ DEV — Causa de las ráfagas UDP (3–4 lecturas juntas cada ~0.27 s; probablemente
      el softAP del ESP8266). El control ya las cubre con el p90
      ([pcr_eje_tiempo.md](pcr_eje_tiempo.md) §6).

## Electroquímica (EmStat)

- [ ] ⬆ HW — **Seguridad:**
  - `ABORT` apaga la celda (`clean=true`);
  - el dead-man actúa al matar el host;
  - un fin normal no dispara un ABORT espurio;
  - mapeo canal MCP → electrodo real.

  Detalle en [emstat_abort_y_canal.md](emstat_abort_y_canal.md) §8.
- [ ] ➖ HW — **Recuperación por UDP:** dos sockets en 5005 reciben ambos; Fase 0 (pérdida
      solo TCP) y Fase 1 (matar TCP a mitad de corrida)
      ([emstat_udp_recovery.md](emstat_udp_recovery.md) §6).
- [ ] ➖ HW — **SWV:** arranque fiable con `rxbuf=2048`; estabilidad en corridas largas
      ([emstat_swv_y_fiabilidad_uart.md](emstat_swv_y_fiabilidad_uart.md)).
- [ ] ➖ HW — **SWV, pre-tratamiento:**
  - plot sin pre-tratamiento, indicador de fase y `phase` en el CSV;
  - el motor oscila solo durante el pre-tratamiento y se detiene con Stop.

  Detalle en [sqwv_plot_precondicionamiento.md](sqwv_plot_precondicionamiento.md) y
  [sqwv_motor_pretratamiento.md](sqwv_motor_pretratamiento.md).
- [ ] ➖ HW — **Keep runs:** seis casos (trazas R1/R2, sin marcar, apilado, Save/Load
      multi-corrida, CSV viejo, etiquetas CV) ([emstat_keep_runs.md](emstat_keep_runs.md)
      §6).
- [ ] ➖ HW — **EIS:**
  - acondicionamiento opcional;
  - baja frecuencia contra `MAX_EXPERIMENT_MS`;
  - código de paquete de `eb`;
  - terminal del fin de Time Scan;
  - cycles × Keep runs.

  Detalle en [eis_impedancia.md](eis_impedancia.md) §6, §7.5.
- [ ] ➖ HW — **CA end-to-end:** paquetes `e`/`i`, marcador `*`, Cottrell. La v1.9 ya está
      flasheada ([ca_cronoamperometria.md](ca_cronoamperometria.md) §7).
- [ ] ⬇ DEV — **CA:** calcular `Max bandwidth` automáticamente, como PSTrace
      ([ca_cronoamperometria.md](ca_cronoamperometria.md) §7).

## Fluorescencia

- [ ] ➖ HW — Ciclo real: timing del muestreo, CSV crudo y ETA. Se puede cerrar con la
      misma corrida PCR de validación ([cambios_fluorescencia.md](cambios_fluorescencia.md)).

## Análisis

- [ ] ➖ DEV — **Pestaña PCR:** usar las columnas `cycle`/`phase` del CSV de temperatura y
      `timeouts` del de fotodetector para segmentar automáticamente y excluir ciclos
      fallidos. Es una decisión de diseño: ¿cómo convive con la selección manual a dos
      clics? ([pcr_pendientes.md](pcr_pendientes.md) 8, [pcr_analisis.md](pcr_analisis.md)).

## Control manual (Quick Control)

- [ ] ⬇ DEV — Dos plots apilados; página de análisis para los CSV `unified_*` (fuera de
      alcance por ahora) ([quick_control.md](quick_control.md)).

## Firmware legacy (otros equipos)

- [ ] ⬇ HW — **FluorReader:** compilar/flashear, confirmar el LCD (16x4 o 20x4, fork de
      la librería) y la polaridad del relé
      ([FluorReader](../firmware/FluorReader/README.md) §6).
- [ ] ⬇ HW — **DisckWifiArduino:** el broadcast dirigido llega en el hotspot real
      ([DisckWifiArduino](../firmware/DisckWifiArduino/README.md) §5).

## Cerrado recientemente (13–14/10/2026)

- **Temperatura cada 0.307 s:** la causa era el `power_save` del Pi. **Se apagó de forma
  persistente**, y ahora llega a 12.5/s, en ráfagas ([pcr_eje_tiempo.md](pcr_eje_tiempo.md)
  §6).
- **Frescura de la temperatura** relativa a la cadencia, con **p90** de los huecos:
  los *holds* recuperan ~100 % de potencia
  ([pcr_temperature_control.md](pcr_temperature_control.md) §9).
- **Salvaguarda de tiempo por fase** y aborto por racha de ciclos fallidos
  ([pcr_timeout_fases.md](pcr_timeout_fases.md)).
- **Columnas `cycle`/`phase`** por muestra en el CSV de PCR
  ([pcr_csv_ciclo_fase.md](pcr_csv_ciclo_fase.md)).
- **Varios puntos de PCR** ([pcr_pendientes.md](pcr_pendientes.md)):
  - fuzzy continuo;
  - `ext_ramp` sin `break_if_below`;
  - defaults = ganancias del equipo;
  - `temp_start_wait_s`;
  - extensión en la metadata;
  - preview y ETA con modelo ΔT.
- **Ventana del watchdog de sensores** configurable con `temp_stale_s`
  ([temp_source_selector.md](temp_source_selector.md)).
- **Firmware v1.9 del disco flasheado**, y **emisividad 0.96 del MLX confirmada** por la
  consola serial del Pico (usuario, 14/10/2026). CA ya no está bloqueada
  ([ca_cronoamperometria.md](ca_cronoamperometria.md) §7,
  [mlx90614_emisividad.md](mlx90614_emisividad.md) §6).

__author__ = "Edisson A. Naula"
__date__ = "$ 14/10/2026 $"
