# Selector de fuente de temperatura

## Qué es

El broadcast UDP del disco (`...UDP:<t_amb>:<t_obj>:<t_tc>`) trae **tres**
temperaturas, no una: las dos primeras son del sensor infrarrojo **MLX90614**
(ambiente y objeto) y la tercera es la termocupla **MAX31855**. El firmware las
arma así:

```python
# firmware del disco (fuera de este repo)
line = f"{t_amb}:{t_obj}:{t_tc}"   # cualquier campo puede venir "None" / "NS"
```

Hasta ahora `Drivers/ClientUDP.py` sólo parseaba el tercer campo (termocupla) y
lo reenviaba. Este cambio agrega un **selector de fuente** para que el usuario
elija cuál de las tres temperaturas usan los experimentos, en tres lugares:
la ventana **PCR** (`ui/PcrFrame.py`), y las tabs de control manual
**Temperature** (`ui/TemperatureFrame.py`) y **Quick Control**
(`ui/QuickControlFrame.py`).

## Decisiones de diseño

### 1. ClientUDP reenvía las tres; el frame elige (no el driver)

`ClientUDP._run_loop` parsea los tres campos y los reenvía en la lista del
callback `[t_amb, t_obj, t_tc, ts]` (antes eran `[0, 0, temp, ts]`: los dos
slots reservados ahora llevan las IR). El driver queda **genérico** —relata
datos crudos— y cada frame selecciona el índice según su combobox. Esto es
retrocompatible: el índice 2 sigue siendo la termocupla, así que los cuatro
consumidores existentes que leían `temps_list[2]` no se rompen
(`Drivers/ClientUDP.py:216-238`).

`latest_temp` (para lectores directos) y `data_temps` conservan el **último
valor válido por campo** —no se pisan con `None`— y `latest_temp` sigue siendo
la termocupla por compatibilidad.

### 2. Parseo tolerante a `None` / `NS`

Cualquier campo puede llegar como el literal `"None"` (sensor con excepción) o
`"NS"` (no sensor). `_parse_temp` (`Drivers/ClientUDP.py`) devuelve `float` o
`None` en lugar de reventar el parseo de todo el mensaje —antes `float(temps[2])`
tiraba y se descartaba el broadcast completo—. Por eso `MainGUI.on_message_tester`
(el test de conexión del disco) ahora acepta **cualquiera** de las tres
temperaturas para confirmar conexión, no sólo la termocupla
(`ui/MainGUI.py:311-322`).

### 3. Persistencia: una clave global en settings.json

La elección se guarda como clave canónica **`temp_source`** en
`resources/settings.json` (`"thermocouple"` / `"ir_object"` / `"ir_ambient"`),
no el índice del payload, para sobrevivir un reordenamiento futuro de los
campos. Vive en `templates/utils.py` junto a la tabla `TEMP_SOURCES` y helpers
(`temp_source_labels`, `temp_source_index`, `temp_source_key`,
`temp_source_label`, `read_temp_source`, `write_temp_source`); sembrada en
`DEFAULT_SETTINGS` para auto-repararse. Cada frame **lee al construir y escribe
al cambiar**; no hay sync en vivo entre frames (el valor queda consistente la
próxima vez que se abre cada uno).

### 4. En PCR la fuente maneja el PID (bloqueada durante la corrida)

En `PcrFrame`, `self.temp` es la variable que **todo el lazo térmico** regula
(`_reach_temperature_pi`, `_hold_phase`, decisiones de calentar/enfriar). El
selector fija qué campo del payload alimenta `self.temp`
(`update_displayed_temperature`, índice `temp_source_idx`). Como cambiar de
sensor a mitad de experimento cambiaría el setpoint efectivo (IR objeto y
termocupla leen distinto), el combobox se **deshabilita** mientras
`running_experiment` es `True` (`callback_start_experiment`) y se rehabilita al
restaurar la UI (`_restore_input_ui`). El combobox vive en la barra de botones
(`_build_source_selector`), que permanece visible durante la corrida (a
diferencia de las entradas y la barra de proyecto, que se ocultan).

### 5. Sensor caído: sostener último valor + avisar

Si el sensor elegido viene ausente (`None`), se **sostiene el último valor
válido** (igual que el `except` que ya tenía PcrFrame) y se marca
`temp_source_bad`, que se surtea en el status:
`⚠ IR Object unavailable — holding last value`. No hay auto-fallback silencioso
a termocupla —cambiar la fuente de control sin avisar es justo el susto que el
bloqueo-durante-la-corrida evita—. En PCR el aviso va al `svar_status`; en
Temperature a un `lbl_status` nuevo del panel de control; en Quick Control al
`_set_status` existente.

### 6. Metadata: la fuente queda registrada

- **PCR**: se agrega `-temp_source: <label>` al `prefix_col` que encabeza el CSV
  de temperaturas (`callback_start_experiment`).
- **Temperature**: el encabezado de columna incluye la fuente
  (`Temp IR Object (°C)`).
- **Quick Control**: para corridas de temperatura se agrega `tsrc=<label>` al
  meta que arma el sufijo del nombre de archivo (`start_reading`).

## Orden de los campos (crítico)

| índice payload | campo    | sensor            | clave          | etiqueta      |
|:--------------:|----------|-------------------|----------------|---------------|
| 0              | `t_amb`  | MLX90614 ambiente | `ir_ambient`   | IR Ambient    |
| 1              | `t_obj`  | MLX90614 objeto   | `ir_object`    | IR Object     |
| 2              | `t_tc`   | MAX31855 termocupla | `thermocouple` | Thermocouple |

El combobox se muestra en orden **Thermocouple, IR Object, IR Ambient**
(termocupla primero = comportamiento por defecto previo).

__author__ = "Edisson A. Naula"
