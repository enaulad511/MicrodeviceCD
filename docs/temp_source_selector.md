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
  meta que arma el sufijo del nombre de archivo (`start_reading`); en modo
  "All (3 temps)" el valor es `tsrc=All`.

### 7. Quick Control: graficar las 3 temperaturas a la vez

`ui/QuickControlFrame.py` agrega una 4ª entrada al combobox, **`"All (3 temps)"`**
(`ALL_TEMPS_LABEL`), que activa `self.temp_all_mode`. Es un modo **local a Quick
Control** — no se agrega a `templates.utils.TEMP_SOURCES`/`temp_source_labels()`
(así PcrFrame y TemperatureFrame no la ofrecen, porque no aplica a un lazo PID
de un solo sensor) y **no se persiste** en el `temp_source` global de
`settings.json` (seleccionarla no toca el valor que lee PcrFrame; queda el
último single-source elegido).

- **Filtro por canal.** El promedio móvil de 4 muestras deja de ser un único
  `temps_filter`; ahora es `self.temp_filters` (3 buffers independientes, uno
  por índice de payload). Así el modo "All" luce igual que el modo de un solo
  canal —cada línea es la misma suavización que ya se confiaba—, y
  `_thermocouple_reader` (single-source) y `_read_all_temps` (All) leen del
  mismo array.
- **Modelo de datos unificado.** Cada corrida (`run` en `self.runs`) gana
  `run["cols"]`: la lista de nombres de columna (`["Thermocouple"]` en
  single-source, `["IR Ambient","IR Object","Thermocouple"]` en All,
  `["Voltage"]` en fluorescencia). `run["v"]` pasa de lista de escalares a
  lista de filas (`[c0, c1, ...]`, largo `len(cols)`); single-source es
  simplemente el caso de 1 columna. `_acquire` arma la fila con
  `_read_all_temps()` (All) o `[self._thermocouple_reader()]` (single/fluor).
- **Combobox bloqueado durante la lectura.** Cambiar de fuente/modo a mitad de
  una corrida rompería el modelo de filas (`cols` se fija al iniciar en
  `start_reading`, pero `_acquire` lee el modo *en vivo*): filas de distinto
  largo corromperían `_redraw`/CSV. Por eso `cbo_temp_source` se deshabilita en
  `start_reading` junto a los demás controles y se rehabilita en
  `stop_reading`, igual que ya hacían `chk_sig_temp`/`chk_sig_fluor`/
  `chk_keep`.
- **Sensor caído en modo All.** `_read_all_temps` sostiene el último valor
  **por canal** (no todo-o-nada) y el aviso lista los caídos por nombre:
  `⚠ IR Object unavailable — holding last value` (uno) o
  `⚠ IR Object, IR Ambient unavailable — holding last value` (varios).
- **Colores fijos por canal + leyenda adaptativa.** `TEMP_CHANNEL_COLORS`
  (`IR Ambient`→azul, `IR Object`→naranja, `Thermocouple`→rojo) se aplica en
  `_redraw` tanto en modo All como single-source, para que un canal mantenga su
  color aunque se apilen corridas (Keep data). La leyenda se muestra siempre
  que haya **más de 1 corrida** (Keep data) **o más de 1 columna** (modo All,
  incluso con una sola corrida); las etiquetas son solo el nombre del canal
  (`IR Object`) con una corrida, o `R{run} {canal}` con varias apiladas.
- **CSV en formato largo.** `save_data` cambia de
  `t_s,value,signal,run` a **`t_s,value,channel,signal,run`**: una fila por
  muestra y canal. Esto soporta sin celdas vacías que Keep data mezcle, en el
  mismo archivo, corridas de distinta forma (single-source de 1 columna, All
  de 3, fluorescencia con `channel="Voltage"`). Nada más en el repo relee estos
  CSV, así que el cambio de encabezado es seguro.
- **Retención (Keep data) sin cambios de regla.** Igual que un cambio de fuente
  single→single ya no limpiaba el plot, pasar a/desde "All" tampoco lo hace —
  solo un cambio de señal (temp↔fluor) limpia. Los colores fijos por canal +
  las etiquetas `R{run} {canal}` mantienen legible una mezcla de corridas de 1
  y 3 columnas.
