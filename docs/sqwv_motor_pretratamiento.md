# SWV — Motor durante el pre-tratamiento

El SWV (`ui/SqwVFrame.py`) puede oscilar el motor del disco (±ángulo) **solo durante el
pre-tratamiento** = `condition` + `deposition`. A diferencia de CV
([CvFrame](../ui/CvFrame.py)), donde el motor gira toda la corrida, aquí **debe estar
quieto** durante la equilibración y el barrido SWV.

Complementa [emstat_keep_runs.md](emstat_keep_runs.md) y reutiliza el mismo driver
oscilador (`spinMotorAngleDriver`, modo sweep continuo) que CV.

---

## 1. El problema: el host no "ve" el fin del pre-tratamiento

El pre-tratamiento **sí emite datos** — ojo, esto corrige una premisa inicial equivocada. Cada
fase (condition, deposition, equilibration) es un `meas_loop_ca` que transmite paquetes `e`/`i`
([Drivers/EmstatUtils.py](../Drivers/EmstatUtils.py), `construc_individual_script_sqwv`); el
barrido SWV es el último loop. Cronología real de una corrida típica
(`t_con=15`, `t_dep=60`, `t_equil=10`):

```
envío script ─┬─ condition  (15 s)  ◄── motor oscilando   (emite datos CA)
              ├─ deposition (60 s)  ◄── motor oscilando   (emite datos CA)
              │  ── frontera @ 75 s: motor DEBE parar ──
              ├─ equilibration (10 s)   motor quieto       (emite datos CA)
              └─ barrido SWV …          motor quieto       (1er paquete "sweep" @ ~85 s)
```

La frontera deposition→equilibration (75 s) **no tiene un marcador directo en el stream** (los
datos fluyen igual antes y después). Por eso la frontera se deduce por **tiempo**, no por
paquetes. Lo que sí se distingue por paquetes es el **inicio del barrido**: solo los paquetes
SWV traen `i_forward`/`i_reverse` (`phase="sweep"`, ver
[sqwv_plot_precondicionamiento.md](sqwv_plot_precondicionamiento.md)) — eso alimenta la red de
seguridad de §2.

## 2. Diseño: Timer como autoridad + primer-paquete-de-barrido como red de seguridad

- **Autoridad — Timer.** Al enviar el script, `start_spin_motor_angle` arranca el oscilador y
  arma un `threading.Timer(t_con + t_dep, stop_event.set)`. Al cumplirse la duración, setea el
  `stop_event`; el driver lo sondea ~cada 20 ms (`Drivers/DriverStepperSys.py`,
  `spinMotorAngleDriver`) y detiene el motor pronto. El ancla del Timer es el **momento de
  envío** (igual que CV, vía `callback_spin_motor` en `EventPlotter.start`); el desfase por
  latencia de la cadena Python→Wemos→Pico→EmStat (~<1 s) es despreciable frente a la ventana
  de decenas de segundos.
- **Red de seguridad — primer paquete de BARRIDO.** `EventPlotter` dispara un hook opcional
  `on_first_data` la primera vez que llega un paquete con `phase != "pretreatment"` (inicio real
  del barrido, ya pasada la equilibración, ~85 s) — **no** el primer `emstat_data`, que sería un
  paquete de condition (~0.5 s) y cortaría el motor enseguida. El handler de SWV
  (`_stop_motor_on_first_data`) setea el `stop_event`. El Timer siempre gana (75 s < ~85 s), así
  que esto solo cubre que el Timer no disparara. One-shot: el hook se anula tras ejecutarse.

Parada efectiva = `min(Timer @ 75 s, 1er paquete sweep @ ~85 s)` = **75 s**.

## 3. Limpieza y bordes

- **Fin de corrida** (terminal del firmware, Stop manual o error de MethodSCRIPT): el plotter
  llama `on_end_experiment`, que **cancela el Timer**, setea el `stop_event` y hace `join` del
  hilo para liberar UART/GPIO antes de la siguiente corrida. Cubre también un Stop/error
  **durante** el pre-tratamiento (el motor para con la corrida).
- **Ventana cero.** Si el motor está habilitado pero `t_con + t_dep == 0`, **no se arranca el
  motor** (`callback_spin_motor=None` para esa corrida): evita un motor que arranca y se le
  manda parar en el mismo instante.
- **Cancelar el Timer al cerrar** evita que un Timer rezagado dispare sobre el `stop_event` de
  una corrida posterior.

## 4. UI y persistencia (paridad con CV)

`create_widgets_swv` añade un `LabelFrame` "Motor Settings" idéntico al de CV: checkbox
*Enable Motor (pre-treatment only)*, *Angle (°, max 30)* (default 10), *Speed (%)* (default 7).
Los campos `motor_enable`/`motor_angle`/`motor_speed` se guardan en `collect_values`/
`apply_values`, así que persisten en los proyectos electroquímicos `sqwv`
([electrochem_proyectos.md](electrochem_proyectos.md)). El CSV guardado lleva el sufijo
`_ang<…>_spd<…>` (o `_motoroff`) vía `filename_meta`.

## 5. Archivos tocados (host-only; el firmware NO cambia)

| Archivo | Cambio |
|---|---|
| `ui/SqwVFrame.py` | frame "Motor Settings"; `start_spin_motor_angle` + Timer; `_stop_motor_on_first_data`; `on_end_experiment`; wiring en `send_script`; persistencia en `collect_values`/`apply_values` |
| `ui/EventEmstatFrame.py` | hook genérico `on_first_data` (param de `update_val_experiment`, disparo one-shot en el 1er `emstat_data`) |

El motor comparte el UART del Pico con el stepper, igual que en CV — sin nueva contención. Al
ser una feature de orquestación del host, **el EmStat y el firmware quedan intactos**.

## 6. Verificación

- [ ] Con motor habilitado y `t_con=15`, `t_dep=60`: el motor oscila ~75 s y se detiene antes
  de que lleguen los primeros datos del barrido.
- [ ] Stop manual durante el pre-tratamiento detiene el motor de inmediato.
- [ ] `t_con=t_dep=0` con motor habilitado: el motor no arranca.
- [ ] El proyecto `sqwv` guarda/restaura enable/ángulo/velocidad.

---

__author__ = "Edisson A. Naula"
__date__ = "$ 25/06/2026 $"