- **`_set_status` a prueba de encoding.** Los avisos de sensor caído usan `⚠` y
  `—`; en una consola cp1252 (Windows sin UTF-8) `print()` con esos caracteres
  lanza `UnicodeEncodeError`. Como `_set_status` se llama **desde dentro** de
  `_thermocouple_reader`/`_read_all_temps`, que a su vez corren dentro del
  `try` de `_acquire`, ese error se tragaba silenciosamente en el `except`
  genérico —la muestra se descartaba y el label nunca llegaba a actualizarse
  con el aviso real—. `_set_status` ahora configura el label **antes** de
  intentar el `print` (Tk sí soporta Unicode sin problema) y el `print` cae a
  un fallback ASCII (`encode("ascii","replace")`) si falla.

### 8. PCR: las tres temperaturas en el label durante la corrida

`_ui_poll_loop` arma la primera línea del status (`ui/PcrFrame.py`). Antes
mostraba **solo** la fuente que regula el PID; ahora añade las **otras dos**
temperaturas entre paréntesis, sin tocar el lazo térmico:

```
Temperature: 94.12 °C [Thermocouple]  (IR Object 92.3, IR Ambient 25.1)
State: Reach High temp
Time passed: 2 m 14.3 s -- cycles: 3/30 -- Estimated finish: 41m 8.0s
```

- **Primaria suavizada, secundarias crudas.** El número principal sigue siendo
  `self.temp` (la fuente elegida, suavizada α=0.3, sin cambios: es lo que el PID
  regula, sección 4). Las dos secundarias muestran el **último valor crudo**
  recibido — `update_displayed_temperature` ahora guarda los tres campos del
  payload en `self.temps_raw` (`[t_amb, t_obj, t_tc]` por índice, `None` incluido)
  además de calcular `self.temp` como siempre.
- **Orden fijo, salta la primaria.** Se itera `TEMP_SOURCES` (Thermocouple, IR
  Object, IR Ambient) y se omite el índice primario (`temp_source_idx`), así el
  par secundario aparece siempre en el mismo orden sin importar cuál regula.
- **Sensor secundario ausente → `N/A`.** Un canal secundario en `None` (o no
  numérico) se muestra como `N/A`, **sin** el aviso `⚠`. El
  `⚠ … holding last value` queda reservado para la fuente que maneja el PID
  (sección 5): un canal secundario caído no afecta el control, así que no merece
  alarma. Ambos coexisten en la línea si la primaria además se cae.
- **Solo el label.** El plot (`update_graph_temperature`) y el CSV
  (`save_data_temps_file`) siguen guardando **solo** `self.temp` (la primaria).
  Graficar/persistir las tres es justo lo que cubre Quick Control (sección 7);
  duplicarlo en PCR no aporta. Como `_ui_poll_loop` solo corre durante la
  corrida, el display multi-temp aparece únicamente mientras el experimento está
  activo. Host-only.
- **Reconstrucción completa cada tick.** `_ui_poll_loop` arma el status entero
  (`Temperature…` / `State: …` / `Time passed…`) desde cero en cada iteración;
  es el único escritor de `svar_status` durante la corrida. El patrón previo
  leía y partía el valor anterior (`get().split("\n")`) para parchar índices
  concretos, lo que asumía **una línea por slot**: al poner `State:` en su propia
  línea (dos `\n` en el status) las líneas viejas dejaban de sobreescribirse y el
  label crecía sin límite (una línea por tick). Reconstruir sin releer fija el
  número de líneas.

## Orden de los campos (crítico)

| índice payload | campo    | sensor            | clave          | etiqueta      |
|:--------------:|----------|-------------------|----------------|---------------|
| 0              | `t_amb`  | MLX90614 ambiente | `ir_ambient`   | IR Ambient    |
| 1              | `t_obj`  | MLX90614 objeto   | `ir_object`    | IR Object     |
| 2              | `t_tc`   | MAX31855 termocupla | `thermocouple` | Thermocouple |

El combobox se muestra en orden **Thermocouple, IR Object, IR Ambient**
(termocupla primero = comportamiento por defecto previo).

__author__ = "Edisson A. Naula"
